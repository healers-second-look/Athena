"""Tests for FalkorDB evidence retrieval (Phase 6). Needs a live graph with
real data -- see issue #109's own reproduction, which is what this pins.
"""

import pytest

from secondlook.chat.knowledge import retrieve_evidence_for_turn
from secondlook.tier1.graph_connection import connect_graph


@pytest.fixture
def evidence_graph():
    """The FalkorDB graph this repo's dev data lives in, per issue #109's
    investigation. Not `secondlook_tier1` -- that one is empty; the real
    CIViC-sourced evidence used for live testing sits under `duplicate`.
    """
    try:
        graph = connect_graph("duplicate")
        graph.query("MATCH (n) RETURN n LIMIT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no live FalkorDB with real evidence data reachable: {exc}")
    return graph


@pytest.mark.integration
def test_gene_query_does_not_pull_in_unrelated_genes(evidence_graph):
    """Issue #109: asking about JAK1 overexpression must not also return
    PDGFRB/PDGFRA/CASP8/IL6 sources just because they share the variant
    name "Overexpression". Every returned source's gene must be JAK1.
    """
    sources = retrieve_evidence_for_turn(
        entities={"genes": ["JAK1"], "variants": ["Overexpression"]},
        graph=evidence_graph,
    )
    assert sources, "expected at least one real JAK1 source in the dev dataset"
    unrelated = [s["gene"] for s in sources if s["gene"] != "JAK1"]
    assert not unrelated, f"pulled in unrelated genes: {unrelated}"


@pytest.mark.integration
def test_bare_variant_with_no_gene_still_falls_back_to_variant_match(evidence_graph):
    """The fallback this fix must not break: a variant token with no
    recognized gene (e.g. a bare HGVS string) should still search by
    variant name.
    """
    sources = retrieve_evidence_for_turn(
        entities={"genes": [], "variants": ["NP_000537.3:p.Arg273His"]},
        graph=evidence_graph,
    )
    assert sources, "expected the bare-variant fallback to still find TP53's own variant"
    assert all(s["gene"] == "TP53" for s in sources)
