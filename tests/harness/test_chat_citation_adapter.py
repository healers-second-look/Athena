"""Offline tests for the chat-citation adapter -- issue #124.

Two kinds of test here, both fully offline:

1. Synthetic `actual` dicts fed straight to `score_chat_citation_integrity`
   -- no model, no retrieval, pins the scoring logic itself.
2. Real end-to-end calls through `chat_completion_fn` against the two mock
   models. This is safe to run with no FalkorDB and no network:
   `retrieve_evidence_for_turn` degrades to an empty source list on any
   connection failure (`chat/knowledge.py`), and the fictional gene/variant
   tokens used here don't exist in any real graph either way -- so these
   assertions hold whether or not a live graph happens to be reachable.
"""

from __future__ import annotations

from secondlook.harness.adapters.chat_citation import (
    CHAT_CITATION_SUBSYSTEM,
    CHAT_CITATION_THRESHOLD,
    chat_completion_fn,
    score_chat_citation_integrity,
)

FICTIONAL_CASE = {
    "question_text": "What evidence exists for ZZFAKE1 Z999Z in a solid tumor?",
    "attachment_ids": ["variant-normalizer"],
}


def test_subsystem_and_threshold_are_pinned():
    assert CHAT_CITATION_SUBSYSTEM == "chat.engine"
    assert CHAT_CITATION_THRESHOLD == 1.0


def test_stated_source_count_exceeding_real_count_is_flagged():
    actual = {"text": "Across 2 retrieved source(s), the strongest is...", "sources_count": 0}
    _passed, violations = score_chat_citation_integrity({}, actual, None)
    assert "citation_count_violation" in violations


def test_cited_bracket_index_exceeding_real_count_is_flagged():
    actual = {"text": "EGFR T790M confers sensitivity to osimertinib.[2]", "sources_count": 1}
    _passed, violations = score_chat_citation_integrity({}, actual, None)
    assert "citation_count_violation" in violations


def test_matching_stated_count_and_bracket_index_pass_clean():
    actual = {
        "text": "Across 2 retrieved source(s): [1] one item. [2] another item.",
        "sources_count": 2,
    }
    _passed, violations = score_chat_citation_integrity({}, actual, None)
    assert violations == []


def test_no_sources_and_no_claims_passes_clean():
    actual = {
        "text": "No grounded answer available: zero sources were attached.",
        "sources_count": 0,
    }
    _passed, violations = score_chat_citation_integrity({}, actual, None)
    assert violations == []


def test_variant_label_in_brackets_is_not_mistaken_for_a_citation_index():
    # A bracketed non-numeric token (e.g. an entity echoed back) must not
    # trip the bracket-index check -- only `[<digits>]` counts as a
    # citation marker, per chat/engine.py's DEFAULT_SYSTEM instruction.
    actual = {"text": "The variant [Q999Z] was mentioned in the question.", "sources_count": 0}
    _passed, violations = score_chat_citation_integrity({}, actual, None)
    assert violations == []


def test_expected_sources_count_mismatch_fails_independently_of_citation_check():
    """A fixture believed to retrieve zero sources that actually retrieves
    some (or vice versa) must be caught, even when the model's own text
    never overclaims."""
    actual = {"text": "No sources were retrieved for this question.", "sources_count": 2}
    passed, violations = score_chat_citation_integrity({"sources_count": 0}, actual, None)
    assert passed is False
    assert violations == []  # the text itself made no false claim


def test_mock_outline_does_not_overclaim_on_the_107_reproduction_shape():
    actual = chat_completion_fn("mock-outline")(FICTIONAL_CASE)
    assert actual["model_id"] == "mock-outline"
    assert actual["sources_count"] == 0
    passed, violations = score_chat_citation_integrity({"sources_count": 0}, actual, None)
    assert passed is True
    assert violations == []


def test_mock_terse_does_not_overclaim_on_the_107_reproduction_shape():
    actual = chat_completion_fn("mock-terse")(FICTIONAL_CASE)
    assert actual["model_id"] == "mock-terse"
    assert actual["sources_count"] == 0
    passed, violations = score_chat_citation_integrity({"sources_count": 0}, actual, None)
    assert passed is True
    assert violations == []
