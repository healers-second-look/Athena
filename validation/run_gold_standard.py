#!/usr/bin/env python
"""Run the nine gold-standard cases and write an auditable results table.

Each case is cached after its first successful run, so re-running is cheap and a
crash partway through does not lose completed work. This matters: most candidates
have no PDB HET code and therefore need a real docking run, and mCSM-lig must stay
serial against a shared academic server.

Usage::

    python validation/run_gold_standard.py                 # run any uncached cases
    python validation/run_gold_standard.py --force         # re-run everything
    python validation/run_gold_standard.py --report-only   # score the cache, no network
    python validation/run_gold_standard.py --case BRAF     # one gene only

Output: `validation/results.md`, plus one JSON payload per case under
`validation/cache/`.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from secondlook.cache import (  # noqa: E402
    DEFAULT_CACHE_DIR,
    cache_key,
    load_payload,
    payload_is_stale,
    save_payload,
    to_payload,
)


def is_worth_rerunning(payload: dict) -> bool:
    """True when a cached entry records a transient failure rather than a result.

    Caching exists to avoid repeating expensive *successful* work. A cached
    failure is not a result: treating it as one silently freezes a rate-limit blip
    into the record, so the next run reports "cached, skipping" and the case never
    recovers. Only retryable failures qualify — a reference-residue mismatch or an
    out-of-scope variant will fail identically forever and is a real answer.
    """
    if payload.get("results"):
        return False
    failures = payload.get("failures") or []
    return any(f.get("retryable") for f in failures)


from secondlook.pipeline import run_tier2  # noqa: E402
from secondlook.validation import (  # noqa: E402
    GOLD_STANDARD_CASES,
    build_report,
    proximity_rows,
    render_markdown,
)

RESULTS_PATH = REPO_ROOT / "validation" / "results.md"


def unique_mutations(cases, gene_filter=None):
    """(gene, mutation) → every drug that mutation's cases need scored.

    One pipeline run per mutation, not per case: EGFR T790M appears twice
    (gefitinib and osimertinib) and a single run answers both, since Step 4
    generates the whole shortlist once.
    """
    seen: dict[tuple[str, str], list[str]] = {}
    for case in cases:
        if gene_filter and case.gene.upper() != gene_filter.upper():
            continue
        drugs = seen.setdefault((case.gene, case.mutation), [])
        if case.drug not in drugs:
            drugs.append(case.drug)
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-run even if cached")
    parser.add_argument(
        "--report-only", action="store_true", help="score existing cache without running"
    )
    parser.add_argument("--case", help="limit to one gene symbol")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument(
        "--pace-seconds",
        type=float,
        default=5.0,
        help=(
            "pause between cases. Every case opens with a UniProt lookup, and "
            "back-to-back runs trip its rate limit — which surfaces as a "
            "retryable timeout failure rather than a result."
        ),
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help="cap the shortlist per case (useful for a faster first pass)",
    )
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    targets = unique_mutations(GOLD_STANDARD_CASES, args.case)

    if not args.report_only:
        for index, ((gene, mutation), drugs) in enumerate(targets.items(), start=1):
            existing = load_payload(gene, mutation, cache_dir=cache_dir)
            if (
                existing
                and not args.force
                and not payload_is_stale(existing)
                and not is_worth_rerunning(existing)
            ):
                print(f"[{index}/{len(targets)}] {gene} {mutation}: cached, skipping")
                continue
            if existing and is_worth_rerunning(existing):
                print(
                    f"[{index}/{len(targets)}] {gene} {mutation}: cached run was a "
                    "retryable failure, re-running"
                )
            if existing and payload_is_stale(existing):
                print(f"[{index}/{len(targets)}] {gene} {mutation}: cache is stale, re-running")

            if index > 1 and args.pace_seconds:
                time.sleep(args.pace_seconds)
            print(
                f"[{index}/{len(targets)}] {gene} {mutation}: running for {', '.join(drugs)}…",
                flush=True,
            )
            try:
                kwargs = {"restrict_to_drugs": tuple(drugs)}
                if args.max_candidates is not None:
                    kwargs["max_candidates"] = args.max_candidates
                output = run_tier2(gene, mutation, **kwargs)
            except Exception:  # noqa: BLE001
                # A crash on one case must not lose the other eight. The traceback
                # is printed rather than swallowed — this is a research harness,
                # and a silent skip here would be the same class of bug the
                # pipeline's own failure contract exists to prevent.
                print(f"    ERROR running {gene} {mutation}:", file=sys.stderr)
                traceback.print_exc()
                continue

            payload = to_payload(output, gene=gene, mutation=mutation)
            # Never let a failed re-run destroy a good cached result. A stale
            # success is still data — it has a pipeline_version stamp saying so —
            # whereas an outage payload carries nothing. Overwriting one with the
            # other silently converts "we measured this once" into "we have
            # nothing", which is the same class of loss as recording a transient
            # failure as a settled fact.
            if not payload["results"] and existing and existing.get("results"):
                print(
                    "    run failed; keeping the previous successful result "
                    f"(pipeline {existing.get('pipeline_version')}) rather than overwriting it"
                )
                continue
            path = save_payload(payload, cache_dir=cache_dir)
            summary = ", ".join(f"{k}={v}" for k, v in output.scored_by_method.items())
            print(
                f"    status={output.status} results={len(output.results)} "
                f"failures={len(output.failures)} [{summary or 'none scored'}] → {path}"
            )

    payloads = {}
    for gene, mutation in unique_mutations(GOLD_STANDARD_CASES):
        payload = load_payload(gene, mutation, cache_dir=cache_dir)
        if payload is not None:
            payloads[cache_key(gene, mutation)] = payload

    report = build_report(payloads)
    # Attached rather than computed inside build_report: proximity is reported as
    # observation only, and keeping it off the report's scoring surface makes that
    # separation structural rather than a matter of discipline.
    object.__setattr__(report, "_proximity_rows", proximity_rows(payloads))
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(render_markdown(report))

    print()
    print(f"Pass rate: {report.correct_count}/{len(report.outcomes)} ({report.pass_rate:.0%})")
    print(f"Demo-ready: {'YES' if report.is_demo_ready else 'NO'}")
    print(f"Wrote {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
