"""Tests for Subsystem W (Board Session Orchestrator)."""

import dataclasses
from pathlib import Path

import pytest

from secondlook.board.challenges import (
    Challenge,
    ChallengeType,
)
from secondlook.board.charters import (
    RoleCharter,
    load_all_charters,
)
from secondlook.board.fabric import (
    AnchorType,
    EvidenceClass,
    GraphFabric,
    GraphNode,
    IdentityAnchor,
    RoleKnowledgeGraph,
)
from secondlook.board.orchestrator import (
    ChairModelCallForbiddenError,
    run_board,
)


@pytest.fixture
def board_charters() -> list[RoleCharter]:
    charters_dir = Path(__file__).resolve().parent.parent.parent / "charters"
    all_c = load_all_charters(charters_dir)
    return [
        all_c["chair"],
        all_c["medical_oncologist"],
        all_c["molecular_pathologist"],
        all_c["clinical_pharmacologist"],
    ]


@pytest.fixture
def board_fabric() -> GraphFabric:
    fabric = GraphFabric()

    # Chair session state KG
    kg_chair = RoleKnowledgeGraph(role_id="chair", graph_id="session_state_kg")
    fabric.register_graph(kg_chair)

    # Medical Oncologist KG
    kg_med = RoleKnowledgeGraph(role_id="medical_oncologist", graph_id="medical_oncologist_kg")
    kg_med.add_node(
        GraphNode(
            node_id="med-1",
            role_provenance="medical_oncologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim=(
                "Fulvestrant plus Alpelisib indicated for PIK3CA-mutated "
                "HR+/HER2- metastatic breast cancer"
            ),
            citation_id="NCCN-BC-2024",
            citation_url="https://doi.org/10.1016/j.annonc.2024.01.001",
            anchors=(
                IdentityAnchor(AnchorType.HGNC, "PIK3CA"),
                IdentityAnchor(AnchorType.RXNORM, "ALPELISIB"),
            ),
        )
    )
    fabric.register_graph(kg_med)

    # Molecular Pathologist KG
    kg_mol = RoleKnowledgeGraph(
        role_id="molecular_pathologist", graph_id="molecular_pathologist_kg"
    )
    kg_mol.add_node(
        GraphNode(
            node_id="mol-1",
            role_provenance="molecular_pathologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="PIK3CA H1047R detected at 28% VAF in cfDNA",
            citation_id="NGS-Report-441",
            citation_url="https://civicdb.org/variants/441",
            anchors=(IdentityAnchor(AnchorType.HGNC, "PIK3CA"),),
        )
    )
    fabric.register_graph(kg_mol)

    # Clinical Pharmacology KG
    kg_pharm = RoleKnowledgeGraph(
        role_id="clinical_pharmacologist", graph_id="clinical_pharmacologist_kg"
    )
    kg_pharm.add_node(
        GraphNode(
            node_id="pharm-1",
            role_provenance="clinical_pharmacologist",
            evidence_class=EvidenceClass.REGULATORY,
            claim=(
                "Severe hyperglycemia risk: fasting glucose > 160 mg/dL is a relative "
                "contraindication to Alpelisib"
            ),
            citation_id="FDA-Label-Piqray",
            anchors=(IdentityAnchor(AnchorType.RXNORM, "ALPELISIB"),),
        )
    )
    fabric.register_graph(kg_pharm)

    return fabric


def test_orchestrator_runs_5_rounds_successfully(
    board_charters: list[RoleCharter],
    board_fabric: GraphFabric,
) -> None:
    # Custom challenge evaluator simulating cross-lane constraint (precondition challenge)
    def pharm_challenge_evaluator(charter, target_finding, kg):
        if "Alpelisib" in target_finding.statement:
            return Challenge(
                challenge_id="ch-pharm-alpelisib",
                challenger_role=charter.role_id,
                target_role=target_finding.role_id,
                target_finding_id=target_finding.finding_id,
                challenge_type=ChallengeType.PRECONDITION,
                rationale=(
                    "Fasting plasma glucose baseline must be evaluated "
                    "prior to Alpelisib initiation"
                ),
                citation="FDA-Label-Piqray",
            )
        return None

    evaluators = {"clinical_pharmacologist": pharm_challenge_evaluator}

    record = run_board(
        case={"case_id": "case-test-404"},
        roles=board_charters,
        fabric=board_fabric,
        challenge_evaluators=evaluators,
    )

    # Verification of Round 4 deterministic assembly
    assert record.case_id == "case-test-404"
    assert record.quorum_verified is True
    assert len(record.roles) == 4

    # Findings partitioned by lane
    assert "medical_oncologist" in record.findings_by_lane
    assert "molecular_pathologist" in record.findings_by_lane
    assert "clinical_pharmacologist" in record.findings_by_lane
    assert len(record.all_findings) == 3

    # Challenge verified in DisagreementLedger
    challenges = record.disagreement_ledger.all_challenges()
    assert len(challenges) == 1
    ch = challenges[0]
    assert ch.challenger_role == "clinical_pharmacologist"
    assert ch.target_role == "medical_oncologist"
    assert ch.challenge_type == ChallengeType.PRECONDITION

    # Per-lane coverage computed
    assert "medical_oncologist" in record.lane_coverages
    assert record.lane_coverages["medical_oncologist"].node_count == 1
    assert record.lane_coverages["molecular_pathologist"].node_count == 1


def test_chair_must_be_deterministic(
    board_charters: list[RoleCharter],
    board_fabric: GraphFabric,
) -> None:
    chair_charter = next(r for r in board_charters if r.role_id == "chair")
    non_deterministic_chair = dataclasses.replace(chair_charter, is_deterministic=False)

    with pytest.raises(ChairModelCallForbiddenError):
        run_board(
            case={"case_id": "case-bad-chair"},
            roles=[non_deterministic_chair],
            fabric=board_fabric,
        )
