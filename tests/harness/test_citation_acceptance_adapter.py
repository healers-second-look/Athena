"""Offline tests for the citation-acceptance adapter -- fake LLM, no network.

The metric is the citation-gate accepted-sentence rate, reported through
the generic EvalResult / derive_verdict shape. The gate itself is not
reimplemented here.
"""

from __future__ import annotations

import pytest

from secondlook.harness.adapters.citation_acceptance import (
    CITATION_ACCEPTANCE_PROMPT_TEMPLATE_ID,
    CITATION_ACCEPTANCE_SUBSYSTEM,
    CITATION_ACCEPTANCE_THRESHOLD,
    evaluate_citation_acceptance,
)
from secondlook.harness.llm_eval import derive_verdict
from secondlook.synthesis.generate import SYSTEM_PROMPT_VERSION
from secondlook.synthesis.llm_client import LLMClientError


class FakeLLM:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[tuple[str, str | None]] = []

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        return self.text


class RaisingLLM:
    def complete(self, prompt: str, *, system: str | None = None) -> str:
        raise LLMClientError("endpoint unreachable")


def test_threshold_is_precommitted_and_not_one():
    """Same floor as SYNTHESIS_THRESHOLD: chosen before a live run.

    1.0 would claim the two-fixture corpus can certify perfect citation
    discipline; it cannot. Falling below this constant is a documented
    outcome, not a reason to move it.
    """
    assert CITATION_ACCEPTANCE_THRESHOLD == 0.70


def test_prompt_template_id_is_the_real_synthesis_prompt():
    assert CITATION_ACCEPTANCE_PROMPT_TEMPLATE_ID == SYSTEM_PROMPT_VERSION


def test_full_citation_discipline_is_a_pass():
    fake = FakeLLM("EGFR T790M confers sensitivity to osimertinib.[ref:civic_12]")
    result = evaluate_citation_acceptance(llm_client=fake)
    assert result.subsystem == CITATION_ACCEPTANCE_SUBSYSTEM
    assert result.threshold == CITATION_ACCEPTANCE_THRESHOLD
    assert result.pass_rate == pytest.approx(1.0)
    assert result.safety_violations == []
    assert result.verdict == derive_verdict(
        result.pass_rate, result.threshold, result.safety_violations
    )
    assert result.verdict == "PASS"
    assert fake.calls, "must call the real generate_synthesis LLM path"


def test_fully_uncited_output_is_a_fail_not_a_silent_pass():
    fake = FakeLLM("This is an unsupported editorial claim with no citation.")
    result = evaluate_citation_acceptance(llm_client=fake)
    assert result.pass_rate == pytest.approx(0.0)
    assert result.verdict == derive_verdict(
        result.pass_rate, CITATION_ACCEPTANCE_THRESHOLD, result.safety_violations
    )
    assert result.verdict == "FAIL"


def test_client_error_is_not_swallowed_as_a_template_pass():
    """generate_synthesis degrades to the template path on LLMClientError.

    That path has llm_used=False and a 100% accepted-sentence rate by
    construction. Measuring it as a citation-gate success would be a
    silent pass of an unreachable endpoint.
    """
    with pytest.raises(LLMClientError, match="unreachable|degraded|template"):
        evaluate_citation_acceptance(llm_client=RaisingLLM())


def test_missing_client_raises_a_clear_runtime_error():
    with pytest.raises(RuntimeError, match="ATHENA_LLM"):
        evaluate_citation_acceptance(llm_client=None)
