"""Unit tests for citation_gate.py -- deterministic, no LLM, no network.

Written against synthetic LLM output per the issue's own rationale: this
gate is testable before subsystem I's LLM integration exists at all.
"""

from __future__ import annotations

from secondlook.synthesis.citation_gate import enforce_citations


def _tier1_item(item_id: str) -> dict:
    return {
        "type": "documented",
        "source": "CIViC",
        "evidence_level": "A",
        "citation": {"id": item_id, "url": f"https://civicdb.org/{item_id}"},
        "summary": "summary",
        "drug": "Drug X",
        "trial_status": None,
    }


def test_cited_sentence_is_kept():
    text = "Drug X shows response in this context.[ref:civic_1]"
    accepted, cited_ids, dropped = enforce_citations(text, [_tier1_item("civic_1")])

    assert accepted == text
    assert cited_ids == ["civic_1"]
    assert dropped == 0


def test_uncited_sentence_is_removed_and_counted():
    text = (
        "Drug X shows response in this context.[ref:civic_1] "
        "This is an unsupported editorial claim with no citation."
    )
    accepted, cited_ids, dropped = enforce_citations(text, [_tier1_item("civic_1")])

    assert accepted == "Drug X shows response in this context.[ref:civic_1]"
    assert cited_ids == ["civic_1"]
    assert dropped == 1


def test_sentence_citing_unknown_id_is_dropped():
    text = "Drug X shows response.[ref:does_not_exist]"
    accepted, cited_ids, dropped = enforce_citations(text, [_tier1_item("civic_1")])

    assert accepted == ""
    assert cited_ids == []
    assert dropped == 1


def test_sentence_kept_if_at_least_one_of_multiple_markers_resolves():
    text = "Drug X shows response.[ref:civic_1][ref:does_not_exist]"
    accepted, cited_ids, dropped = enforce_citations(text, [_tier1_item("civic_1")])

    assert accepted == text
    assert cited_ids == ["civic_1"]
    assert dropped == 0


def test_multiple_valid_markers_all_recorded():
    text = "Drug X shows response.[ref:civic_1][ref:civic_2]"
    accepted, cited_ids, dropped = enforce_citations(
        text, [_tier1_item("civic_1"), _tier1_item("civic_2")]
    )

    assert accepted == text
    assert cited_ids == ["civic_1", "civic_2"]
    assert dropped == 0


def test_cited_ids_deduplicated_preserving_first_occurrence_order():
    text = (
        "Drug X shows response.[ref:civic_1] "
        "Drug X is also documented elsewhere.[ref:civic_2][ref:civic_1]"
    )
    accepted, cited_ids, dropped = enforce_citations(
        text, [_tier1_item("civic_1"), _tier1_item("civic_2")]
    )

    assert cited_ids == ["civic_1", "civic_2"]
    assert dropped == 0


def test_empty_synthesis_text_returns_empty_with_no_drops():
    accepted, cited_ids, dropped = enforce_citations("", [_tier1_item("civic_1")])

    assert accepted == ""
    assert cited_ids == []
    assert dropped == 0


def test_no_retrieved_items_drops_every_sentence():
    text = "Drug X shows response.[ref:civic_1] Drug Y is documented.[ref:civic_2]"
    accepted, cited_ids, dropped = enforce_citations(text, [])

    assert accepted == ""
    assert cited_ids == []
    assert dropped == 2


def test_item_id_falls_back_to_top_level_id_when_no_citation_object():
    # Tier 2 item shape (docs/api-contracts.md) has no `citation` sub-object.
    tier2_item = {"type": "computational_signal", "id": "tier2_1", "drug": "Drug X"}
    text = "Binding affinity is likely reduced.[ref:tier2_1]"

    accepted, cited_ids, dropped = enforce_citations(text, [tier2_item])

    assert accepted == text
    assert cited_ids == ["tier2_1"]
    assert dropped == 0


def test_item_with_neither_citation_id_nor_top_level_id_is_uncitable():
    item = {"type": "documented", "citation": {"url": "https://example.com"}}
    text = "Drug X shows response.[ref:civic_1]"

    accepted, cited_ids, dropped = enforce_citations(text, [item])

    assert accepted == ""
    assert cited_ids == []
    assert dropped == 1


def test_all_sentences_dropped_when_none_cite():
    text = "Unsupported claim one. Unsupported claim two."
    accepted, cited_ids, dropped = enforce_citations(text, [_tier1_item("civic_1")])

    assert accepted == ""
    assert cited_ids == []
    assert dropped == 2
