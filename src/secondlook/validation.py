"""Gold-standard validation harness (`validation-plan.md`).

Runs the nine known-directionality cases through the Step 7 pipeline and scores
the result against criteria that were **pre-committed before any run**. The
criteria live here as constants precisely so they cannot be quietly adjusted
after seeing results — `validation-plan.md` is explicit that they are set before
running and not tuned afterwards.

This module defines the cases and the scoring. Running them is
`validation/run_gold_standard.py`, which caches each case so that sweeping a
Step 6 cutoff costs no recomputation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from secondlook.labeling import MethodCalibration, ScoringMethod

KnownDirection = Literal["resistance", "sensitive"]

#: Correct directionality required on at least this fraction of cases.
PASS_THRESHOLD = 0.70

#: `validation-plan.md`: these two "designed-for" positive controls must both
#: show retained/increased binding regardless of the overall pass rate. Either
#: failing means the pipeline is not demo-ready as-is.
HARD_REQUIRED_CONTROLS = (("BRAF", "V600E", "vemurafenib"), ("EGFR", "T790M", "osimertinib"))


@dataclass(frozen=True)
class GoldStandardCase:
    gene: str
    mutation: str
    drug: str
    known_direction: KnownDirection
    note: str

    @property
    def is_hard_required_control(self) -> bool:
        return (self.gene, self.mutation, self.drug.lower()) in {
            (g, m, d.lower()) for g, m, d in HARD_REQUIRED_CONTROLS
        }

    @property
    def expected_label(self) -> str:
        if self.known_direction == "resistance":
            return "likely_reduced_binding"
        return "likely_retained_or_increased_binding"


#: The nine cases from `validation-plan.md`, verbatim.
GOLD_STANDARD_CASES: tuple[GoldStandardCase, ...] = (
    GoldStandardCase("EGFR", "T790M", "gefitinib", "resistance", "Gatekeeper mutation"),
    GoldStandardCase("EGFR", "T790M", "osimertinib", "sensitive", "3rd-gen, designed for T790M"),
    GoldStandardCase(
        "EGFR", "C797S", "osimertinib", "resistance", "Abolishes covalent binding at C797"
    ),
    GoldStandardCase("ABL1", "T315I", "imatinib", "resistance", "Classic gatekeeper mutation"),
    GoldStandardCase("KIT", "D816V", "imatinib", "resistance", "Kinase-domain mutation"),
    GoldStandardCase(
        "KIT", "V560G", "imatinib", "sensitive", "Juxtamembrane; contrast case for D816V"
    ),
    GoldStandardCase(
        "BRAF", "V600E", "vemurafenib", "sensitive", "Drug designed for this mutation"
    ),
    GoldStandardCase(
        "ALK", "G1202R", "crizotinib", "resistance", "Sensitive to lorlatinib instead"
    ),
    GoldStandardCase(
        "ALK", "I1171T", "crizotinib", "resistance", "Sensitive to ceritinib/lorlatinib"
    ),
)


#: Stable opening of MUTATION_OUTSIDE_POCKET_MESSAGE. Matched as a prefix so a
#: case the method correctly ruled out of scope is not tallied as a wrong answer.
_OUT_OF_POCKET_PREFIX = "This mutation lies"


def proximity_rows(payloads: dict[str, dict[str, Any]]) -> list[tuple[str, str, float | None, str]]:
    """Measured binding-site proximity per case, for reporting as observation.

    Deliberately **not** scored against a pass criterion. `validation-plan.md`
    pre-committed directionality only; inventing a proximity-accuracy metric after
    seeing these numbers would be defining the test to fit the data, which that
    document explicitly forbids. These are reported as measurements a reader can
    check, not as evidence of accuracy.
    """
    rows = []
    for case in GOLD_STANDARD_CASES:
        from secondlook.cache import cache_key

        payload = payloads.get(cache_key(case.gene, case.mutation))
        if payload is None:
            continue
        item = find_drug_result(payload, case.drug)
        prox = (item or {}).get("proximity") or {}
        distance = prox.get("distance_angstrom")
        band = prox.get("band")
        if band is None:
            continue
        rows.append((f"{case.gene} {case.mutation}", case.drug, distance, band))
    return rows


def is_out_of_pocket(payload: dict[str, Any]) -> bool:
    """True when the pipeline refused to score because the mutation is too far out."""
    return any(
        str(f.get("reason", "")).startswith(_OUT_OF_POCKET_PREFIX)
        for f in payload.get("failures", [])
    )


@dataclass(frozen=True)
class CaseOutcome:
    case: GoldStandardCase
    predicted_label: str | None
    method: ScoringMethod | None
    delta_score: float | None
    #: True only on a correct directional call. "uncertain" is not correct — but
    #: it is not *wrong* either; see `is_confidently_wrong`.
    correct: bool
    #: A directional call in the opposite direction to the known clinical answer.
    #: This is the failure mode that disqualifies a hard-required control.
    confidently_wrong: bool
    note: str
    #: The method determined this mutation is beyond docking's contact range.
    #: Not a wrong answer — an explicit, correct statement of scope. Tallied
    #: separately so it cannot inflate or deflate the directional-accuracy figure
    #: without being visible.
    out_of_scope: bool = False
    #: Whether the pipeline was actually run for this case. Distinguishing "not
    #: yet run" from "ran and got it wrong" is essential: reporting an unrun
    #: harness as a 0% pass rate would be a false claim about the pipeline's
    #: measured accuracy, which is the exact class of misleading output the
    #: project's "never state a fact you didn't compute" rule forbids.
    ran: bool = True


def find_drug_result(payload: dict[str, Any], drug: str) -> dict[str, Any] | None:
    """Locate the result item for `drug`, matching case-insensitively."""
    wanted = drug.strip().lower()
    for item in payload.get("results", []):
        if str(item.get("drug", "")).strip().lower() == wanted:
            return item
    return None


def score_case(case: GoldStandardCase, payload: dict[str, Any]) -> CaseOutcome:
    """Score one case's cached payload against its known direction."""
    item = find_drug_result(payload, case.drug)
    if item is None:
        out_of_scope = is_out_of_pocket(payload)
        if out_of_scope:
            reason = "mutation beyond docking contact range — method reports out of scope"
        elif payload.get("results"):
            reason = f"{case.drug} was not among the generated candidates"
        else:
            reason = f"pipeline produced no scored results (status={payload.get('status')})"
        return CaseOutcome(
            case=case,
            predicted_label=None,
            method=None,
            delta_score=None,
            correct=False,
            confidently_wrong=False,
            note=reason,
            out_of_scope=out_of_scope,
        )

    label = item.get("label")
    expected = case.expected_label
    opposite = (
        "likely_retained_or_increased_binding"
        if expected == "likely_reduced_binding"
        else "likely_reduced_binding"
    )
    return CaseOutcome(
        case=case,
        predicted_label=label,
        method=item.get("method"),
        delta_score=item.get("delta_score"),
        correct=label == expected,
        confidently_wrong=label == opposite,
        note=case.note,
    )


