"""Citation-gate accepted-sentence-rate adapter for the LLM eval harness.

Measures `citation_gate.enforce_citations` as applied by `generate_synthesis`
against a configured LLM. The gate itself is unchanged; this adapter only
scores the accepted-sentence rate and reports it through `EvalResult` /
`derive_verdict`.

Fixtures are the same two synthetic cases the standalone
`validation/synthesis_citation_acceptance.py` script used when it stood
alone. Expand only by adding fixtures, never by retuning the gate.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from secondlook.case.diff import Change, ChangeKind
from secondlook.case.questions import Question
from secondlook.harness.llm_eval import EvalResult, derive_verdict
from secondlook.signals.types import (
    ComputedMethod,
    DocumentedSource,
    EvidenceClass,
    Signal,
    SignalKind,
)
from secondlook.synthesis.generate import SYSTEM_PROMPT_VERSION, generate_synthesis
from secondlook.synthesis.llm_client import LLMClient, LLMClientError, get_llm_client

#: Same floor as `SYNTHESIS_THRESHOLD` / `INTAKE_THRESHOLD`, chosen before
#: any live-model run and not fitted to one. The fixture set is two
#: synthetic cases -- enough to exercise the gate, not enough to certify
#: perfect citation discipline. A 1.0 bar would claim precision this
#: corpus cannot support. Falling below 70% means more than three in ten
#: generated sentences were dropped by the gate: that is a documented
#: outcome, not a reason to move the constant.
CITATION_ACCEPTANCE_THRESHOLD = 0.70

CITATION_ACCEPTANCE_SUBSYSTEM = "synthesis.citation_acceptance"
CITATION_ACCEPTANCE_PROMPT_TEMPLATE_ID = SYSTEM_PROMPT_VERSION

NOW = datetime(2026, 8, 23, tzinfo=UTC)

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?\]])\s+")

_UNSET = object()


def _question(text: str) -> Question:
    change = Change(
        kind=ChangeKind.NEW_ALTERATION,
        summary="EGFR T790M newly observed",
        detail={"gene": "EGFR", "variant": "T790M"},
        triggering_event_id="evt-1",
    )
    return Question(
        kind=ChangeKind.NEW_ALTERATION,
        text=text,
        detail={"gene": "EGFR", "variant": "T790M", "cancer_type": "NSCLC"},
        priority=3,
        triggering_change=change,
    )


def _documented(item_id: str, claim: str) -> Signal:
    return Signal(
        kind=SignalKind.DOCUMENTED_EVIDENCE,
        evidence_class=EvidenceClass.DOCUMENTED,
        claim=claim,
        source=DocumentedSource(
            citation_url=f"https://civicdb.org/evidence/{item_id}",
            citation_id=item_id,
        ),
        confidence="high",
        caveats=(),
        computed_at=NOW,
        generator_version="validation",
    )


def _computed() -> Signal:
    return Signal(
        kind=SignalKind.COMPUTATIONAL,
        evidence_class=EvidenceClass.COMPUTED,
        claim="Proximity to ligand is 3.1 Å.",
        source=ComputedMethod(method="proximity", version="graph.py/1"),
        confidence="stated",
        caveats=("measurement, not a validated classifier",),
        computed_at=NOW,
        generator_version="validation",
    )


# Synthetic fixtures -- not a gold-standard set. Enough to exercise the
# gate against a candidate model; expand only by adding fixtures, never
# by retuning the gate to fit a model's failures.
FIXTURES: tuple[tuple[str, Question, list[Signal]], ...] = (
    (
        "single_documented",
        _question("What documented evidence exists for EGFR T790M in NSCLC?"),
        [
            _documented(
                "civic_12",
                "EGFR T790M confers sensitivity to osimertinib.",
            )
        ],
    ),
    (
        "documented_plus_computed",
        _question("What documented evidence exists for EGFR T790M in NSCLC?"),
        [
            _computed(),
            _documented(
                "civic_12",
                "EGFR T790M confers sensitivity to osimertinib.",
            ),
        ],
    ),
)


def _sentence_count(text: str) -> int:
    return sum(1 for part in _SENTENCE_BOUNDARY.split(text.strip()) if part.strip())


def accepted_sentence_rate(*, dropped: int, accepted_n: int) -> float | None:
    total = accepted_n + dropped
    if total == 0:
        return None
    return 1.0 - (dropped / total)


def _resolve_client(llm_client: object) -> LLMClient | None:
    if llm_client is _UNSET:
        return get_llm_client()
    return llm_client  # type: ignore[return-value]


def measure_citation_acceptance(*, llm_client: object = _UNSET) -> list[dict]:
    """Run FIXTURES once. Raises if the client is missing or degrades."""
    client = _resolve_client(llm_client)
    if client is None:
        raise RuntimeError(
            "citation-acceptance eval needs a configured LLM client "
            "(ATHENA_LLM_ENABLED is off, or provider config is missing)"
        )

    rows: list[dict] = []
    for name, question, signals in FIXTURES:
        result = generate_synthesis(question, signals, llm_client=client, now=NOW)
        if not result.llm_used:
            raise LLMClientError(
                f"citation-acceptance fixture {name!r} degraded to the template "
                "path; the configured endpoint is unreachable or returned an "
                "unusable payload"
            )
        accepted_n = _sentence_count(result.text)
        rate = accepted_sentence_rate(
            dropped=result.dropped_sentence_count,
            accepted_n=accepted_n,
        )
        rows.append(
            {
                "name": name,
                "accepted_n": accepted_n,
                "dropped": result.dropped_sentence_count,
                "accepted_rate": rate,
                "llm_used": result.llm_used,
                "cited_ids": list(result.cited_ids),
            }
        )
    return rows


def eval_result_from_measurements(rows: list[dict]) -> EvalResult:
    rates = [0.0 if row["accepted_rate"] is None else row["accepted_rate"] for row in rows]
    pass_rate = sum(rates) / len(rates) if rates else 0.0
    violations: list[str] = []
    return EvalResult(
        subsystem=CITATION_ACCEPTANCE_SUBSYSTEM,
        prompt_template_id=CITATION_ACCEPTANCE_PROMPT_TEMPLATE_ID,
        pass_rate=pass_rate,
        threshold=CITATION_ACCEPTANCE_THRESHOLD,
        safety_violations=violations,
        verdict=derive_verdict(pass_rate, CITATION_ACCEPTANCE_THRESHOLD, violations),
    )


def evaluate_citation_acceptance(*, llm_client: object = _UNSET) -> EvalResult:
    """Average accepted-sentence rate across FIXTURES, then `derive_verdict`."""
    return eval_result_from_measurements(measure_citation_acceptance(llm_client=llm_client))
