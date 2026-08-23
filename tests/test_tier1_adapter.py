"""Tests for the Tier 1 <-> Tier 2 bridge (`secondlook.tier1_adapter`).

No FalkorDB and no network: every test injects a fake graph object exposing
`.query()`, which is the same affordance Tier 1's own unit tests use. The point
of these tests is the *seam* — the activation rule, the dict->dataclass
conversion, and the graph write shape — not Tier 1's Cypher, which Tier 1 tests
itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from secondlook.graph import StructuralSignal, utc_now_iso
from secondlook.tier1_adapter import (
    STRONG_EVIDENCE_LEVELS,
    FalkorDBGraphSink,
    Tier1Retrieval,
    Tier1RetrievalPolicy,
    to_result_item,
)
from secondlook.tier1_contract import ActivationPolicy, GraphSink, Tier1ResultItem

# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------


@dataclass
class FakeQueryResult:
    result_set: list


class RecordingGraph:
    """Captures queries and returns canned rows, in call order."""

    def __init__(self, responses=None):
        self.calls: list[tuple[str, dict]] = []
        self._responses = list(responses or [])

    def query(self, q, params=None):
        self.calls.append((q, params or {}))
        if self._responses:
            return FakeQueryResult(self._responses.pop(0))
        return FakeQueryResult([])


class VariantGraph:
    """Fake graph for the sink: `existing_vid` is the id `_FIND_VARIANT`
    returns, or None to force the create path."""

    def __init__(self, existing_vid=None):
        self.calls: list[tuple[str, dict]] = []
        self._existing = existing_vid

    def query(self, q, params=None):
        self.calls.append((q, params or {}))
        if "MATCH (gn:Gene {symbol: $gene})-[:HAS_VARIANT]" in q:
            return FakeQueryResult([[self._existing]] if self._existing is not None else [])
        if "CREATE (v:Variant" in q:
            return FakeQueryResult([[999]])
        return FakeQueryResult([[1]])

    def find(self, needle):
        """The single query containing `needle`."""
        hits = [c for c in self.calls if needle in c[0]]
        assert len(hits) == 1, f"expected exactly one query containing {needle!r}, got {len(hits)}"
        return hits[0]


def civic_row(level="A", drug="imatinib", direction="sensitive", civic_id=1):
    """One row in the shape Tier 1's _row_to_item produces."""
    return {
        "type": "documented",
        "source": "CIViC",
        "evidence_level": level,
        "citation": {"id": str(civic_id), "url": f"https://civicdb.org/evidence/{civic_id}"},
        "summary": f"level {level} evidence",
        "drug": drug,
        "trial_status": None,
        "retrieval_mode": "exact",
    }


class StubPolicy(Tier1RetrievalPolicy):
    """Bypasses retrieval so `_classify` can be exercised on its own."""

    def __init__(self, found: Tier1Retrieval):
        super().__init__(graph=None)
        self._found = found

    def retrieve(self, *args, **kwargs) -> Tier1Retrieval:
        return self._found


def found(rows, mode="exact", filtered=0) -> Tier1Retrieval:
    return Tier1Retrieval(
        items=tuple(to_result_item(r) for r in rows), filtered_count=filtered, mode=mode
    )


# --------------------------------------------------------------------------
# the adapter satisfies the contracts it claims to
# --------------------------------------------------------------------------


def test_policy_satisfies_activation_policy_protocol():
    assert isinstance(Tier1RetrievalPolicy(), ActivationPolicy)


def test_sink_satisfies_graph_sink_protocol():
    assert isinstance(FalkorDBGraphSink(), GraphSink)


def test_real_implementations_are_not_flagged_as_placeholders():
    """`is_placeholder` is how callers tell a stub from the real thing; the
    placeholders in tier1_contract report True, so these must report False or
    the distinction is useless."""
    assert Tier1RetrievalPolicy().is_placeholder is False
    assert FalkorDBGraphSink().is_placeholder is False


# --------------------------------------------------------------------------
# dict -> dataclass conversion
# --------------------------------------------------------------------------


def test_to_result_item_flattens_nested_citation():
    item = to_result_item(civic_row(civic_id=42))
    assert isinstance(item, Tier1ResultItem)
    assert item.citation_id == "42"
    assert item.citation_url == "https://civicdb.org/evidence/42"
    assert item.type == "documented"


def test_to_result_item_rejects_a_row_with_no_citation_url():
    """Tier 1 filters these itself, but the contract's own invariant must hold
    independently — two filters, because a citation-less item reaching the UI
    is the one failure mode api-contracts.md calls out by name."""
    row = civic_row()
    row["citation"] = {"id": "1", "url": ""}
    with pytest.raises(ValueError):
        to_result_item(row)


# --------------------------------------------------------------------------
# the activation rule (tier1-retrieval.md SSActivation)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("level", sorted(STRONG_EVIDENCE_LEVELS))
def test_exact_match_at_level_a_or_b_is_a_strong_hit_and_does_not_run_tier2(level):
    decision = StubPolicy(found([civic_row(level=level)])).decide(
        gene="ABL1", mutation="p.Thr315Ile"
    )
    assert decision.state == "strong_hit"
    assert decision.should_run_tier2 is False
    assert level in decision.reason


