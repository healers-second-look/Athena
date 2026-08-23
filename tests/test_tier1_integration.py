"""Live Tier 1 <-> Tier 2 integration. Requires FalkorDB and a loaded graph.

    docker compose up -d                       # in the Athena_Tier_1 repo
    python -m secondlook.tier1.civic_loader

Everything here is marked `integration` and therefore deselected by the default
addopts. These tests exist because the two bugs that actually mattered — the
StructuralSignal schema drift and the hgvs_p variant-join mismatch — were both
invisible to unit tests with fake graphs. Each one passed every mock and failed
against real data.
"""

from __future__ import annotations

import pytest

from secondlook.graph import StructuralSignal, utc_now_iso
from secondlook.tier1_adapter import FalkorDBGraphSink, Tier1RetrievalPolicy

pytestmark = pytest.mark.integration

TEST_GENE = "SECONDLOOK_TEST_GENE"
TEST_HGVS = "p.Thr999Ile"
#: Every drug name this module writes, so the fixture can clean all of them up.
TEST_DRUGS = ["TESTDRUG", "DRUG_A", "DRUG_B"]


@pytest.fixture
def graph():
    pytest.importorskip("falkordb", reason="falkordb client not installed")
    # The falkordb client is a thin layer over redis-py and raises redis's
    # exception types, not its own — `falkordb.exceptions` defines no error
    # classes at all. And redis.exceptions.ConnectionError does NOT subclass
    # the builtin ConnectionError/OSError, so catching those does not cover it
    # either. Getting this wrong means the suite ERRORS instead of skipping
    # when the database is simply not running, which is exactly what happened
    # the first time Docker went down.
    redis_exceptions = pytest.importorskip("redis.exceptions")
    from secondlook.tier1.graph_connection import connect_graph

    try:
        g = connect_graph()
        g.query("RETURN 1")
    except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError) as exc:
        pytest.skip(f"FalkorDB not reachable ({exc}); start it with `docker compose up -d`")
    yield g
    # Only ever removes this test's own synthetic gene.
    g.query(
        "MATCH (gn:Gene {symbol: $g})-[:HAS_VARIANT]->(v:Variant) "
        "OPTIONAL MATCH (v)-[:HAS_COMPUTATIONAL_SIGNAL]->(s:StructuralSignal) "
        "DETACH DELETE gn, v, s",
        params={"g": TEST_GENE},
    )
    # The sink MERGEs a Drug per signal. Deleting the signal leaves those
    # behind, and a stray test drug in a shared graph is not inert: the ChEMBL
    # enrichment pass picks it up and reports it as an unmatched real drug.
    # Restricted to drugs this test names AND that nothing else references, so
    # a name colliding with a real CIViC drug is never removed.
    g.query(
        "MATCH (d:Drug) WHERE d.name IN $names AND NOT (d)<-[]-() AND NOT (d)-[]->() " "DELETE d",
        params={"names": TEST_DRUGS},
    )


def a_signal(drug="TESTDRUG", hgvs_p=TEST_HGVS) -> StructuralSignal:
    return StructuralSignal(
        gene=TEST_GENE,
        hgvs_p=hgvs_p,
        drug=drug,
        alphamissense_score=0.91,
        alphamissense_class="likely_pathogenic",
        structure_source="PDB",
        structure_id="0TST",
        plddt_at_residue=None,
        reliability_flag="high",
        method=None,
        delta_score=None,
        label=None,
        binding_site_distance_angstrom=3.5,
        confidence="low",
        calibration_status="provisional",
        computed_at=utc_now_iso(),
        pipeline_version="0.2.0",
        labeling_version="0.1.0-provisional",
    )


def test_the_graph_is_loaded(graph):
    n = graph.query("MATCH (gn:Gene)-[:HAS_VARIANT]->(:Variant) RETURN count(gn)").result_set[0][0]
    if n == 0:
        pytest.skip("graph is empty; run `python -m secondlook.tier1.civic_loader` first")
    assert n > 0


