"""Turn free-text trial eligibility criteria into evaluable predicates.

Subsystem F, step 1 of 2. This module structures text. It does not read a case
and does not decide whether anyone matches -- that is `signals/trials.py`, and
keeping them apart is what lets extraction be cached and validated against a
fixed corpus while matching stays free and instant.

**Extraction is a one-time cost per trial; matching is a per-patient cost.**
That asymmetry is the whole design. An LLM call to structure a criteria section
is defensible because it happens once and the result is cached forever. An LLM
call to decide whether *this* patient matches would run on every query, cost
money per question, and -- worse -- be unreproducible.

Two extractors are provided:

* `RuleBasedExtractor` -- deterministic, offline, no API key. Handles the
  patterns that are genuinely regular in registry text (age bounds, ECOG caps,
  explicit prior-therapy exclusions). It is the default because a pipeline that
  cannot run without a paid API is a pipeline nobody runs.
* `LlmAssistedExtractor` -- wraps any callable matching `ExtractionModel`, for
  the long tail the rules miss. Results cache to disk keyed by a hash of the
  criteria text, so re-running never re-bills and a cached corpus stays stable
  even if the registry edits the source record.

**Anything not confidently parsed becomes an `UNPARSEABLE` predicate, never a
dropped line.** A criterion silently discarded reads downstream as a criterion
the patient satisfies, which is the failure mode that turns "we could not read
this" into "you are eligible".
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

PredicateType = Literal[
    "AGE_RANGE",
    "PRIOR_THERAPY_EXCLUDES",
    "BIOMARKER_REQUIRES",
    "ECOG_MAX",
    "DISEASE_STAGE_REQUIRES",
    "UNPARSEABLE",
]

#: Which half of the criteria section a line came from. Inclusion and exclusion
#: invert the meaning of the same sentence -- "prior anthracycline therapy" is a
#: requirement under Inclusion and a disqualifier under Exclusion -- so the
#: section is tracked rather than inferred from wording.
CriterionSection = Literal["inclusion", "exclusion", "unknown"]

Comparison = Literal["equals", "not_equals", "at_least", "at_most", "present", "absent"]


@dataclass(frozen=True)
class Predicate:
    """One structured, evaluable eligibility criterion.

    `source_text` is mandatory and never paraphrased. Every bucket this feeds
    has to cite the criterion that produced it, and a clinician checking the
    reasoning needs the registry's own words, not ours.
    """

    type: PredicateType
    source_text: str
    section: CriterionSection = "unknown"
    #: What the criterion is about: a drug name, a biomarker, "age", "ECOG".
    subject: str | None = None
    comparison: Comparison | None = None
    value: str | float | None = None
    #: Why extraction gave up, populated only on UNPARSEABLE.
    reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> Predicate:
        return cls(**payload)


@dataclass
class ExtractionResult:
    registry_id: str
    predicates: list[Predicate] = field(default_factory=list)
    #: Which extractor produced this, recorded so a mixed-provenance corpus can
    #: be audited and so an accuracy figure can be attributed to a method.
    extractor: str = "unknown"
    #: Lines the extractor saw. Used to assert nothing was silently dropped.
    lines_seen: int = 0

    @property
    def unparseable(self) -> list[Predicate]:
        return [p for p in self.predicates if p.type == "UNPARSEABLE"]

    @property
    def parsed_fraction(self) -> float:
        if not self.predicates:
            return 0.0
        return 1.0 - len(self.unparseable) / len(self.predicates)


@runtime_checkable
class ExtractionModel(Protocol):
    """Any callable that turns one criteria section into predicate dicts."""

    def __call__(self, criteria_text: str) -> list[dict]: ...


# ---------------------------------------------------------------------------
# Splitting the section
# ---------------------------------------------------------------------------

#: Sponsors qualify these headers freely -- "Inclusion Criteria for All
#: Patients", "Exclusion Criteria (Cohort B):" -- so the pattern anchors at the
#: start and allows a trailing qualifier. Requiring the line to end after
#: "Criteria" silently left whole sections marked `unknown`, which loses the
#: inclusion/exclusion sense that inverts every criterion's meaning.
_INCLUSION_HEADER = re.compile(r"^\s*[*\-•]?\s*(?:\d+[.)]\s*)?inclusion\s+criteria\b", re.I)
_EXCLUSION_HEADER = re.compile(r"^\s*[*\-•]?\s*(?:\d+[.)]\s*)?exclusion\s+criteria\b", re.I)

#: ClinicalTrials.gov escapes comparison operators in its own free text
#: ("Bilirubin \> 3.0"). Left in place they defeat every numeric pattern here.
_MD_ESCAPE = re.compile(r"\\([<>*_\[\]()#+\-.!])")
#: Registry text is a bulleted list far more often than prose, but the bullet
#: character is inconsistent across sponsors.
_BULLET = re.compile(r"^\s*(?:[*\-•·]|\d+[.)])\s+")


def split_criteria(criteria_text: str) -> list[tuple[CriterionSection, str]]:
    """Split a criteria section into (section, line) pairs.

    Headers switch the active section; everything after an inclusion header is
    inclusion until an exclusion header appears. Text before any header is
    `unknown` rather than assumed to be inclusion -- guessing here would invert
    the meaning of every criterion from a sponsor who omits the headers.
    """
    section: CriterionSection = "unknown"
    out: list[tuple[CriterionSection, str]] = []
    for raw in criteria_text.splitlines():
        line = _MD_ESCAPE.sub(r"\1", raw).strip()
        if not line:
            continue
        if _INCLUSION_HEADER.match(line):
            section = "inclusion"
            continue
        if _EXCLUSION_HEADER.match(line):
            section = "exclusion"
            continue
        cleaned = _BULLET.sub("", line).strip()
        if cleaned:
            out.append((section, cleaned))
    return out


# ---------------------------------------------------------------------------
# Rule-based extraction
# ---------------------------------------------------------------------------

_AGE_MIN = re.compile(
    r"(?:>=|≥|at\s+least|minimum\s+(?:of\s+)?|older\s+than|"
    r"(?<![<≤])\bage[ds]?\s+)\s*(\d{1,3})\s*(?:years?|yrs?|y/o)?\b",
    re.I,
)
_AGE_MAX = re.compile(
    r"(?:<=|≤|no\s+(?:more|older)\s+than|younger\s+than|up\s+to|maximum\s+(?:of\s+)?)"
    r"\s*(\d{1,3})\s*(?:years?|yrs?|y/o)?\b",
    re.I,
)
_AGE_WORD = re.compile(r"\bage[ds]?\b|\byears?\s+of\s+age\b", re.I)
_ECOG_WORD = re.compile(r"\becog\b|\bperformance\s+status\b|\bkarnofsky\b", re.I)
#: Sponsors write the cap several ways: "ECOG <= 2", "ECOG of 2", "ECOG 0-2",
#: "performance status 0 to 1", or a bare "ECOG 2". The RANGE form is tried
#: first because "0-2" also contains a bare "0", and taking the lower bound as
#: the cap would exclude exactly the patients the trial is most open to.
_ECOG_RANGE = re.compile(r"\b[0-4]\s*(?:[-–—]|\bto\b|\bor\b)\s*([0-4])\b", re.I)
_ECOG_VALUE = re.compile(r"(?:<=|≤|of|is|:|score|status)\s*([0-4])\b", re.I)
_ECOG_BARE = re.compile(r"\b([0-4])\b")
_PRIOR_THERAPY = re.compile(
    r"\b(?:prior|previous|preceding|received|treated\s+with)\b[^.\n]{0,80}?"
    r"\b(?:therapy|therapies|treatment|chemotherapy|inhibitor|agent|regimen)\b",
    re.I,
)
#: "positive" and "negative" are deliberately NOT triggers. They fire on
#: unrelated serology -- "Subjects testing positive for HIV" in a transplant
#: workup is not a tumour-biomarker criterion, and treating it as one was a
#: measured C1 failure against the annotated corpus.
_BIOMARKER = re.compile(
    r"\b(?:mutation|mutated|amplif\w*|fusion|overexpress\w*|deficien\w*|"
    r"wild[- ]?type|immunohistochemistry|IHC|loss\s+of)\b",
    re.I,
)

#: Gene / marker symbols: 2-8 chars, uppercase, at least one letter.
_GENE_TOKEN = re.compile(r"\b([A-Z][A-Z0-9]{1,7})\b")

#: Uppercase tokens that look like gene symbols and are not. Without this,
#: "HIV", "DLCO" and "ECOG" all read as biomarkers.
_NOT_A_GENE: frozenset[str] = frozenset(
    {
        "HIV",
        "HBV",
        "HCV",
        "HTLV",
        "EBV",
        "CMV",
        "HSV",
        "TB",
        "COVID",
        "ECOG",
        "RECIST",
        "WHO",
        "NCI",
        "CTCAE",
        "FDA",
        "IRB",
        "ICF",
        "CT",
        "MRI",
        "PET",
        "MIBG",
        "DLCO",
        "ANC",
        "ULN",
        "LVEF",
        "EF",
        "DNA",
        "RNA",
        "PCR",
        "IHC",
        "FISH",
        "NGS",
        "HLA",
        "BSA",
        "IV",
        "US",
        "UK",
        "EU",
        "AND",
        "OR",
        "NOT",
        "ALL",
        "ANY",
        "NONE",
    }
)

#: Drug-name suffixes and explicit class phrases. Conservative on purpose: a
#: wrongly named agent produces a confidently wrong exclusion, while an
#: unnamed one produces `needs_verification`, which is the honest answer.
_AGENT_SUFFIX = re.compile(
    r"\b([a-z]{3,}(?:mab|nib|tinib|ciclib|parib|platin|rubicin|taxel|mustine|"
    r"tecan|zomib|limus|degib|sertib))\b",
    re.I,
)
_AGENT_CLASS = re.compile(
    r"\b((?:PARP|PD-?L?1|CDK4/6|CDK|MEK|BRAF|ALK|EGFR|VEGF|mTOR|PI3K|TKI|"
    r"tyrosine\s+kinase|checkpoint|anthracycline|platinum|alkylating|taxane)"
    r"(?:\s+inhibitor|\s+therapy|\s+agent)?)\b",
    re.I,
)


def _first_gene(line: str) -> str | None:
    for match in _GENE_TOKEN.finditer(line):
        token = match.group(1)
        if token not in _NOT_A_GENE and any(ch.isalpha() for ch in token):
            return token
    return None


def _first_agent(line: str) -> str | None:
    if match := _AGENT_CLASS.search(line):
        return match.group(1)
    if match := _AGENT_SUFFIX.search(line):
        return match.group(1)
    return None


_STAGE = re.compile(r"\bstage\s+(0|IV|I{1,3}|[1-4])\b", re.I)


class RuleBasedExtractor:
    """Deterministic extraction of the genuinely regular patterns.

    Recall is modest by design. The alternative to admitting that is guessing,
    and a wrong predicate is worse than an `UNPARSEABLE` one: a wrong predicate
    buckets a patient confidently, while `UNPARSEABLE` sends them to
    `needs_verification`, which is the honest answer.
    """

    name = "rule_based"

    def extract(self, registry_id: str, criteria_text: str) -> ExtractionResult:
        lines = split_criteria(criteria_text)
        predicates = [self._line_to_predicate(section, line) for section, line in lines]
        return ExtractionResult(
            registry_id=registry_id,
            predicates=predicates,
            extractor=self.name,
            lines_seen=len(lines),
        )

    def _line_to_predicate(self, section: CriterionSection, line: str) -> Predicate:
        # ECOG first: "ECOG 0-2" also contains a bare number that the age
        # patterns would otherwise be tempted by.
        if _ECOG_WORD.search(line):
            match = _ECOG_RANGE.search(line) or _ECOG_VALUE.search(line) or _ECOG_BARE.search(line)
            if match:
                return Predicate(
                    type="ECOG_MAX",
                    source_text=line,
                    section=section,
                    subject="ECOG",
                    comparison="at_most",
                    value=float(match.group(1)),
                )

        if _AGE_WORD.search(line):
            low = _AGE_MIN.search(line)
            high = _AGE_MAX.search(line)
            if low or high:
                return Predicate(
                    type="AGE_RANGE",
                    source_text=line,
                    section=section,
                    subject="age",
                    comparison=(
                        "at_least"
                        if low and not high
                        else "at_most" if high and not low else "equals"
                    ),
                    value=f"{low.group(1) if low else ''}-{high.group(1) if high else ''}",
                )

        if match := _STAGE.search(line):
            return Predicate(
                type="DISEASE_STAGE_REQUIRES",
                source_text=line,
                section=section,
                subject="stage",
                comparison="equals",
                value=match.group(1).upper(),
            )

        # A typed predicate is emitted ONLY when its subject can be named.
        # An unnamed subject is not evaluable -- the matcher resolves it to
        # `unresolved` either way -- so asserting a type buys nothing and risks
        # being wrong. The suspicion is preserved in `reason` instead.
        if _PRIOR_THERAPY.search(line):
            agent = _first_agent(line)
            if agent is None:
                return Predicate(
                    type="UNPARSEABLE",
                    source_text=line,
                    section=section,
                    reason="reads as a prior-therapy criterion, but no agent could be named",
                )
            return Predicate(
                type="PRIOR_THERAPY_EXCLUDES",
                source_text=line,
                section=section,
                subject=agent,
                comparison="absent" if section == "exclusion" else "present",
            )

        if _BIOMARKER.search(line):
            gene = _first_gene(line)
            if gene is None:
                return Predicate(
                    type="UNPARSEABLE",
                    source_text=line,
                    section=section,
                    reason="reads as a biomarker criterion, but no marker could be named",
                )
            return Predicate(
                type="BIOMARKER_REQUIRES",
                source_text=line,
                section=section,
                subject=gene,
                comparison="present",
            )

        return Predicate(
            type="UNPARSEABLE",
            source_text=line,
            section=section,
            reason="no rule matched this line",
        )


# ---------------------------------------------------------------------------
# LLM-assisted extraction, cached
# ---------------------------------------------------------------------------


def criteria_fingerprint(criteria_text: str) -> str:
    """Cache key. Hashes the TEXT, not the registry id.

    Registries edit records in place. Keying on the id would serve a cached
    parse of text that no longer exists; keying on the text means an edited
    record is re-extracted and an unchanged one never is.
    """
    return hashlib.sha256(criteria_text.encode("utf-8")).hexdigest()


class LlmAssistedExtractor:
    """Wraps an `ExtractionModel`, caching every result to disk.

    Falls back to the rule-based extractor when the model is unavailable or
    returns something unusable, rather than failing the load. A trial with
    rule-based predicates is worth more than no trial at all.
    """

    name = "llm_assisted"

    def __init__(
        self,
        model: ExtractionModel,
        *,
        cache_dir: Path | str,
        fallback: RuleBasedExtractor | None = None,
    ) -> None:
        self.model = model
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.fallback = fallback or RuleBasedExtractor()
        self.cache_hits = 0
        self.model_calls = 0
        self.fallbacks = 0

    def _cache_path(self, criteria_text: str) -> Path:
        return self.cache_dir / f"{criteria_fingerprint(criteria_text)}.json"

    def extract(self, registry_id: str, criteria_text: str) -> ExtractionResult:
        path = self._cache_path(criteria_text)
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.cache_hits += 1
                return ExtractionResult(
                    registry_id=registry_id,
                    predicates=[Predicate.from_dict(p) for p in payload["predicates"]],
                    extractor=payload.get("extractor", self.name),
                    lines_seen=payload.get("lines_seen", 0),
                )
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("ignoring unreadable extraction cache %s: %s", path, exc)

        try:
            predicates = [Predicate.from_dict(p) for p in self.model(criteria_text)]
            self.model_calls += 1
        except (TypeError, KeyError, ValueError) as exc:
            # A model returning the wrong shape is a bug worth seeing, but it
            # must not take the whole load down with it.
            logger.warning("extraction model returned an unusable result: %s", exc)
            self.fallbacks += 1
            return self.fallback.extract(registry_id, criteria_text)

        result = ExtractionResult(
            registry_id=registry_id,
            predicates=predicates,
            extractor=self.name,
            lines_seen=len(split_criteria(criteria_text)),
        )
        path.write_text(
            json.dumps(
                {
                    "extractor": result.extractor,
                    "lines_seen": result.lines_seen,
                    "predicates": [p.to_dict() for p in result.predicates],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return result
