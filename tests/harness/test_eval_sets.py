"""The synthesis eval sets are hand-labeled and checked in, not generated."""

from __future__ import annotations

from secondlook.harness.llm_eval import EvalCase

from .eval_sets.chat_citation import CHAT_CITATION_EVAL_CASES
from .eval_sets.synthesis import SYNTHESIS_EVAL_CASES
from .eval_sets.synthesis_breast_cancer import SYNTHESIS_BREAST_CANCER_EVAL_CASES


def test_synthesis_eval_set_has_at_least_five_hand_labeled_cases():
    assert len(SYNTHESIS_EVAL_CASES) >= 5
    for case in SYNTHESIS_EVAL_CASES:
        assert isinstance(case, EvalCase)
        assert case.input.get("question_text")
        assert case.expected, "every case must carry a human-written expected output"


def test_eval_set_covers_conflict_and_adversarial_recommendation_ask():
    texts = [case.input["question_text"] for case in SYNTHESIS_EVAL_CASES]
    assert any("should this patient take" in text.lower() for text in texts)
    claims = [
        signal["claim"]
        for case in SYNTHESIS_EVAL_CASES
        for signal in case.input.get("signals") or []
    ]
    assert any("sensitive" in c.lower() for c in claims)
    assert any("resistance" in c.lower() for c in claims)


def test_chat_citation_eval_set_has_at_least_five_hand_labeled_cases():
    assert len(CHAT_CITATION_EVAL_CASES) >= 5
    for case in CHAT_CITATION_EVAL_CASES:
        assert isinstance(case, EvalCase)
        assert case.input.get("question_text")


def test_chat_citation_eval_set_reproduces_the_107_shape():
    """At least one case must pair a real plugin attachment with a
    fictional gene/variant pair pinned to zero real sources -- the exact
    shape issue #107's bug was found in, per issue #124's own wording."""
    zero_source_cases = [
        case
        for case in CHAT_CITATION_EVAL_CASES
        if case.expected.get("sources_count") == 0 and case.input.get("attachment_ids")
    ]
    assert zero_source_cases, "need at least one zero-source, attachment-bearing case"


def test_chat_citation_eval_set_covers_every_real_plugin():
    attached = {
        attachment_id
        for case in CHAT_CITATION_EVAL_CASES
        for attachment_id in case.input.get("attachment_ids") or []
    }
    assert {"variant-normalizer", "citation-guard", "evidence-grader"} <= attached


def test_chat_citation_eval_set_includes_an_environment_independent_case():
    """At least one case must not pin `sources_count`, so the same
    citation-integrity invariant is also exercised when real evidence may
    actually be retrieved, not only in the guaranteed-zero cases."""
    assert any("sources_count" not in case.expected for case in CHAT_CITATION_EVAL_CASES)


# --- issue #122: breast-cancer-scoped eval set (issue #121's MVP cancer type) --


def test_breast_cancer_eval_set_has_at_least_five_hand_labeled_cases():
    assert len(SYNTHESIS_BREAST_CANCER_EVAL_CASES) >= 5
    for case in SYNTHESIS_BREAST_CANCER_EVAL_CASES:
        assert isinstance(case, EvalCase)
        assert case.input.get("question_text")
        assert case.expected, "every case must carry a human-written expected output"


def test_breast_cancer_eval_set_is_scoped_to_the_mvp_cancer_type():
    for case in SYNTHESIS_BREAST_CANCER_EVAL_CASES:
        assert case.input.get("cancer_type") == "HR+/HER2- breast cancer"


def test_breast_cancer_eval_set_covers_conflict_and_adversarial_recommendation_ask():
    texts = [case.input["question_text"] for case in SYNTHESIS_BREAST_CANCER_EVAL_CASES]
    assert any("should this patient take" in text.lower() for text in texts)
    claims = [
        signal["claim"]
        for case in SYNTHESIS_BREAST_CANCER_EVAL_CASES
        for signal in case.input.get("signals") or []
    ]
    assert any("resistance" in c.lower() for c in claims)
    assert any("sensitivity" in c.lower() for c in claims)