def test_activation_returns_no_hit_for_a_gene_outside_the_loaded_scope(graph):
    """Tier 1's scope is rare cancers; Tier 2's gold-standard set is
    common-cancer kinase biology, chosen for having known ground truth. So
    these must come back no_hit and hand off to Tier 2 — which is the product
    working, not a gap."""
    decision = Tier1RetrievalPolicy(graph=graph).decide(
        gene="ABL1", mutation="NP_005148.2:p.Thr315Ile"
    )
    assert decision.state == "no_hit"
    assert decision.should_run_tier2 is True
    assert decision.is_placeholder is False
    assert decision.tier1_results == []


def test_emitted_signal_is_reachable_from_its_gene(graph):
    """An orphan Variant is invisible to every Tier 1 traversal, all of which
    start at Gene."""
    FalkorDBGraphSink(graph=graph).emit(a_signal())
    rows = graph.query(
        "MATCH (gn:Gene {symbol: $g})-[:HAS_VARIANT]->(v:Variant)"
        "-[:HAS_COMPUTATIONAL_SIGNAL]->(s:StructuralSignal)"
        "-[:PREDICTS_BINDING_CHANGE]->(d:Drug) "
        "RETURN v.hgvs_p, d.name, s.binding_site_distance_angstrom",
        params={"g": TEST_GENE},
    ).result_set
    assert len(rows) == 1
    assert rows[0][0] == TEST_HGVS
    assert rows[0][2] == pytest.approx(3.5)


def test_two_drugs_on_one_variant_share_a_single_variant_node(graph):
    """The join bug in miniature: a second emit for the same variant must
    attach to the node the first one resolved, not mint another."""
    sink = FalkorDBGraphSink(graph=graph)
    sink.emit(a_signal(drug="DRUG_A"))
    sink.emit(a_signal(drug="DRUG_B"))
    variants = graph.query(
        "MATCH (gn:Gene {symbol: $g})-[:HAS_VARIANT]->(v:Variant) RETURN count(v)",
        params={"g": TEST_GENE},
    ).result_set[0][0]
    signals = graph.query(
        "MATCH (gn:Gene {symbol: $g})-[:HAS_VARIANT]->(:Variant)"
        "-[:HAS_COMPUTATIONAL_SIGNAL]->(s) RETURN count(s)",
        params={"g": TEST_GENE},
    ).result_set[0][0]
    assert variants == 1, "second emit created a duplicate Variant"
    assert signals == 2


def test_signal_survives_the_round_trip_with_calibration_status_intact(graph):
    """A label whose calibration state is lost on write is indistinguishable
    from a validated one on read."""
    FalkorDBGraphSink(graph=graph).emit(a_signal())
    row = graph.query(
        "MATCH (gn:Gene {symbol: $g})-[:HAS_VARIANT]->(:Variant)"
        "-[:HAS_COMPUTATIONAL_SIGNAL]->(s:StructuralSignal) "
        "RETURN s.calibration_status, s.pipeline_version, s.source, s.retrieved_at",
        params={"g": TEST_GENE},
    ).result_set[0]
    assert row[0] == "provisional"
    assert row[1] == "0.2.0"
    assert row[2] == FalkorDBGraphSink.PROVENANCE_SOURCE
    assert row[3]


def test_every_declared_structural_signal_property_is_queryable(graph):
    """Closes the schema-drift loop: Tier 1 declares these, so a query built
    from the declaration must actually read them back."""
    from secondlook.tier1.graph_schema import STRUCTURAL_SIGNAL

    FalkorDBGraphSink(graph=graph).emit(a_signal())
    returns = ", ".join(f"s.{p}" for p in STRUCTURAL_SIGNAL.properties)
    row = graph.query(
        f"MATCH (gn:Gene {{symbol: $g}})-[:HAS_VARIANT]->(:Variant)"
        f"-[:HAS_COMPUTATIONAL_SIGNAL]->(s:StructuralSignal) RETURN {returns}",
        params={"g": TEST_GENE},
    ).result_set[0]
    named = dict(zip(STRUCTURAL_SIGNAL.properties, row, strict=True))
    assert named["binding_site_distance_angstrom"] == pytest.approx(3.5)
    assert named["calibration_status"] == "provisional"
    assert named["structure_id"] == "0TST"