@dataclass(frozen=True)
class ValidationReport:
    outcomes: list[CaseOutcome]

    @property
    def scored(self) -> list[CaseOutcome]:
        return [o for o in self.outcomes if o.predicted_label is not None]

    @property
    def out_of_scope_count(self) -> int:
        return sum(1 for o in self.outcomes if o.out_of_scope)

    @property
    def in_scope(self) -> list[CaseOutcome]:
        """Cases the method claims it can answer at all."""
        return [o for o in self.outcomes if o.ran and not o.out_of_scope]

    @property
    def in_scope_correct(self) -> int:
        return sum(1 for o in self.in_scope if o.correct)

    @property
    def ran_count(self) -> int:
        return sum(1 for o in self.outcomes if o.ran)

    @property
    def has_been_run(self) -> bool:
        """False when no case has a cached run — the harness has not been executed.

        Every pass/fail property below is meaningless in that state, and
        `render_markdown` refuses to report a verdict rather than presenting an
        unrun harness as a measured 0% failure.
        """
        return self.ran_count > 0

    @property
    def is_complete_run(self) -> bool:
        return self.ran_count == len(self.outcomes)

    @property
    def correct_count(self) -> int:
        return sum(1 for o in self.outcomes if o.correct)

    @property
    def pass_rate(self) -> float:
        """Fraction correct over ALL cases, not only the ones that produced a label.

        Deliberate: a case the pipeline could not score is a case it got wrong
        from the user's perspective. Scoring only over successful runs would
        flatter the result by hiding coverage failures.
        """
        if not self.outcomes:
            return 0.0
        return self.correct_count / len(self.outcomes)

    @property
    def meets_pass_threshold(self) -> bool:
        return self.pass_rate >= PASS_THRESHOLD

    @property
    def failed_hard_controls(self) -> list[CaseOutcome]:
        return [o for o in self.outcomes if o.case.is_hard_required_control and not o.correct]

    @property
    def is_demo_ready(self) -> bool:
        """Both pre-committed criteria must hold — and the harness must have run."""
        return self.has_been_run and self.meets_pass_threshold and not self.failed_hard_controls

    @property
    def method_split(self) -> dict[str, int]:
        """mCSM-lig vs docking counts — the evidence for deliverable 5's coverage note."""
        counts: dict[str, int] = {}
        for outcome in self.scored:
            if outcome.method:
                counts[outcome.method] = counts.get(outcome.method, 0) + 1
        return counts


