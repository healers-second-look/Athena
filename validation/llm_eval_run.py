#!/usr/bin/env python
"""Run held-out LLM eval sets and write an auditable results table.

Mirrors `validation/run_gold_standard.py`: pre-committed thresholds live
in the adapters; this script only runs and reports.

Usage::

    python validation/llm_eval_run.py
    python validation/llm_eval_run.py --subsystem synthesis
    python validation/llm_eval_run.py --subsystem synthesis --grounded-comparison
    python validation/llm_eval_run.py --subsystem criteria_extraction
    python validation/llm_eval_run.py --subsystem intake
    python validation/llm_eval_run.py --subsystem citation_acceptance

    # issue #122: run against the MVP cancer type's vocabulary (issue #121)
    # instead of (or alongside) the general NSCLC/melanoma/mastocytosis set --
    # useful when validating a new backend (e.g. a self-hosted model) against
    # the actual vocabulary the MVP demo will use, per that issue's own
    # dependency note.
    python validation/llm_eval_run.py --subsystem synthesis --cases breast_cancer
    python validation/llm_eval_run.py --subsystem synthesis --cases both

Output: `validation/llm_eval_results.md`

Exit status is 0 only when every `EvalResult.verdict` is PASS (and, with
`--grounded-comparison`, when the grounded result is PASS).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from harness.eval_sets.synthesis import SYNTHESIS_EVAL_CASES  # noqa: E402
from harness.eval_sets.synthesis_breast_cancer import (  # noqa: E402
    SYNTHESIS_BREAST_CANCER_EVAL_CASES,
)

from secondlook.harness.adapters.citation_acceptance import (  # noqa: E402
    evaluate_citation_acceptance,
)
from secondlook.harness.adapters.criteria_extraction import (  # noqa: E402
    evaluate_existing_corpus,
)
from secondlook.harness.adapters.intake import (  # noqa: E402
    evaluate_eval_set as evaluate_intake_eval_set,
)
from secondlook.harness.adapters.synthesis import (  # noqa: E402
    SYNTHESIS_PROMPT_TEMPLATE_ID,
    SYNTHESIS_SUBSYSTEM,
    SYNTHESIS_THRESHOLD,
    grounded_completion_fn,
    score_synthesis,
    ungrounded_completion_fn,
)
from secondlook.harness.llm_eval import (  # noqa: E402
    EvalResult,
    GroundingComparison,
    render_markdown,
    run_eval_set,
    run_grounded_vs_ungrounded,
)
from secondlook.synthesis.llm_client import get_llm_client  # noqa: E402

RESULTS_PATH = REPO_ROOT / "validation" / "llm_eval_results.md"


def run_criteria_extraction() -> EvalResult:
    return evaluate_existing_corpus()


#: Maps the CLI's --cases value to (label, cases). label is folded into
#: the reported subsystem name so validation/llm_eval_results.md stays
#: self-documenting about which vocabulary a given run actually used --
#: an auditable report that doesn't say what it evaluated is not
#: auditable.
_CASE_SETS: dict[str, tuple[str, list]] = {
    "general": ("", SYNTHESIS_EVAL_CASES),
    "breast_cancer": (" (breast_cancer eval set)", SYNTHESIS_BREAST_CANCER_EVAL_CASES),
}


def run_synthesis_eval(cases_key: str = "general") -> EvalResult:
    client = get_llm_client()
    if client is None:
        raise RuntimeError(
            "synthesis eval needs a configured LLM client "
            "(ATHENA_LLM_ENABLED is off, or provider config is missing)"
        )
    label, cases = _CASE_SETS[cases_key]
    return run_eval_set(
        cases,
        subsystem=SYNTHESIS_SUBSYSTEM + label,
        prompt_template_id=SYNTHESIS_PROMPT_TEMPLATE_ID,
        completion_fn=grounded_completion_fn(llm_client=client),
        score_fn=score_synthesis,
        threshold=SYNTHESIS_THRESHOLD,
    )


def run_synthesis_comparison(cases_key: str = "general") -> GroundingComparison:
    client = get_llm_client()
    if client is None:
        raise RuntimeError(
            "synthesis grounding comparison needs a configured LLM client "
            "(ATHENA_LLM_ENABLED is off, or provider config is missing)"
        )
    label, cases = _CASE_SETS[cases_key]
    return run_grounded_vs_ungrounded(
        cases,
        subsystem=SYNTHESIS_SUBSYSTEM + label,
        prompt_template_id=SYNTHESIS_PROMPT_TEMPLATE_ID,
        grounded_completion_fn=grounded_completion_fn(llm_client=client),
        ungrounded_completion_fn=ungrounded_completion_fn(llm_client=client),
        score_fn=score_synthesis,
        threshold=SYNTHESIS_THRESHOLD,
    )


def run_intake_eval() -> EvalResult:
    client = get_llm_client()
    if client is None:
        raise RuntimeError(
            "intake eval needs a configured LLM client "
            "(ATHENA_LLM_ENABLED is off, or provider config is missing)"
        )
    return evaluate_intake_eval_set(llm_client=client)


def run_citation_acceptance_eval() -> EvalResult:
    client = get_llm_client()
    if client is None:
        raise RuntimeError(
            "citation-acceptance eval needs a configured LLM client "
            "(ATHENA_LLM_ENABLED is off, or provider config is missing)"
        )
    return evaluate_citation_acceptance(llm_client=client)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--subsystem",
        choices=[
            "synthesis",
            "criteria_extraction",
            "intake",
            "citation_acceptance",
            "all",
        ],
        default="all",
    )
    parser.add_argument(
        "--grounded-comparison",
        action="store_true",
        help="run synthesis with and without retrieval (synthesis only)",
    )
    parser.add_argument(
        "--cases",
        choices=["general", "breast_cancer", "both"],
        default="general",
        help=(
            "which eval-case set(s) to run for --subsystem synthesis "
            "(synthesis only; ignored for other subsystems). 'general' is "
            "the existing NSCLC/melanoma/mastocytosis set; 'breast_cancer' "
            "is issue #121's MVP cancer type; 'both' runs each separately "
            "and reports both."
        ),
    )
    args = parser.parse_args(argv)

    if args.grounded_comparison and args.subsystem in {
        "criteria_extraction",
        "intake",
        "citation_acceptance",
    }:
        print(
            f"error: --grounded-comparison is not valid with "
            f"--subsystem {args.subsystem}. {args.subsystem} has no "
            "ungrounded variant by design, not by omission.",
            file=sys.stderr,
        )
        return 2

    cases_keys = ["general", "breast_cancer"] if args.cases == "both" else [args.cases]

    results: list[EvalResult] = []
    comparisons: list[GroundingComparison] = []

    try:
        if args.subsystem in {"synthesis", "all"}:
            for cases_key in cases_keys:
                if args.grounded_comparison:
                    comparison = run_synthesis_comparison(cases_key)
                    comparisons.append(comparison)
                    results.append(comparison.grounded)
                else:
                    results.append(run_synthesis_eval(cases_key))
        if args.subsystem in {"criteria_extraction", "all"}:
            results.append(run_criteria_extraction())
        if args.subsystem in {"intake", "all"}:
            results.append(run_intake_eval())
        if args.subsystem in {"citation_acceptance", "all"}:
            results.append(run_citation_acceptance_eval())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(render_markdown(results, comparisons=tuple(comparisons)))
    print(f"Wrote {RESULTS_PATH}")
    for result in results:
        print(f"{result.subsystem}: {result.verdict} ({result.pass_rate:.0%})")
    for comparison in comparisons:
        print(f"grounding delta ({comparison.subsystem}): " f"{comparison.pass_rate_delta:+.0%}")

    blocked = any(result.verdict != "PASS" for result in results)
    if any(comparison.grounded.verdict != "PASS" for comparison in comparisons):
        blocked = True
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
