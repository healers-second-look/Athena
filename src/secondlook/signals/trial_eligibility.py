"""Match a case against extracted trial eligibility predicates.

Subsystem F, step 2 of 2. Pure predicate evaluation: **no LLM calls, no network,
no I/O.** Extraction (`tier1/criteria_extraction.py`) is a one-time cached cost
per trial; this runs per patient per query and must therefore be fast and free.

Lives in its own module rather than `signals/trials.py` -- issue #6 (Signal
Generator Layer) and issue #7 (Trial Intelligence) both named `signals/trials.py`
as their deliverable, but they're not the same thing: `trials.py::generate()` is
a Signal Generator Layer plugin (`generate(change_set, question) -> SignalBatch`,
dispatched by `signals/registry.py`), while this module is a pure matching
engine with a different signature (`match_trials(extractions, case)`) that
`generate()` does not yet call. Wiring eligibility bucketing into the dispatch
path needs `CaseState` threaded through `dispatch()`, which none of the other
generators currently receive either -- that's tracked separately, not solved by
a file rename. See the issue this module's own PR links for the tracking issue.

## The rule that matters most

**A criterion referencing a case field that is not recorded resolves to
`needs_verification`, never to a guess.**

An unrecorded ECOG score is not an ECOG of 0. An unknown prior-therapy history is
not an empty one. Treating absent data as satisfying a criterion is how a
matcher tells someone they are eligible for a trial that will turn them away --
so absence resolves to "a human must check this", and the specific criterion is
named so they know what to check.

## Buckets

| Bucket | Condition |
|---|---|
| `highly_compatible` | every criterion evaluates true |
| `probably_incompatible` | at least one criterion evaluates false |
| `needs_verification` | at least one unresolved, and none false |

`probably_incompatible` wins over `needs_verification` when both apply: a
criterion the case definitively fails is not made uncertain by another criterion
being unknown.

## What this cannot yet decide

`CaseState` (Subsystem C) records alterations, biomarkers, treatments and
assessments. It has **no age, ECOG, or disease-stage field**, so predicates of
those types cannot be evaluated from a case at all and always land in
`unresolved`. Age and ECOG are looked up through the free-form `biomarkers` dict
as a bridge, which works if an intake pipeline chooses to record them there;
stage has no bridge.

This is a real gap between F and C, not a defect in either. It is surfaced by
`unresolvable_predicate_types()` rather than hidden, so the size of it is
measurable before anyone relies on the buckets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from secondlook.tier1.criteria_extraction import Predicate

Bucket = Literal["highly_compatible", "needs_verification", "probably_incompatible"]

Outcome = Literal["matched", "violated", "unresolved"]

#: Predicate types with no corresponding CaseState field. Kept explicit so the
#: gap is countable rather than showing up as a mysteriously large
#: needs_verification rate.
NO_CASE_FIELD: frozenset[str] = frozenset({"DISEASE_STAGE_REQUIRES"})

#: Names an intake pipeline might use for these in the free-form biomarker dict.
_AGE_KEYS = ("age", "age_years", "patient_age")
_ECOG_KEYS = ("ecog", "ecog_ps", "performance_status")

_AGE_BOUNDS = re.compile(r"^(\d{1,3})?-(\d{1,3})?$")


@dataclass
class CriterionOutcome:
    """One criterion's verdict, with the registry's own words attached."""

    predicate: Predicate
    outcome: Outcome
    #: Why. Always populated -- a bucket a clinician cannot interrogate is not
    #: usable, and "unresolved" without a reason is indistinguishable from a bug.
    explanation: str

    @property
    def source_text(self) -> str:
        return self.predicate.source_text


@dataclass
class TrialMatchResult:
    trial_id: str
    bucket: Bucket
    outcomes: list[CriterionOutcome] = field(default_factory=list)

    def _texts(self, outcome: Outcome) -> list[str]:
        return [o.source_text for o in self.outcomes if o.outcome == outcome]

    @property
    def matched_criteria(self) -> list[str]:
        return self._texts("matched")

    @property
    def unresolved_criteria(self) -> list[str]:
        return self._texts("unresolved")

    @property
    def violated_criteria(self) -> list[str]:
        return self._texts("violated")

    def unresolvable_predicate_types(self) -> dict[str, int]:
        """Unresolved counts by predicate type.

        Distinguishes "this case is missing data" from "F cannot evaluate this
        kind of criterion at all". The second is a gap to close in C or in
        intake, and it should not be mistaken for a sparse case record.
        """
        counts: dict[str, int] = {}
        for outcome in self.outcomes:
            if outcome.outcome == "unresolved":
                key = outcome.predicate.type
                counts[key] = counts.get(key, 0) + 1
        return counts


def _biomarker(case, keys: tuple[str, ...]) -> float | None:
    """Case-insensitive lookup across candidate names in the biomarker dict."""
    biomarkers = getattr(case, "biomarkers", {}) or {}
    lowered = {str(name).strip().lower(): value for name, value in biomarkers.items()}
    for key in keys:
        entry = lowered.get(key)
        if entry is None:
            continue
        value = getattr(entry, "value", entry)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _mentions(text: str, haystack: str) -> bool:
    """Whole-word containment, case-insensitive.

    Substring matching would make "ALK" match "alkylating agent" -- the exact
    class of error the project's DOID-over-name-matching rule exists to prevent.
    """
    return re.search(rf"\b{re.escape(text.strip())}\b", haystack, re.I) is not None


def _evaluate_age(predicate: Predicate, case) -> CriterionOutcome:
    age = _biomarker(case, _AGE_KEYS)
    if age is None:
        return CriterionOutcome(
            predicate,
            "unresolved",
            "The case records no age. An unrecorded age is not an eligible age.",
        )
    bounds = _AGE_BOUNDS.match(str(predicate.value or ""))
    if not bounds:
        return CriterionOutcome(
            predicate, "unresolved", f"Could not read an age bound from {predicate.value!r}."
        )
    low, high = bounds.group(1), bounds.group(2)
    if low and age < float(low):
        return CriterionOutcome(predicate, "violated", f"Case age {age:.0f} is below {low}.")
    if high and age > float(high):
        return CriterionOutcome(predicate, "violated", f"Case age {age:.0f} is above {high}.")
    return CriterionOutcome(predicate, "matched", f"Case age {age:.0f} is within range.")


def _evaluate_ecog(predicate: Predicate, case) -> CriterionOutcome:
    ecog = _biomarker(case, _ECOG_KEYS)
    if ecog is None:
        return CriterionOutcome(
            predicate,
            "unresolved",
            "The case records no ECOG score. An unrecorded score is not a score of 0.",
        )
    cap = predicate.value
    if not isinstance(cap, (int, float)):
        return CriterionOutcome(predicate, "unresolved", "No numeric ECOG cap was extracted.")
    if ecog > float(cap):
        return CriterionOutcome(
            predicate, "violated", f"Case ECOG {ecog:.0f} exceeds the cap of {cap:.0f}."
        )
    return CriterionOutcome(
        predicate, "matched", f"Case ECOG {ecog:.0f} is within the cap of {cap:.0f}."
    )


def _evaluate_prior_therapy(predicate: Predicate, case) -> CriterionOutcome:
    if not predicate.subject:
        # Extraction declines to guess the agent out of the sentence rather than
        # risk naming the wrong one, so there is nothing to check against.
        return CriterionOutcome(
            predicate,
            "unresolved",
            "The criterion names a prior therapy that extraction could not identify "
            "specifically. A human must read the criterion.",
        )
    regimens = " ".join(t.regimen for t in getattr(case, "treatments", ()) or ())
    received = _mentions(predicate.subject, regimens)
    if predicate.section == "exclusion":
        if received:
            return CriterionOutcome(
                predicate,
                "violated",
                f"The case records prior {predicate.subject}, which this criterion excludes.",
            )
        if not regimens:
            return CriterionOutcome(
                predicate,
                "unresolved",
                "The case records no treatment history. Absent history is not an "
                "absence of treatment.",
            )
        return CriterionOutcome(
            predicate, "matched", f"No prior {predicate.subject} in the recorded history."
        )
    if received:
        return CriterionOutcome(
            predicate, "matched", f"The case records the required prior {predicate.subject}."
        )
    return CriterionOutcome(
        predicate,
        "unresolved",
        f"No prior {predicate.subject} recorded, but the history may be incomplete.",
    )


def _evaluate_biomarker(predicate: Predicate, case) -> CriterionOutcome:
    if not predicate.subject:
        return CriterionOutcome(
            predicate,
            "unresolved",
            "The criterion requires a biomarker that extraction could not name "
            "specifically. A human must read the criterion.",
        )
    haystack = " ".join(
        [
            *(str(name) for name in (getattr(case, "biomarkers", {}) or {})),
            *(f"{a.gene} {a.variant}" for a in getattr(case, "alterations", ()) or ()),
        ]
    )
    if _mentions(predicate.subject, haystack):
        return CriterionOutcome(predicate, "matched", f"The case records {predicate.subject}.")
    return CriterionOutcome(
        predicate,
        "unresolved",
        f"The case does not record {predicate.subject}. Not testing for a marker is "
        "not the same as testing negative.",
    )


def evaluate_predicate(predicate: Predicate, case) -> CriterionOutcome:
    """One predicate against one case. Never raises, never guesses."""
    if predicate.type == "UNPARSEABLE":
        return CriterionOutcome(
            predicate,
            "unresolved",
            predicate.reason or "This criterion could not be structured and must be read.",
        )
    if predicate.type in NO_CASE_FIELD:
        return CriterionOutcome(
            predicate,
            "unresolved",
            f"{predicate.type} cannot be evaluated: CaseState records no such field.",
        )
    if predicate.type == "AGE_RANGE":
        return _evaluate_age(predicate, case)
    if predicate.type == "ECOG_MAX":
        return _evaluate_ecog(predicate, case)
    if predicate.type == "PRIOR_THERAPY_EXCLUDES":
        return _evaluate_prior_therapy(predicate, case)
    if predicate.type == "BIOMARKER_REQUIRES":
        return _evaluate_biomarker(predicate, case)
    return CriterionOutcome(
        predicate, "unresolved", f"No evaluation rule for predicate type {predicate.type}."
    )


def match_trial(trial_id: str, predicates: list[Predicate], case) -> TrialMatchResult:
    """Bucket one trial for one case.

    A trial with **no** predicates is `needs_verification`, not
    `highly_compatible`. "Every criterion passed" is vacuously true of an empty
    list, and bucketing an unread trial as a strong match is the worst error
    available here.
    """
    outcomes = [evaluate_predicate(p, case) for p in predicates]
    if not outcomes:
        return TrialMatchResult(trial_id, "needs_verification", outcomes)
    if any(o.outcome == "violated" for o in outcomes):
        bucket: Bucket = "probably_incompatible"
    elif any(o.outcome == "unresolved" for o in outcomes):
        bucket = "needs_verification"
    else:
        bucket = "highly_compatible"
    return TrialMatchResult(trial_id, bucket, outcomes)


def match_trials(extractions: dict[str, list[Predicate]], case) -> list[TrialMatchResult]:
    """Match many trials, ordered most compatible first.

    Ties keep registry-id order so two runs over the same inputs produce the
    same list -- a result order that shuffles between runs is not reviewable.
    """
    order = {"highly_compatible": 0, "needs_verification": 1, "probably_incompatible": 2}
    results = [match_trial(tid, preds, case) for tid, preds in extractions.items()]
    return sorted(results, key=lambda r: (order[r.bucket], r.trial_id))