@pytest.mark.parametrize("level", ["C", "D", "E"])
def test_exact_match_at_level_c_to_e_is_a_weak_hit_and_runs_tier2(level):
    decision = StubPolicy(found([civic_row(level=level)])).decide(
        gene="ABL1", mutation="p.Thr315Ile"
    )
    assert decision.state == "weak_hit"
    assert decision.should_run_tier2 is True


def test_relaxed_match_is_weak_even_when_the_evidence_level_is_a():
    """The spec's strong clause requires level A/B *for this exact variant*.
    A level-A hit on a different variant of the same gene is Mode 2 output and
    must not suppress Tier 2 — this is the clause most likely to be got wrong,
    because the level alone looks strong."""
    decision = StubPolicy(found([civic_row(level="A")], mode="relaxed")).decide(
        gene="ABL1", mutation="p.Thr315Ile"
    )
    assert decision.state == "weak_hit"
    assert decision.should_run_tier2 is True
    assert "relaxation" in decision.reason


def test_no_evidence_anywhere_is_no_hit_and_runs_tier2():
    decision = StubPolicy(found([], mode="none", filtered=3)).decide(
        gene="ABL1", mutation="p.Thr315Ile"
    )
    assert decision.state == "no_hit"
    assert decision.should_run_tier2 is True
    assert "3 row(s) filtered" in decision.reason


def test_manual_override_runs_tier2_without_querying_the_graph():
    graph = RecordingGraph()
    decision = Tier1RetrievalPolicy(graph=graph).decide(
        gene="ABL1", mutation="p.Thr315Ile", manual_override=True
    )
    assert decision.state == "manual_override"
    assert decision.should_run_tier2 is True
    assert graph.calls == [], "override must not cost a graph round-trip"


def test_strong_and_weak_rationales_disclose_that_trials_were_not_evaluated():
    """Tier 1 loads CIViC and PubMed but no trial source, so half of the
    spec's strong-hit clause cannot be evaluated. Saying so is the difference
    between an unimplemented source and a negative finding."""
    for rows, mode in ([civic_row(level="A")], "exact"), ([civic_row(level="C")], "exact"):
        reason = (
            StubPolicy(found(rows, mode=mode)).decide(gene="ABL1", mutation="p.Thr315Ile").reason
        )
        assert "not evaluated" in reason


# --------------------------------------------------------------------------
# retrieval order: Mode 1, then Mode 2 only on a miss
# --------------------------------------------------------------------------


def test_relaxed_retrieval_is_skipped_when_exact_returns_items(monkeypatch):
    calls = []

    class FakeRetrieval:
        @staticmethod
        def retrieve_exact(gene, hgvs_p=None, *, variant_name=None, graph=None):
            calls.append("exact")
            return type("R", (), {"items": [civic_row()], "filtered_count": 0})()

        @staticmethod
        def retrieve_relaxed(*args, **kwargs):
            calls.append("relaxed")
            raise AssertionError("must not be called when exact found items")

    monkeypatch.setattr("secondlook.tier1_adapter._import_retrieval", lambda: FakeRetrieval)
    result = Tier1RetrievalPolicy().retrieve("ABL1", "p.Thr315Ile")
    assert calls == ["exact"]
    assert result.mode == "exact"


def test_filtered_counts_from_both_passes_are_summed(monkeypatch):
    """Reporting only the relaxed pass's count would under-report what was
    dropped on the way to the answer."""

    class FakeRetrieval:
        @staticmethod
        def retrieve_exact(gene, hgvs_p=None, *, variant_name=None, graph=None):
            return type("R", (), {"items": [], "filtered_count": 2})()

        @staticmethod
        def retrieve_relaxed(*args, **kwargs):
            return type("R", (), {"items": [civic_row()], "filtered_count": 5})()

    monkeypatch.setattr("secondlook.tier1_adapter._import_retrieval", lambda: FakeRetrieval)
    result = Tier1RetrievalPolicy().retrieve("ABL1", "p.Thr315Ile")
    assert result.filtered_count == 7
    assert result.mode == "relaxed"


# --------------------------------------------------------------------------
# graph write
# --------------------------------------------------------------------------


