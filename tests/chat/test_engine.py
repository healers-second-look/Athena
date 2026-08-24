"""Tests for session store, engine, and KG integration (Phases 1, 4)."""

from secondlook.chat.engine import build_prompt, run_turn
from secondlook.chat.knowledge import describe_context
from secondlook.chat.session import (
    create_session,
    delete_session,
    get_session,
    list_sessions,
    update_session,
)


def test_session_store_crud():
    sess = create_session(model_id="mock-terse", attachment_ids=["variant-normalizer"])
    assert sess.id is not None
    assert sess.model_id == "mock-terse"
    assert sess.attachment_ids == ["variant-normalizer"]

    fetched = get_session(sess.id)
    assert fetched is not None
    assert fetched.id == sess.id

    msg = sess.add_message("user", "Hello world")
    assert msg["content"] == "Hello world"
    assert len(sess.history) == 1

    updated = update_session(sess.id, context_id="gene:EGFR")
    assert updated.context_id == "gene:EGFR"

    all_sessions = list_sessions()
    assert any(s.id == sess.id for s in all_sessions)

    deleted = delete_session(sess.id)
    assert deleted is True
    assert get_session(sess.id) is None


def test_build_prompt():
    prompt = build_prompt("My question", ["Context 1", "Context 2"])
    assert "My question" in prompt
    assert "### Retrieved context" in prompt
    assert "- Context 1" in prompt
    assert "- Context 2" in prompt


def test_build_prompt_separates_context_from_sources():
    """Issue #107: context and sources render under distinct markers, and
    a prompt with only context (no sources) must not carry the source
    marker at all -- that absence is what tells a model zero sources were
    retrieved.
    """
    prompt = build_prompt(
        "My question", context_lines=["Some context"], source_lines=["[1] A real source"]
    )
    assert "### Retrieved sources" in prompt
    assert "### Retrieved context" in prompt
    assert "- [1] A real source" in prompt
    assert "- Some context" in prompt

    context_only = build_prompt("My question", context_lines=["Some context"], source_lines=[])
    assert "### Retrieved sources" not in context_only
    assert "### Retrieved context" in context_only


def test_run_turn_end_to_end():
    result = run_turn(
        "What is EGFR T790M?",
        model_id="mock-outline",
        attachment_ids=["variant-normalizer", "citation-guard"],
    )
    assert result.model_id == "mock-outline"
    assert "EGFR" in result.entities.get("genes", [])
    assert "T790M" in result.entities.get("variants", [])
    assert len(result.notes) > 0
    assert "## On:" in result.content


def test_describe_context_graceful_handling():
    # If FalkorDB is live, it returns facts; if unavailable, it degrades to UNAVAILABLE notice
    lines = describe_context("gene:EGFR")
    assert isinstance(lines, list)
    if lines:
        assert any("EGFR" in line or "UNAVAILABLE" in line for line in lines)