def build_report(payloads: dict[str, dict[str, Any]]) -> ValidationReport:
    """Score every gold-standard case. `payloads` is keyed by `cache_key`."""
    from secondlook.cache import cache_key

    outcomes = []
    for case in GOLD_STANDARD_CASES:
        payload = payloads.get(cache_key(case.gene, case.mutation))
        if payload is None:
            outcomes.append(
                CaseOutcome(
                    case=case,
                    predicted_label=None,
                    method=None,
                    delta_score=None,
                    correct=False,
                    confidently_wrong=False,
                    note="no cached run for this case",
                    ran=False,
                )
            )
            continue
        outcomes.append(score_case(case, payload))
    return ValidationReport(outcomes=outcomes)


def sweep_thresholds(
    payloads: dict[str, dict[str, Any]],
    candidate_calibrations: list[dict[ScoringMethod, MethodCalibration]],
) -> list[tuple[dict[ScoringMethod, MethodCalibration], ValidationReport]]:
    """Score every candidate cutoff against the same cached runs.

    Cheap by construction — re-labels cached deltas, makes no network calls.
    """
    from secondlook.cache import relabel_payload

    results = []
    for calibrations in candidate_calibrations:
        relabeled = {
            key: relabel_payload(payload, calibrations) for key, payload in payloads.items()
        }
        results.append((calibrations, build_report(relabeled)))
    return results


