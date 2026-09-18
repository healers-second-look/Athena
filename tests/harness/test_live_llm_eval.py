"""Live-model synthesis eval -- skipped unless a self-hosted endpoint is configured.

Deselected by default (`addopts = -m 'not integration'`). Run explicitly with:

    pytest -m integration tests/harness/test_live_llm_eval.py

This hits `get_llm_client()` for real. It does not mock the client, and it
does not hardcode a model name -- the serving name lives in ATHENA_LLM_MODEL.
"""

from __future__ import annotations

import os

import pytest

from secondlook.harness.adapters.synthesis import (
    SYNTHESIS_PROMPT_TEMPLATE_ID,
    SYNTHESIS_SUBSYSTEM,
    SYNTHESIS_THRESHOLD,
    grounded_completion_fn,
    score_synthesis,
)
from secondlook.harness.llm_eval import derive_verdict, run_eval_set
from secondlook.synthesis.llm_client import (
    DEFAULT_PROVIDER,
    LLMClientError,
    get_llm_client,
    llm_enabled,
)

from .eval_sets.synthesis_breast_cancer import SYNTHESIS_BREAST_CANCER_EVAL_CASES

pytestmark = pytest.mark.integration

_SKIP_HINT = (
    "no self-hosted LLM endpoint configured; set ATHENA_LLM_ENABLED=true, "
    "ATHENA_LLM_PROVIDER=openai_compatible, ATHENA_LLM_BASE_URL, and "
    "ATHENA_LLM_MODEL, then re-run with pytest -m integration"
)


def _skip_reason_if_unconfigured() -> str | None:
    if not llm_enabled():
        return (
            "ATHENA_LLM_ENABLED is off; set ATHENA_LLM_ENABLED=true, "
            "ATHENA_LLM_PROVIDER=openai_compatible, ATHENA_LLM_BASE_URL, and "
            "ATHENA_LLM_MODEL to run live LLM eval"
        )
    base_url = (os.environ.get("ATHENA_LLM_BASE_URL") or "").strip()
    model = (os.environ.get("ATHENA_LLM_MODEL") or "").strip()
    if not base_url or not model:
        return _SKIP_HINT
    provider = os.environ.get("ATHENA_LLM_PROVIDER") or DEFAULT_PROVIDER
    if provider != "openai_compatible":
        return (
            "live harness eval targets a self-hosted OpenAI-compatible endpoint; "
            "set ATHENA_LLM_PROVIDER=openai_compatible, ATHENA_LLM_BASE_URL, and "
            "ATHENA_LLM_MODEL"
        )
    return None


@pytest.fixture
def live_llm_client():
    reason = _skip_reason_if_unconfigured()
    if reason is not None:
        pytest.skip(reason)
    client = get_llm_client()
    if client is None:
        pytest.skip(_SKIP_HINT)
    try:
        client.complete(
            "Reply with the single word ok.",
            system="You are a connectivity check. Do not give clinical advice.",
        )
    except LLMClientError as exc:
        pytest.fail(
            f"configured LLM endpoint is unreachable or returned an unusable " f"payload: {exc}"
        )
    return client


def test_breast_cancer_eval_set_against_live_client(live_llm_client):
    inner = grounded_completion_fn(llm_client=live_llm_client)

    def complete(case_input: dict) -> dict:
        actual = inner(case_input)
        if not actual.get("llm_used"):
            raise LLMClientError(
                "generate_synthesis degraded to the template path; "
                "the configured endpoint is unreachable or returned an "
                "unusable payload"
            )
        return actual

    try:
        result = run_eval_set(
            SYNTHESIS_BREAST_CANCER_EVAL_CASES,
            subsystem=SYNTHESIS_SUBSYSTEM + " (breast_cancer eval set)",
            prompt_template_id=SYNTHESIS_PROMPT_TEMPLATE_ID,
            completion_fn=complete,
            score_fn=score_synthesis,
            threshold=SYNTHESIS_THRESHOLD,
        )
    except LLMClientError as exc:
        pytest.fail(
            f"configured LLM endpoint is unreachable or returned an unusable " f"payload: {exc}"
        )

    assert result.threshold == SYNTHESIS_THRESHOLD
    assert result.verdict == derive_verdict(
        result.pass_rate, result.threshold, result.safety_violations
    )
    assert result.verdict == "PASS", (
        f"live breast-cancer eval {result.verdict} at "
        f"{result.pass_rate:.0%} (threshold {result.threshold:.0%}); "
        f"safety_violations={result.safety_violations!r}"
    )
