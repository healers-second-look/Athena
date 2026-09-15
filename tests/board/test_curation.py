"""Tests for Subsystem V (KG Construction & Curation Pipeline)."""

import pytest

from secondlook.board.curation import (
    CurationPipeline,
    CuratorActionError,
    LicenseType,
    LicenseViolationError,
    StagedNodeStatus,
)
from secondlook.board.fabric import (
    AnchorType,
    EvidenceClass,
    GraphFabric,
    GraphNode,
    IdentityAnchor,
    RoleKnowledgeGraph,
)
from secondlook.board.overrule import (
    ClinicianOverrule,
    OverruleAction,
    OverruleLedger,
)


@pytest.fixture
def test_fabric() -> GraphFabric:
    fabric = GraphFabric()
    kg_med = RoleKnowledgeGraph(role_id="medical_oncologist", graph_id="medical_oncologist_kg")
    fabric.register_graph(kg_med)

    kg_pharm = RoleKnowledgeGraph(
        role_id="clinical_pharmacologist", graph_id="clinical_pharmacologist_kg"
    )
    fabric.register_graph(kg_pharm)
    return fabric


def test_licensing_first_ingestion(test_fabric: GraphFabric) -> None:
    pipeline = CurationPipeline(test_fabric)

    # Permissible licenses succeed
    for lic in (
        LicenseType.CC_BY,
        LicenseType.CC0,
        LicenseType.PUBLIC_DOMAIN,
        LicenseType.OPEN_GOVERNMENT,
    ):
        staged = pipeline.stage_evidence(
            staged_id=f"staged-{lic.value}",
            role_id="medical_oncologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim=f"Claim under {lic.value}",
            citation_id="TEST-CIT",
            citation_url="https://doi.org/10.1016/j.annonc.2024.01.001",
            license=lic,
        )
        assert staged.status == StagedNodeStatus.PENDING_CONFIRMATION
        assert staged.license == lic

    # Proprietary or unknown license raises LicenseViolationError
    with pytest.raises(LicenseViolationError, match="is not permissible"):
        pipeline.stage_evidence(
            staged_id="staged-proprietary",
            role_id="medical_oncologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="Scraped proprietary clinical data",
            citation_id="PROPRIETARY-DB",
            citation_url="https://proprietary.internal",
            license=LicenseType.PROPRIETARY,
        )

    with pytest.raises(LicenseViolationError):
        pipeline.stage_evidence(
            staged_id="staged-unknown",
            role_id="medical_oncologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="Unverified web scrap",
            citation_id="UNKNOWN-SOURCE",
            citation_url="https://unverified.internal",
            license=LicenseType.UNKNOWN,
        )


def test_curator_gated_staging_and_promotion(test_fabric: GraphFabric) -> None:
    pipeline = CurationPipeline(test_fabric)
    med_kg = test_fabric.get_graph("medical_oncologist_kg")

    staged = pipeline.stage_evidence(
        staged_id="staged-med-101",
        role_id="medical_oncologist",
        evidence_class=EvidenceClass.DOCUMENTED,
        claim="Fulvestrant plus Alpelisib indicated for PIK3CA-mutated HR+/HER2- MBC",
        citation_id="NCCN-BC-2024",
        citation_url="https://doi.org/10.1016/j.annonc.2024.01.001",
        license=LicenseType.CC_BY,
        anchors=(IdentityAnchor(AnchorType.HGNC, "PIK3CA"),),
    )

    # 1. Staged in pending_confirmation; NOT in active KG yet
    assert staged.status == StagedNodeStatus.PENDING_CONFIRMATION
    assert "staged-med-101" not in med_kg.nodes
    assert len(pipeline.get_pending_nodes()) == 1

    # 2. Curator approves and promotes to active KG
    promoted = pipeline.approve_and_promote(
        staged_id="staged-med-101",
        curator_id="curator-dr-smith",
        notes="Verified against NCCN 2024 Guidelines Update v1",
        snapshot_id="v2024.1",
    )

    assert promoted.node_id == "staged-med-101"
    assert "staged-med-101" in med_kg.nodes
    assert promoted.snapshot_id == "v2024.1"
    assert "Curated by curator-dr-smith" in promoted.caveats[0]

    # Staged status updated to APPROVED
    assert pipeline.get_staged_node("staged-med-101").status == StagedNodeStatus.APPROVED
    assert len(pipeline.get_pending_nodes()) == 0

    # Cannot approve again
    with pytest.raises(CuratorActionError, match="Cannot approve"):
        pipeline.approve_and_promote("staged-med-101", "curator-dr-smith", "duplicate approval")


