"""Tests for session store, engine, and KG integration (Phases 1, 4)."""

import pytest

from secondlook.chat import engine
from secondlook.chat.engine import build_prompt, run_turn
from secondlook.chat.knowledge import RetrievalResult, describe_context
from secondlook.chat.models import SOURCE_MARKER
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


# ---------------------------------------------------------------------------
# Retrieval ordering and outage handling -- the regression these pin is that
# citation-guard shipped running BEFORE retrieval, so it always saw zero
# sources and told the model "nothing was retrieved" while `build_prompt`
# handed it real ones. Neither mock reads `system`, so no demo revealed it
# and no unit test caught it: the plugin tests pre-populated `Turn.sources`,
# a state the engine never produced. These drive `run_turn` end to end
# instead, which is the only level at which the ordering is observable.
# ---------------------------------------------------------------------------


class _SpyClient:
    """Captures the system prompt the engine actually sends."""

    def __init__(self):
        self.system = None
        self.prompt = None

    def complete(self, prompt, *, system=None):
        self.prompt = prompt
        self.system = system
        return "spy reply"


def _sources(n):
    return [
        {
            "id": f"civic:{i}",
            "citation_index": i,
            "title": f"Source {i}",
            "evidence_level": "A",
            "summary": "summary",
            "citation_url": "https://civicdb.org/evidence/1",
            "pmid": "123456",
        }
        for i in range(1, n + 1)
    ]


@pytest.fixture
def spy(monkeypatch):
    client = _SpyClient()
    monkeypatch.setattr(engine, "build_client", lambda model_id: client)
    return client


def _patch_retrieval(monkeypatch, result):
    monkeypatch.setattr(engine, "retrieve_evidence_for_turn", lambda **kwargs: result)


class TestCitationGuardSeesWhatRetrievalActuallyReturned:
    def test_it_is_told_sources_exist_when_they_do(self, monkeypatch, spy):
        _patch_retrieval(monkeypatch, RetrievalResult(sources=_sources(3)))
        result = engine.run_turn("EGFR T790M?", attachment_ids=["citation-guard"])

        assert "cite a retrieved source" in spy.system
        assert "nothing was retrieved" not in spy.system
        assert result.sources_count == 3

    def test_the_prompt_and_the_system_text_agree(self, monkeypatch, spy):
        """The actual defect: they contradicted each other."""
        _patch_retrieval(monkeypatch, RetrievalResult(sources=_sources(3)))
        engine.run_turn("EGFR T790M?", attachment_ids=["citation-guard"])

        prompt_has_sources = SOURCE_MARKER in spy.prompt
        system_denies_sources = "nothing was retrieved" in spy.system
        assert not (prompt_has_sources and system_denies_sources)

    def test_the_notes_do_not_contradict_each_other(self, monkeypatch, spy):
        _patch_retrieval(monkeypatch, RetrievalResult(sources=_sources(3)))
        notes = " | ".join(engine.run_turn("Q?", attachment_ids=["citation-guard"]).notes)

        assert "3 retrieved source(s) present" in notes
        assert "NO retrieved context" not in notes

    def test_a_genuinely_empty_search_still_says_so(self, monkeypatch, spy):
        _patch_retrieval(monkeypatch, RetrievalResult(sources=[]))
        engine.run_turn("Q?", attachment_ids=["citation-guard"])
        assert "nothing was retrieved" in spy.system


class TestAnOutageIsNotAClinicalNegative:
    """FalkorDB being unreachable must not render as 'no evidence exists'."""

    OUTAGE = RetrievalResult(sources=[], failed=True, error="FalkorDB unreachable")

    def test_the_turn_reports_the_failure(self, monkeypatch, spy):
        _patch_retrieval(monkeypatch, self.OUTAGE)
        result = engine.run_turn("Q?")

        assert result.retrieval_failed is True
        assert "FalkorDB unreachable" in result.retrieval_error
        assert any("retrieval FAILED" in n for n in result.notes)

    def test_the_model_is_told_the_search_never_ran(self, monkeypatch, spy):
        _patch_retrieval(monkeypatch, self.OUTAGE)
        engine.run_turn("Q?", attachment_ids=["citation-guard"])

        assert "retrieval FAILED" in spy.system
        assert "do not state or imply that no evidence exists" in spy.system

    def test_an_outage_and_an_empty_search_differ_everywhere(self, monkeypatch, spy):
        _patch_retrieval(monkeypatch, self.OUTAGE)
        down = engine.run_turn("Q?", attachment_ids=["citation-guard"])
        down_system, down_prompt = spy.system, spy.prompt

        _patch_retrieval(monkeypatch, RetrievalResult(sources=[]))
        empty = engine.run_turn("Q?", attachment_ids=["citation-guard"])

        assert down.retrieval_failed and not empty.retrieval_failed
        assert down_system != spy.system
        assert down_prompt != spy.prompt
        assert down.notes != empty.notes

    def test_both_mock_models_distinguish_the_two(self, monkeypatch):
        """The demo surface, not just the payload."""
        _patch_retrieval(monkeypatch, self.OUTAGE)
        for model_id in ("mock-outline", "mock-terse"):
            outage_text = engine.run_turn("Q?", model_id=model_id).content
            _patch_retrieval(monkeypatch, RetrievalResult(sources=[]))
            empty_text = engine.run_turn("Q?", model_id=model_id).content
            _patch_retrieval(monkeypatch, self.OUTAGE)

            assert outage_text != empty_text, model_id
            assert "could not be run" in outage_text, model_id
            # The outage reply must not tell the user to go attach something:
            # nothing they attach fixes a server being down.
            assert "matched zero sources" not in outage_text, model_id
