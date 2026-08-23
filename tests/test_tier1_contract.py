"""The Tier 1 integration seam and its placeholders."""

import pytest

from secondlook.tier1_contract import (
    ActivationDecision,
    AlwaysRunTier2Policy,
    CollectingGraphSink,
    Tier1ResultItem,
)

# --- api-contracts.md's hard rule on evidence items ---------------------------


def test_tier1_result_item_requires_a_citation_url():
    """'An item with no citation.url must not be constructed or returned.'

    Enforced in the constructor rather than left to call sites, so the rule
    cannot be forgotten once Tier 1 starts building these.
    """
    with pytest.raises(ValueError, match="citation_url"):
        Tier1ResultItem(
            source="CIViC",
            evidence_level="A",
            citation_id="civic:123",
            citation_url="",
            summary="Sensitive to drug X",
        )


def test_tier1_result_item_rejects_whitespace_only_citation_url():
    with pytest.raises(ValueError):
        Tier1ResultItem(
            source="CIViC",
            evidence_level="A",
            citation_id="civic:123",
            citation_url="   ",
            summary="Sensitive to drug X",
        )


def test_valid_tier1_result_item_is_typed_documented():
    item = Tier1ResultItem(
        source="CIViC",
        evidence_level="A",
        citation_id="civic:123",
        citation_url="https://civicdb.org/events/genes/1/variants/12",
        summary="Sensitive to drug X",
    )
    assert item.type == "documented"


# --- Placeholders are honest and obviously placeholders -----------------------


def test_placeholder_policy_is_flagged_as_a_placeholder():
    decision = AlwaysRunTier2Policy().decide(gene="TP53", mutation="R175H", cancer_type=None)
    assert decision.is_placeholder is True
    assert AlwaysRunTier2Policy.is_placeholder is True


def test_placeholder_policy_never_fabricates_tier1_evidence():
    """The whole point: 'no documented evidence' is honest; invented evidence is not."""
    decision = AlwaysRunTier2Policy().decide(gene="BRAF", mutation="V600E", cancer_type="melanoma")
    assert decision.tier1_results == []
    assert decision.state == "no_hit"
    assert decision.should_run_tier2 is True


def test_placeholder_policy_explains_itself():
    decision = AlwaysRunTier2Policy().decide(gene="TP53", mutation="R175H", cancer_type=None)
    assert "placeholder" in decision.reason.lower()


def test_real_decisions_default_to_not_placeholder():
    decision = ActivationDecision(
        state="strong_hit", should_run_tier2=False, reason="CIViC level A"
    )
    assert decision.is_placeholder is False


def test_collecting_graph_sink_accumulates_in_order():
    sink = CollectingGraphSink()
    sink.emit("first")
    sink.emit("second")
    assert sink.signals == ["first", "second"]
    assert sink.is_placeholder is True


def test_tier2_adds_no_database_dependency():
    """§7 recommendation: return objects, don't write to FalkorDB from Tier 2."""
    import secondlook.pipeline as pipeline
    import secondlook.tier1_contract as tier1

    for module in (pipeline, tier1):
        source = open(module.__file__).read()
        assert "import falkordb" not in source
        assert "from falkordb" not in source
