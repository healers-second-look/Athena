#!/usr/bin/env python
"""Choose the Step 6 cutoff from the cached gold-standard run.

`tier2-structural-prediction.md` §6 is explicit that no established clinical
threshold exists and that the cutoff must be set **empirically during
validation**. This script is that step: it re-labels the cached deltas under a
range of candidate cutoffs and reports how each scores.

## What may and may not be tuned

Tuning the cutoff here is the documented process. Tuning the **pass criteria** is
not: `validation-plan.md` pre-commits the 70% directional-accuracy bar and the
two hard-required positive controls, and states plainly that they are set before
running and not adjusted after seeing results. This script therefore reports the
pre-committed criteria as fixed and only varies the cutoff.

A cutoff chosen this way is fit on the same nine cases it is scored against, so
the resulting pass rate is an **optimistic, in-sample estimate** — not an
out-of-sample accuracy figure. Report it as such.

Costs nothing: re-labels cached deltas, makes no network calls and runs no docking.

Usage::

    python validation/sweep_thresholds.py
    python validation/sweep_thresholds.py --min 0.05 --max 2.0 --step 0.05
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from secondlook.cache import DEFAULT_CACHE_DIR, cache_key, load_payload  # noqa: E402
from secondlook.labeling import (  # noqa: E402
    DOCKING_CALIBRATION,
    MCSM_LIG_CALIBRATION,
    MethodCalibration,
)
from secondlook.validation import (  # noqa: E402
    GOLD_STANDARD_CASES,
    PASS_THRESHOLD,
    build_report,
    sweep_thresholds,
)


def calibrations_at(docking_cut: float, mcsm_cut: float) -> dict:
    """Symmetric cutoffs on the canonical scale for both methods."""
    return {
        "docking": MethodCalibration(
            method="docking",
            unit=DOCKING_CALIBRATION.unit,
            orientation=DOCKING_CALIBRATION.orientation,
            reduced_at_or_below=-abs(docking_cut),
            increased_at_or_above=abs(docking_cut),
            confidence=DOCKING_CALIBRATION.confidence,
            accuracy_note=DOCKING_CALIBRATION.accuracy_note,
        ),
        "mCSM-lig": MethodCalibration(
            method="mCSM-lig",
            unit=MCSM_LIG_CALIBRATION.unit,
            orientation=MCSM_LIG_CALIBRATION.orientation,
            reduced_at_or_below=-abs(mcsm_cut),
            increased_at_or_above=abs(mcsm_cut),
            confidence=MCSM_LIG_CALIBRATION.confidence,
            accuracy_note=MCSM_LIG_CALIBRATION.accuracy_note,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min", type=float, default=0.05)
    parser.add_argument("--max", type=float, default=2.0)
    parser.add_argument("--step", type=float, default=0.05)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    args = parser.parse_args()

    payloads = {}
    for case in GOLD_STANDARD_CASES:
        payload = load_payload(case.gene, case.mutation, cache_dir=Path(args.cache_dir))
        if payload is not None:
            payloads[cache_key(case.gene, case.mutation)] = payload
    if not payloads:
        print("No cached runs. Run validation/run_gold_standard.py first.", file=sys.stderr)
        return 1

    baseline = build_report(payloads)
    print(f"Cached mutations: {len(payloads)}   cases scored: {len(baseline.scored)}/9")
    print("\nObserved deltas:")
    for outcome in baseline.outcomes:
        if outcome.delta_score is None:
            print(f"  {outcome.case.gene:5} {outcome.case.mutation:7} {outcome.case.drug:14} —")
        else:
            print(
                f"  {outcome.case.gene:5} {outcome.case.mutation:7} {outcome.case.drug:14} "
                f"{outcome.delta_score:+.4f} ({outcome.method}, "
                f"want {outcome.case.known_direction})"
            )

    cuts = []
    x = args.min
    while x <= args.max + 1e-9:
        cuts.append(round(x, 4))
        x += args.step

    candidates = [calibrations_at(c, c) for c in cuts]
    results = sweep_thresholds(payloads, candidates)

    print(f"\n{'cutoff':>8} {'correct':>8} {'rate':>7} {'wrong':>6} {'controls':>9}  verdict")
    print("-" * 60)
    best = None
    for cut, (_cal, report) in zip(cuts, results, strict=True):
        wrong = sum(1 for o in report.outcomes if o.confidently_wrong)
        controls = "pass" if not report.failed_hard_controls else "FAIL"
        verdict = "demo-ready" if report.is_demo_ready else ""
        print(
            f"{cut:>8.2f} {report.correct_count:>8} {report.pass_rate:>6.0%} "
            f"{wrong:>6} {controls:>9}  {verdict}"
        )
        key = (report.correct_count, -wrong)
        if best is None or key > best[0]:
            best = (key, cut, report)

    print()
    if best is not None:
        _key, cut, report = best
        print(f"Best cutoff by directional accuracy: {cut:.2f}")
        print(
            f"  correct {report.correct_count}/9 ({report.pass_rate:.0%}), "
            f"pre-committed bar {PASS_THRESHOLD:.0%}"
        )
        print(f"  hard controls: {'pass' if not report.failed_hard_controls else 'FAIL'}")
        print()
        print("This is an IN-SAMPLE figure: the cutoff was fitted on these same nine")
        print("cases. It is not an out-of-sample accuracy estimate and must not be")
        print("presented as one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