def test_curator_rejection(test_fabric: GraphFabric) -> None:
    pipeline = CurationPipeline(test_fabric)
    med_kg = test_fabric.get_graph("medical_oncologist_kg")

    pipeline.stage_evidence(
        staged_id="staged-med-flawed",
        role_id="medical_oncologist",
        evidence_class=EvidenceClass.DOCUMENTED,
        claim="Non-standard unapproved monotherapy regimen",
        citation_id="PREPRINT-999",
        citation_url="https://doi.org/10.1016/j.annonc.2024.01.001",
        license=LicenseType.CC_BY,
    )

    rejected = pipeline.reject(
        staged_id="staged-med-flawed",
        curator_id="curator-dr-smith",
        reason="Preprint failed peer review; ungrounded claim",
    )

    assert rejected.status == StagedNodeStatus.REJECTED
    assert "staged-med-flawed" not in med_kg.nodes
    assert len(pipeline.get_pending_nodes()) == 0

    # Rejection requires reason
    pipeline.stage_evidence(
        staged_id="staged-med-no-reason",
        role_id="medical_oncologist",
        evidence_class=EvidenceClass.DOCUMENTED,
        claim="Unverified claim",
        citation_id="PREPRINT-1000",
        citation_url="https://doi.org/10.1016/j.annonc.2024.01.001",
        license=LicenseType.CC_BY,
    )
    with pytest.raises(CuratorActionError, match="explicit reason"):
        pipeline.reject("staged-med-no-reason", "curator-dr-smith", "")


def test_contradiction_preservation_and_edges(test_fabric: GraphFabric) -> None:
    pipeline = CurationPipeline(test_fabric)
    med_kg = test_fabric.get_graph("medical_oncologist_kg")

    # Existing node in medical oncologist KG
    initial_node = GraphNode(
        node_id="med-prior",
        role_provenance="medical_oncologist",
        evidence_class=EvidenceClass.DOCUMENTED,
        claim="Fulvestrant monotherapy standard after CDK4/6 progression",
        citation_id="ASCO-2020",
        citation_url="https://doi.org/10.1016/j.annonc.2020.01.001",
        anchors=(IdentityAnchor(AnchorType.HGNC, "ESR1"),),
    )
    med_kg.add_node(initial_node)

    # Ingesting conflicting new evidence sharing same anchor
    staged = pipeline.stage_evidence(
        staged_id="med-new",
        role_id="medical_oncologist",
        evidence_class=EvidenceClass.DOCUMENTED,
        claim=(
            "Elacestrant preferred over Fulvestrant for ESR1-mutated MBC after CDK4/6 progression"
        ),
        citation_id="EMERALD-Trial-2023",
        citation_url="https://doi.org/10.1016/j.annonc.2023.01.001",
        license=LicenseType.CC_BY,
        anchors=(IdentityAnchor(AnchorType.HGNC, "ESR1"),),
    )

    # Contradiction detected automatically by anchor match
    assert "med-prior" in staged.contradicts_node_ids

    # Promote new node
    pipeline.approve_and_promote(
        staged_id="med-new",
        curator_id="curator-dr-smith",
        notes="New Phase 3 EMERALD trial data supersedes monotherapy standard",
    )

    # Invariant: BOTH nodes must exist, and CONTRADICTS edges must connect them
    assert "med-prior" in med_kg.nodes
    assert "med-new" in med_kg.nodes

    cov = med_kg.coverage()
    assert cov.node_count == 2
    assert cov.contradiction_count == 2  # Bidirectional CONTRADICTS edges


def test_curation_from_subsystem_ad_overrules(test_fabric: GraphFabric) -> None:
    pipeline = CurationPipeline(test_fabric)
    ledger = OverruleLedger()

    overrule = ClinicianOverrule(
        overrule_id="ovr-501",
        session_id="session-501",
        target_type="finding",
        target_id="med-old-regimen",
        role_id="medical_oncologist",
        clinician_id="dr-oncologist",
        action=OverruleAction.OVERRULE_MODIFIED,
        mandatory_reason="Prior anthracycline cardiotoxicity precludes further doxorubicin",
        suggested_alternative="Capecitabine or Trastuzumab deruxtecan depending on HER2 status",
    )
    ledger.record_overrule(overrule)

    curation_items = ledger.get_curation_queue()
    assert len(curation_items) == 1
    item = curation_items[0]

    # Ingest overrule item into curation pipeline
    staged = pipeline.ingest_from_overrule(item, staged_id="staged-from-ovr-501")
    assert staged.staged_id == "staged-from-ovr-501"
    assert staged.role_id == "medical_oncologist"
    assert "Capecitabine or Trastuzumab" in staged.claim
    assert staged.status == StagedNodeStatus.PENDING_CONFIRMATION
    assert staged.license == LicenseType.PUBLIC_DOMAIN
