"""Tests for session store, engine, and KG integration (Phases 1, 4)."""

from secondlook.case.state import Alteration, CaseState
from secondlook.chat.case_context import CaseSnapshot, Diagnosis
from secondlook.chat.engine import build_prompt, citation_overclaim, run_turn
from secondlook.chat.knowledge import describe_context
from secondlook.chat.session import (
    create_session,
    delete_session,
    get_session,
    list_sessions,
    update_session,
)


def test_create_session_defaults_to_self_hosted_when_configured(monkeypatch):
    monkeypatch.setenv("ATHENA_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("ATHENA_LLM_MODEL", "candidate-model")
    sess = create_session()
    try:
        assert sess.model_id == "openai-compatible"
    finally:
        delete_session(sess.id)


def test_session_store_crud():
    sess = create_session(model_id="mock-terse", attachment_ids=["variant-normalizer"])
    assert sess.id is not None
    assert sess.model_id == "mock-terse"
    assert sess.attachment_ids == ["variant-normalizer"]
    assert sess.case_id is None
    assert sess.as_dict()["case_id"] is None

    fetched = get_session(sess.id)
    assert fetched is not None
    assert fetched.id == sess.id

    msg = sess.add_message("user", "Hello world")
    assert msg["content"] == "Hello world"
    assert len(sess.history) == 1

    updated = update_session(sess.id, context_id="gene:EGFR", case_id="case-1")
    assert updated.context_id == "gene:EGFR"
    assert updated.case_id == "case-1"
    assert sess.as_dict()["case_id"] == "case-1"

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


# --- Issue #124: citation_overclaim() and its wiring into run_turn() ------


def test_citation_overclaim_none_when_stated_count_matches_reality():
    text = "Across 2 retrieved source(s): [1] one item. [2] another item."
    assert citation_overclaim(text, source_count=2) is None


def test_citation_overclaim_flags_a_stated_count_higher_than_reality():
    text = "Across 3 retrieved source(s), the strongest is..."
    violation = citation_overclaim(text, source_count=0)
    assert violation is not None
    assert "3" in violation and "0" in violation


def test_citation_overclaim_flags_a_cited_bracket_index_higher_than_reality():
    text = "EGFR T790M confers sensitivity to osimertinib.[2]"
    violation = citation_overclaim(text, source_count=1)
    assert violation is not None


def test_citation_overclaim_ignores_a_non_numeric_bracket():
    # A bracketed entity label like "[Q999Z]" is not a citation index --
    # only "[<digits>]" counts, matching the system prompt's own [1], [2]
    # convention.
    text = "The variant [Q999Z] was mentioned in the question."
    assert citation_overclaim(text, source_count=0) is None


def test_citation_overclaim_none_for_an_honest_zero_source_disclaimer():
    # The exact shape the mock clients produce when nothing was retrieved
    # -- no bracket markers, no inflated count -- must not be flagged.
    text = (
        "No grounded answer available for 'What is XYZ?': zero sources "
        "were attached to this turn."
    )
    assert citation_overclaim(text, source_count=0) is None


class _OverclaimingClient:
    """A fake real model that ignores DEFAULT_SYSTEM's instruction and
    states more sources than were actually retrieved -- exactly the
    failure mode #107 found in the mocks, reproduced here for a client
    that (unlike the mocks) has no structural reason not to do it."""

    model = "fake-overclaiming-model"

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        return "Across 5 retrieved source(s), osimertinib is well documented.[3]"


def test_run_turn_withholds_output_that_overclaims_and_records_it(monkeypatch):
    """The actual regression guard for issue #124: a client free to ignore
    DEFAULT_SYSTEM's instruction (unlike the two structurally-bound mocks)
    must still have its overclaiming answer caught and withheld by
    run_turn, not shown to the user as if it were trustworthy."""
    monkeypatch.setattr(
        "secondlook.chat.engine.build_client",
        lambda model_id: _OverclaimingClient(),
    )
    result = run_turn("What evidence exists for ZZFAKE1 Z999Z?", model_id="fake-overclaiming-model")
    assert result.sources_count == 0
    assert "overstated the retrieved evidence" in result.content
    assert "Across 5" not in result.content  # the fabricated text was not shown
    assert any(n.startswith("citation gate withheld model output") for n in result.notes)


def test_run_turn_does_not_touch_honest_output(monkeypatch):
    """A client that stays within what was actually retrieved must pass
    through unmodified -- the gate should never rewrite a truthful answer."""

    class HonestClient:
        model = "fake-honest-model"

        def complete(self, prompt: str, *, system: str | None = None) -> str:
            del prompt, system
            return "No sources were retrieved for this question."

    monkeypatch.setattr("secondlook.chat.engine.build_client", lambda model_id: HonestClient())
    result = run_turn("What evidence exists for ZZFAKE1 Z999Z?", model_id="fake-honest-model")
    assert result.content == "No sources were retrieved for this question."
    assert not any(n.startswith("citation gate withheld model output") for n in result.notes)


_FAKE_SOURCES = [
    {
        "id": "civic:1",
        "citation_index": 1,
        "title": "EGFR T790M → osimertinib",
        "evidence_level": "A",
        "summary": "documented sensitivity",
        "citation_url": "http://civicdb.org",
        "pmid": "1",
    }
]


def _stub_retrieval(monkeypatch) -> None:
    monkeypatch.setattr(
        "secondlook.chat.engine.retrieve_evidence_for_turn",
        lambda *args, **kwargs: list(_FAKE_SOURCES),
    )


def test_case_context_does_not_change_sources_or_sources_count(monkeypatch):
    """Issue #107: patient facts are CONTEXT, never citable sources."""
    _stub_retrieval(monkeypatch)
    state = CaseState(
        case_id="case-1",
        alterations=(
            Alteration(
                gene="EGFR",
                variant="T790M",
                variant_type="missense",
                assay=None,
                tested_on=None,
                event_id="e1",
            ),
        ),
    )
    without = run_turn("What is EGFR T790M?", model_id="mock-terse")
    with_case = run_turn(
        "What is EGFR T790M?",
        model_id="mock-terse",
        case_id="case-1",
        case_state_loader=lambda _cid: CaseSnapshot(
            state=state, diagnosis=Diagnosis(cancer_type="NSCLC")
        ),
    )
    assert without.sources == with_case.sources
    assert without.sources_count == with_case.sources_count
    assert with_case.sources_count == len(_FAKE_SOURCES)
    assert any("EGFR" in line and "T790M" in line for line in with_case.context_lines)
    case_fact_lines = [line for line in with_case.context_lines if "T790M" in line]
    assert case_fact_lines
    assert not any(line in without.context_lines for line in case_fact_lines)


def test_unknown_case_id_notes_and_still_returns_a_turn(monkeypatch):
    _stub_retrieval(monkeypatch)
    missing = run_turn(
        "What is EGFR T790M?",
        model_id="mock-terse",
        case_id="missing-case",
        case_state_loader=lambda _cid: None,
    )
    assert any("case record could not be loaded" in n for n in missing.notes)
    assert missing.content
    assert missing.sources_count == len(_FAKE_SOURCES)

    def boom(_cid: str):
        raise RuntimeError("postgres unreachable")

    failed = run_turn(
        "What is EGFR T790M?",
        model_id="mock-terse",
        case_id="missing-case",
        case_state_loader=boom,
    )
    assert any("case record could not be loaded" in n for n in failed.notes)
    assert failed.content


def test_run_turn_can_use_supplied_sources_instead_of_the_graph(monkeypatch):
    """The study's chat arm (issue #136) supplies the case's findings as the
    turn's sources; graph retrieval must not run at all."""

    def boom(*args, **kwargs):
        raise AssertionError("retrieval must be skipped when sources are supplied")

    monkeypatch.setattr("secondlook.chat.engine.retrieve_evidence_for_turn", boom)
    sources = [
        {
            "id": "study:f1",
            "citation_index": 1,
            "title": "A finding",
            "summary": "A finding",
            "evidence_level": "B",
            "pmid": "SYN-1",
            "citation_url": "https://example.org/x",
        }
    ]
    result = run_turn(
        "What changed?",
        model_id="mock-outline",
        sources_override=sources,
        extra_context_lines=["2026-01-01: something happened"],
    )
    assert result.sources_count == 1
    assert "2026-01-01: something happened" in result.context_lines
    assert "A finding" in result.content
