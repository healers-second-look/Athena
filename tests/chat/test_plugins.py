"""Tests for chat plugins, skills, and modes (Phase 3)."""

from secondlook.chat.plugins import (
    Turn,
    apply_attachments,
    list_attachments,
    unknown_ids,
)


def test_list_attachments():
    attachments = list_attachments()
    ids = {a.id for a in attachments}
    assert "variant-normalizer" in ids
    assert "citation-guard" in ids
    assert "evidence-grader" in ids
    assert "mode:explore" in ids
    assert "mode:strict-evidence" in ids
    assert "mode:tumor-board" in ids


def test_unknown_ids():
    assert unknown_ids(["variant-normalizer", "bogus"]) == ["bogus"]
    assert unknown_ids(["variant-normalizer"]) == []


def test_variant_normalizer_extracts_entities():
    turn = Turn(
        message="What is the significance of EGFR T790M and KRAS G12D in NSCLC patients?",
        system_prompt="Base prompt",
    )
    apply_attachments(turn, ["variant-normalizer"])

    assert "genes" in turn.entities
    assert "EGFR" in turn.entities["genes"]
    assert "KRAS" in turn.entities["genes"]
    # NSCLC is in _NOT_GENES so it should not be treated as a gene
    assert "NSCLC" not in turn.entities["genes"]

    assert "variants" in turn.entities
    assert "T790M" in turn.entities["variants"]
    assert "G12D" in turn.entities["variants"]

    assert any("variant-normalizer" in note for note in turn.notes)
    assert any("Normalized entities" in line for line in turn.context_lines)


def test_citation_guard_without_sources():
    turn = Turn(message="Tell me about osimertinib.", system_prompt="Base prompt")
    apply_attachments(turn, ["citation-guard"])

    assert "CITATION GUARD: nothing was retrieved" in turn.system_prompt
    assert any("citation-guard active with NO retrieved context" in note for note in turn.notes)


def test_citation_guard_with_sources():
    turn = Turn(
        message="Tell me about osimertinib.",
        system_prompt="Base prompt",
        sources=[{"id": "civic:123", "title": "Study A"}],
    )
    apply_attachments(turn, ["citation-guard"])

    assert "CITATION GUARD: cite a retrieved source" in turn.system_prompt


def test_evidence_grader():
    turn = Turn(message="Question", system_prompt="Base prompt")
    apply_attachments(turn, ["evidence-grader"])

    assert "EVIDENCE GRADING" in turn.system_prompt


def test_modes_affect_budget_and_system_prompt():
    turn_strict = Turn(message="Question", system_prompt="Base prompt")
    apply_attachments(turn_strict, ["mode:strict-evidence"])
    assert turn_strict.max_sources == 4
    assert "MODE strict-evidence" in turn_strict.system_prompt

    turn_explore = Turn(message="Question", system_prompt="Base prompt")
    apply_attachments(turn_explore, ["mode:explore"])
    assert turn_explore.max_sources == 12
    assert "MODE explore" in turn_explore.system_prompt
