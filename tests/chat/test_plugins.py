"""Tests for chat plugins, skills, and modes (Phase 3)."""

import pytest

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


# citation-guard is a POST-retrieval hook. Passing phase="post" here is not
# ceremony: the earlier version of these tests called `apply_attachments`
# with sources pre-populated, which is a state the engine never produced --
# it filled sources in *after* running the plugins. The unit tests passed
# against a world the integration did not have, which is precisely how the
# guard shipped telling the model "nothing was retrieved" over a prompt full
# of sources. `test_engine.py` now pins the real ordering as well.
def test_citation_guard_without_sources():
    turn = Turn(message="Tell me about osimertinib.", system_prompt="Base prompt")
    apply_attachments(turn, ["citation-guard"], phase="post")

    assert "CITATION GUARD: nothing was retrieved" in turn.system_prompt
    assert any("citation-guard active with NO retrieved context" in note for note in turn.notes)


def test_citation_guard_with_sources():
    turn = Turn(
        message="Tell me about osimertinib.",
        system_prompt="Base prompt",
        sources=[{"id": "civic:123", "title": "Study A"}],
    )
    apply_attachments(turn, ["citation-guard"], phase="post")

    assert "CITATION GUARD: cite a retrieved source" in turn.system_prompt
    assert any("1 retrieved source(s) present" in note for note in turn.notes)


def test_citation_guard_separates_an_outage_from_an_empty_search():
    """A failed lookup is not a finding of 'no evidence'."""
    down = Turn(message="Q", system_prompt="Base", retrieval_failed=True)
    apply_attachments(down, ["citation-guard"], phase="post")

    empty = Turn(message="Q", system_prompt="Base")
    apply_attachments(empty, ["citation-guard"], phase="post")

    assert "retrieval FAILED" in down.system_prompt
    assert "do not state or imply that no evidence exists" in down.system_prompt
    assert "nothing was retrieved" in empty.system_prompt
    assert down.system_prompt != empty.system_prompt


def test_a_post_hook_does_not_run_in_the_pre_phase():
    """The guard rail on the bug itself.

    If citation-guard ever runs pre-retrieval again it sees an empty
    `sources` list and contradicts the prompt built underneath it.
    """
    turn = Turn(message="Q", system_prompt="Base", sources=[{"id": "civic:1"}])
    apply_attachments(turn, ["citation-guard"], phase="pre")
    assert turn.system_prompt == "Base", "citation-guard must not run before retrieval"
    assert turn.notes == []


def test_modes_are_pre_hooks_because_retrieval_reads_max_sources():
    turn = Turn(message="Q", system_prompt="Base")
    apply_attachments(turn, ["mode:strict-evidence"], phase="pre")
    assert turn.max_sources == 4, "a mode that runs after retrieval cannot bound it"


def test_an_unknown_phase_is_rejected():
    turn = Turn(message="Q", system_prompt="Base")
    with pytest.raises(ValueError, match="phase must be"):
        apply_attachments(turn, ["citation-guard"], phase="during")


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