def render_markdown(report: ValidationReport) -> str:
    """Render the auditable results table `tier2-implementation-spec.md` §5 requires."""
    lines = [
        "# Tier 2 Gold-Standard Validation Results",
        "",
        "Generated by `validation/run_gold_standard.py`. Criteria were pre-committed in",
        "`docs/validation-plan.md` before any run and are not adjusted after seeing results.",
        "",
        "## Results",
        "",
        "| Gene | Mutation | Drug | Known direction | Predicted label | Method | Delta | Pass |",
        "|---|---|---|---|---|---|---|---|",
    ]
    # An unrun harness is not a failed one. Reporting "0/9, NOT MET, FAILED" for
    # a pipeline that was never executed would be a fabricated accuracy claim.
    if not report.has_been_run:
        return (
            "\n".join(
                lines[:5]
                + [
                    "## Status: NOT YET RUN",
                    "",
                    "No case has been executed, so there is **no measured pass "
                    "rate and no verdict**.",
                    "The criteria below are stated for reference only. Nothing in this file may be",
                    "cited as an accuracy figure until the harness runs.",
                    "",
                    "Run it with:",
                    "",
                    "```bash",
                    "python validation/run_gold_standard.py",
                    "```",
                    "",
                    "## Pre-committed criteria (not yet evaluated)",
                    "",
                    f"- Pass threshold: correct directionality on >= "
                    f"{PASS_THRESHOLD:.0%} of the nine cases.",
                    "- Hard requirement: BRAF V600E/vemurafenib and EGFR T790M/osimertinib must",
                    "  both show retained/increased binding, regardless of overall pass rate.",
                    "",
                    "## Cases awaiting a run",
                    "",
                    "| Gene | Mutation | Drug | Known direction |",
                    "|---|---|---|---|",
                ]
                + [
                    f"| {o.case.gene} | {o.case.mutation} | {o.case.drug} | "
                    f"{o.case.known_direction} |"
                    for o in report.outcomes
                ]
            )
            + "\n"
        )

    for o in report.outcomes:
        delta = "—" if o.delta_score is None else f"{o.delta_score:+.3f}"
        # Plain-text markers, not symbols: this table is read in terminals, in
        # diffs, and pasted into plaintext reports, and a glyph that renders as
        # a box in any of those is worse than a word.
        if not o.ran:
            mark = "not run"
        elif o.out_of_scope:
            mark = "OUT OF SCOPE"
        elif o.correct:
            mark = "PASS"
        elif o.confidently_wrong:
            mark = "FAIL"
        else:
            mark = "UNCERTAIN"
        lines.append(
            f"| {o.case.gene} | {o.case.mutation} | {o.case.drug} | {o.case.known_direction} "
            f"| {o.predicted_label or '—'} | {o.method or '—'} | {delta} | {mark} |"
        )

    lines += [
        "",
        "Legend: PASS = correct direction · FAIL = confidently wrong · "
        "UNCERTAIN = no confident call · OUT OF SCOPE = method reports the case "
        "outside its domain · not run = no result for this case",
        "",
    ]

    if report.out_of_scope_count:
        in_scope_n = len(report.in_scope)
        lines += [
            f"> **{report.out_of_scope_count} of {len(report.outcomes)} cases are outside what "
            "docking can assess.** The mutation sits beyond the contact range within which a "
            "docking score can detect a binding change, so the pipeline declined to produce a "
            "number rather than emitting noise. These are correct statements of scope, not "
            "wrong answers — but they still count against the pass rate below, because from a "
            "clinician's perspective the question went unanswered.",
            "",
            f"> Restricted to the {in_scope_n} case(s) the method claims it can answer: "
            f"**{report.in_scope_correct}/{in_scope_n} correct**. Report this alongside the "
            "overall rate, never instead of it — the cases it cannot reach are a real "
            "limitation, not a sampling artifact.",
            "",
        ]

    if not report.is_complete_run:
        lines += [
            f"> **Partial run: {report.ran_count} of {len(report.outcomes)} cases executed.** "
            "The pass rate below counts unrun cases as failures, so it is a *lower bound*, "
            "not a measured accuracy figure. Complete the run before citing it.",
            "",
        ]

    lines += [
        "## Pre-committed criteria",
        "",
        f"- **Pass rate:** {report.correct_count}/{len(report.outcomes)} "
        f"({report.pass_rate:.0%}) — threshold {PASS_THRESHOLD:.0%} — "
        f"{'MET' if report.meets_pass_threshold else 'NOT MET'}",
    ]

    unrun_controls = [o for o in report.failed_hard_controls if not o.ran]
    if unrun_controls:
        names = ", ".join(f"{o.case.gene} {o.case.mutation}/{o.case.drug}" for o in unrun_controls)
        lines.append(f"- **Hard-required positive controls:** NOT YET RUN ({names})")
    elif report.failed_hard_controls:
        names = ", ".join(
            f"{o.case.gene} {o.case.mutation}/{o.case.drug}" for o in report.failed_hard_controls
        )
        lines.append(f"- **Hard-required positive controls:** FAILED ({names})")
    else:
        lines.append("- **Hard-required positive controls:** both passed")

    lines += [
        "",
        f"**Demo-ready: {'YES' if report.is_demo_ready else 'NO'}**",
        "",
    ]

    if not report.is_demo_ready and report.is_complete_run:
        lines += [
            "Per `validation-plan.md`, falling below threshold means falling back to the",
            'narrower claim — "mutation is in/near the known binding pocket" plus the',
            "AlphaMissense flag only — and dropping the binding-affinity delta/label from",
            "the UI. That is a documented, legitimate outcome, not a result to hide or to",
            "fix by moving the threshold.",
            "",
        ]

    rows = getattr(report, "_proximity_rows", None) or []
    if rows:
        lines += [
            "## Binding-site proximity (measured, not a scored criterion)",
            "",
            "Distance from the mutated residue to the co-crystallized drug, measured",
            "directly from experimental coordinates. Reported because it is what the",
            "pipeline can state with confidence — and because it explains the deltas",
            "above. **This is an observation, not a validated accuracy figure:**",
            "`validation-plan.md` pre-committed directionality as the criterion, and",
            "scoring a proximity metric defined after seeing these numbers would be",
            "fitting the test to the data.",
            "",
            "| Case | Drug | Distance | Band |",
            "|---|---|---|---|",
        ]
        for label, drug, distance, band in rows:
            shown = "—" if distance is None else f"{distance:.1f} A"
            lines.append(f"| {label} | {drug} | {shown} | `{band}` |")
        lines.append("")

    split = report.method_split
    total = sum(split.values())
    lines += ["## Method coverage", ""]
    if total:
        for method, count in sorted(split.items()):
            lines.append(f"- {method}: {count}/{total} ({count / total:.0%})")
        lines += [
            "",
            "mCSM-lig has a published correlation figure for this task (rho up to 0.67);",
            "AutoDock Vina has none. These are not equivalent-confidence signals and are",
            "not presented as such.",
        ]
    else:
        lines.append("- No candidates were scored.")

    return "\n".join(lines) + "\n"