def a_signal(**overrides) -> StructuralSignal:
    base = dict(
        gene="ABL1",
        hgvs_p="p.Thr315Ile",
        drug="imatinib",
        alphamissense_score=0.91,
        alphamissense_class="likely_pathogenic",
        structure_source="PDB",
        structure_id="5HU9",
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
    base.update(overrides)
    return StructuralSignal(**base)


def test_emit_writes_the_two_contract_edges():
    graph = VariantGraph(existing_vid=7)
    FalkorDBGraphSink(graph=graph).emit(a_signal())
    cypher, params = graph.find("PREDICTS_BINDING_CHANGE")
    assert "HAS_COMPUTATIONAL_SIGNAL" in cypher
    assert params["vid"] == 7
    assert params["drug"] == "imatinib"


def test_emit_attaches_to_an_existing_variant_instead_of_creating_a_duplicate():
    """The bug this guards: CIViC stores hgvs_p RefSeq-prefixed
    ("NP_005148.2:p.Thr315Ile"), Tier 2 computes it bare ("p.Thr315Ile"). A
    MERGE on the bare form matches nothing and mints a second, orphan Variant
    node for a variant the graph already has."""
    graph = VariantGraph(existing_vid=7)
    FalkorDBGraphSink(graph=graph).emit(a_signal())
    assert not any(
        "CREATE (v:Variant" in q for q, _ in graph.calls
    ), "a variant already in the graph must not be re-created"
    _, params = graph.find("MATCH (gn:Gene {symbol: $gene})-[:HAS_VARIANT]")
    assert params["hgvs_suffix"] == ":p.Thr315Ile"


def test_variant_suffix_match_is_anchored_at_the_accession_boundary():
    """Without the leading colon, "p.Val60Glu" would match
    "NP_004324.2:p.Val600Glu" as a plain string suffix."""
    graph = VariantGraph(existing_vid=7)
    FalkorDBGraphSink(graph=graph).emit(a_signal(hgvs_p="p.Val60Glu"))
    _, params = graph.find("MATCH (gn:Gene {symbol: $gene})-[:HAS_VARIANT]")
    assert params["hgvs_suffix"].startswith(":")
    assert not "NP_004324.2:p.Val600Glu".endswith(params["hgvs_suffix"])


def test_a_genuinely_new_variant_is_created_and_linked_to_its_gene():
    """An orphan Variant is unreachable by every Tier 1 traversal, which all
    start from Gene."""
    graph = VariantGraph(existing_vid=None)
    FalkorDBGraphSink(graph=graph).emit(a_signal())
    cypher, params = graph.find("CREATE (v:Variant")
    assert "MERGE (gn:Gene {symbol: $gene})" in cypher
    assert "CREATE (gn)-[:HAS_VARIANT]->(v)" in cypher
    assert params["gene"] == "ABL1"
    assert params["source"] == FalkorDBGraphSink.PROVENANCE_SOURCE


def test_a_created_variant_carries_provenance():
    """Every node in this graph records where it came from; a Variant minted by
    Tier 2 must not be the one exception."""
    graph = VariantGraph(existing_vid=None)
    FalkorDBGraphSink(graph=graph).emit(a_signal())
    _, params = graph.find("CREATE (v:Variant")
    assert params["retrieved_at"]
    assert params["source_version"] == "0.2.0"


def test_emit_creates_rather_than_overwrites_the_signal():
    """A second run is a new signal, not an edit — overwriting would destroy
    the provenance trail computed_at/pipeline_version exist to keep."""
    graph = VariantGraph(existing_vid=7)
    FalkorDBGraphSink(graph=graph).emit(a_signal())
    cypher, _ = graph.find("PREDICTS_BINDING_CHANGE")
    assert "CREATE (s:StructuralSignal)" in cypher
    assert "MERGE (d:Drug" in cypher


def test_emit_carries_provenance_and_the_proximity_measurement():
    graph = VariantGraph(existing_vid=7)
    FalkorDBGraphSink(graph=graph).emit(a_signal())
    props = graph.find("PREDICTS_BINDING_CHANGE")[1]["signal_props"]
    assert props["source"] == FalkorDBGraphSink.PROVENANCE_SOURCE
    assert props["source_version"] == "0.2.0"
    assert props["retrieved_at"]
    assert props["binding_site_distance_angstrom"] == 3.5
    assert props["calibration_status"] == "provisional"


def test_emit_does_not_label_a_computed_signal_with_an_evidence_database():
    """graph.py exists to keep computed and documented results distinguishable.
    Writing source='CIViC' onto a Tier 2 computation would undo that in one
    field."""
    graph = VariantGraph(existing_vid=7)
    FalkorDBGraphSink(graph=graph).emit(a_signal())
    assert graph.find("PREDICTS_BINDING_CHANGE")[1]["signal_props"]["source"] != "CIViC"


def test_emit_drops_none_valued_properties():
    """FalkorDB has no null; a None written as a property makes 'not computed'
    and 'computed as null' indistinguishable on read-back."""
    graph = VariantGraph(existing_vid=7)
    FalkorDBGraphSink(graph=graph).emit(a_signal(method=None, plddt_at_residue=None))
    props = graph.find("PREDICTS_BINDING_CHANGE")[1]["signal_props"]
    assert "method" not in props
    assert "plddt_at_residue" not in props
    assert None not in props.values()


def test_emit_snapshots_the_edge_properties_as_json():
    graph = VariantGraph(existing_vid=7)
    FalkorDBGraphSink(graph=graph).emit(a_signal(method="docking", delta_score=0.31))
    edge = json.loads(graph.find("PREDICTS_BINDING_CHANGE")[1]["edge_json"])
    assert edge["method"] == "docking"
    assert edge["delta_score"] == 0.31
    assert edge["calibration_status"] == "provisional"
