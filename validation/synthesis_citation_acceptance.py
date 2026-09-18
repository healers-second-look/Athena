#!/usr/bin/env python
"""Citation-gate accepted-sentence rate against a configured LLM.

Issue #10's open question -- which open-weight models produce adequate
citation-constrained synthesis -- is unvalidated. This script does not
answer it. It makes the gate runnable against whatever `get_llm_client()`
constructs (typically `OpenAICompatibleClient` pointed at a candidate
via ATHENA_LLM_BASE_URL / ATHENA_LLM_MODEL).

The scored metric lives in the LLM eval harness
(`secondlook.harness.adapters.citation_acceptance`) and is reported by
`validation/llm_eval_run.py --subsystem citation_acceptance` into
`validation/llm_eval_results.md` with a pre-committed threshold. This
script keeps the per-fixture printout; the harness is the auditable
record.

Usage::

    ATHENA_LLM_PROVIDER=openai_compatible \\
    ATHENA_LLM_BASE_URL=http://localhost:8000/v1 \\
    ATHENA_LLM_MODEL=<candidate> \\
        python validation/synthesis_citation_acceptance.py

    python validation/llm_eval_run.py --subsystem citation_acceptance
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from secondlook.harness.adapters.citation_acceptance import (  # noqa: E402
    eval_result_from_measurements,
    measure_citation_acceptance,
)
from secondlook.synthesis.llm_client import LLMClientError, get_llm_client  # noqa: E402


def main() -> int:
    client = get_llm_client()
    if client is None:
        print(
            "ATHENA_LLM_ENABLED is false (or unset to a falsey value). "
            "This script needs a live client to measure a model; the "
            "disabled path is already covered by tests/synthesis/test_generate.py."
        )
        return 2

    print(
        "Rates below are for this run only; write them down with the date "
        "and ATHENA_LLM_MODEL (via validation/llm_eval_run.py --subsystem "
        "citation_acceptance) before treating the open question as answered."
    )
    try:
        rows = measure_citation_acceptance(llm_client=client)
    except LLMClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for row in rows:
        rate = row["accepted_rate"]
        rate_s = "n/a" if rate is None else f"{rate:.3f}"
        total = row["accepted_n"] + row["dropped"]
        print(
            f"{row['name']}: accepted_rate={rate_s} "
            f"dropped={row['dropped']} total={total} "
            f"llm_used={row['llm_used']} cited_ids={row['cited_ids']}"
        )
    summary = eval_result_from_measurements(rows)
    print(
        f"{summary.subsystem}: {summary.verdict} "
        f"(accepted_rate={summary.pass_rate:.3f}, "
        f"threshold={summary.threshold:.2f})"
    )
    return 0 if summary.verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
