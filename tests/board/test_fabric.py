"""Tests for Subsystem U: Per-Role Knowledge Graph Fabric.

Validates that:
1. Role knowledge graphs are strictly isolated namespaces.
2. Direct cross-graph edges without an identity anchor are structurally prohibited.
3. Node provenance is immutable.
4. ARCHITECTURE.md §5 evidence classes are strictly enforced (no citations on computed nodes).
5. Cross-graph entity resolution operates exclusively through IdentityAnchors.
6. Lane coverage metrics accurately report density and contradictions.
"""

import pytest

from secondlook.board.fabric import (
    AnchorType,
    ComputedCitationForbiddenError,
    CrossGraphEdgeForbiddenError,
    EvidenceClass,
    GraphEdge,
    GraphFabric,
    GraphNode,
    IdentityAnchor,
    NodeProvenanceTamperError,
    RoleKnowledgeGraph,
)


class TestIdentityAnchors:
    def test_anchor_canonical_keys(self):
        hgnc = IdentityAnchor(AnchorType.HGNC, "EGFR")
        assert hgnc.canonical_key == "HGNC:EGFR"

        nct = IdentityAnchor(AnchorType.NCT, "NCT03778229")
        assert nct.canonical_key == "NCT:NCT03778229"

    def test_inchikey_connectivity_layer_normalization(self):
        # Osimertinib InChIKey (full 27-char key with dashes)
        full_key = "XQLMNPDYSOROBR-UHFFFAOYSA-N"
        anchor = IdentityAnchor(AnchorType.INCHIKEY, full_key)
        # Should normalize to connectivity prefix
        assert anchor.canonical_key == "INCHIKEY:XQLMNPDYSOROBR"

    def test_empty_identifier_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            IdentityAnchor(AnchorType.HGNC, "")


class TestGraphNodeEvidenceClasses:
    def test_computed_node_with_citation_raises(self):
        with pytest.raises(ComputedCitationForbiddenError, match="must never carry citation"):
            GraphNode(
                node_id="comp_1",
                role_provenance="radiologist",
                evidence_class=EvidenceClass.COMPUTED,
                claim="RECIST tumor reduction 25%",
                method="DeepLesion",
                version="2.1",
                citation_url="https://example.com/forbidden",
            )

    def test_computed_node_without_method_raises(self):
        with pytest.raises(ValueError, match="requires 'method'"):
            GraphNode(
                node_id="comp_2",
                role_provenance="radiologist",
                evidence_class=EvidenceClass.COMPUTED,
                claim="RECIST tumor reduction 25%",
            )

    def test_documented_node_without_citation_raises(self):
        with pytest.raises(ValueError, match="requires 'citation_url'"):
            GraphNode(
                node_id="doc_1",
                role_provenance="medical_oncologist",
                evidence_class=EvidenceClass.DOCUMENTED,
                claim="Osimertinib 80mg daily improves PFS in EGFR T790M",
            )


class TestRoleKnowledgeGraphIsolation:
    def test_add_node_enforces_provenance_immutability(self):
        kg = RoleKnowledgeGraph("medical_oncologist")
        node_valid = GraphNode(
            node_id="n1",
            role_provenance="medical_oncologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="Valid claim",
            citation_url="https://example.com/source",
        )
        kg.add_node(node_valid)
        assert "n1" in kg.nodes

        node_foreign = GraphNode(
            node_id="n2",
            role_provenance="radiologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="Tampered claim",
            citation_url="https://example.com/source",
        )
        with pytest.raises(NodeProvenanceTamperError, match="Cannot insert node with provenance"):
            kg.add_node(node_foreign)

    def test_find_by_anchor(self):
        kg = RoleKnowledgeGraph("molecular_pathologist")
        anchor = IdentityAnchor(AnchorType.HGNC, "PIK3CA")
        node = GraphNode(
            node_id="mol_1",
            role_provenance="molecular_pathologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="PIK3CA H1047R is an activating kinase domain mutation",
            anchors=(anchor,),
            citation_url="https://civicdb.org/variants/123",
        )
        kg.add_node(node)

        results = kg.find_by_anchor(anchor)
        assert len(results) == 1
        assert results[0].node_id == "mol_1"

    def test_coverage_metrics(self):
        kg = RoleKnowledgeGraph("clinical_pharmacologist")
        doc_node = GraphNode(
            node_id="p1",
            role_provenance="clinical_pharmacologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="Warfarin interacts with capecitabine",
            citation_url="https://drugs.com/ddi",
        )
        context_node = GraphNode(
            node_id="p2",
            role_provenance="clinical_pharmacologist",
            evidence_class=EvidenceClass.CONTEXTUAL,
            claim="Background pharmacokinetic principle",
        )
        kg.add_node(doc_node)
        kg.add_node(context_node)
        kg.add_edge(
            GraphEdge(
                source_id="p1",
                target_id="p2",
                relation="CONTRADICTS",
                role_provenance="clinical_pharmacologist",
            )
        )

        cov = kg.coverage()
        assert cov.node_count == 2
        assert cov.edge_count == 1
        assert cov.contradiction_count == 1
        assert cov.citation_density == 0.5


class TestGraphFabricFederation:
    def test_direct_cross_kg_edge_is_strictly_forbidden(self):
        fabric = GraphFabric()
        kg_med = RoleKnowledgeGraph("medical_oncologist")
        kg_rad = RoleKnowledgeGraph("radiologist")
        fabric.register_graph(kg_med)
        fabric.register_graph(kg_rad)

        with pytest.raises(CrossGraphEdgeForbiddenError, match="Direct edge from .* is prohibited"):
            fabric.add_cross_edge("medical_oncologist", "radiologist", "n1", "n2")

    def test_cross_graph_resolution_via_identity_anchor(self):
        fabric = GraphFabric()
        kg_mol = RoleKnowledgeGraph("molecular_pathologist")
        kg_trials = RoleKnowledgeGraph("trials_access_officer")
        fabric.register_graph(kg_mol)
        fabric.register_graph(kg_trials)

        pik3ca = IdentityAnchor(AnchorType.HGNC, "PIK3CA")

        node_mol = GraphNode(
            node_id="mol_pik3ca",
            role_provenance="molecular_pathologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="PIK3CA mutation detected",
            anchors=(pik3ca,),
            citation_url="https://civicdb.org/variants/123",
        )
        node_trial = GraphNode(
            node_id="trial_alpelisib",
            role_provenance="trials_access_officer",
            evidence_class=EvidenceClass.REGULATORY,
            claim="Phase 3 trial recruiting PIK3CA altered breast cancer",
            anchors=(pik3ca,),
            instrument="CTgov",
        )

        kg_mol.add_node(node_mol)
        kg_trials.add_node(node_trial)

        resolved = fabric.resolve_cross_graph(pik3ca)
        assert "molecular_pathologist" in resolved
        assert "trials_access_officer" in resolved
        assert resolved["molecular_pathologist"][0].node_id == "mol_pik3ca"
        assert resolved["trials_access_officer"][0].node_id == "trial_alpelisib"

    def test_fabric_coverage_report(self):
        fabric = GraphFabric()
        kg_med = RoleKnowledgeGraph("medical_oncologist")
        fabric.register_graph(kg_med)
        report = fabric.generate_coverage_report()
        assert "medical_oncologist" in report
        assert report["medical_oncologist"].node_count == 0
