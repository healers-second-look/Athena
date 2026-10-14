"""Tests for Subsystem Z (Role Evaluation Suite)."""

import dataclasses
from pathlib import Path

import pytest

from secondlook.board.charters import RoleCharter, load_all_charters
from secondlook.board.evaluation import (
    ReleaseSafetyBlockError,
    RoleEvaluationSuite,
    ThresholdRule,
)
from secondlook.board.fabric import (
    AnchorType,
    EvidenceClass,
    GraphFabric,
    GraphNode,
    IdentityAnchor,
    RoleKnowledgeGraph,
)
from secondlook.board.harness import ClaimKind, Finding
from secondlook.board.orchestrator import run_board


@pytest.fixture
def board_charters() -> list[RoleCharter]:
    charters_dir = Path(__file__).resolve().parent.parent.parent / "charters"
    all_c = load_all_charters(charters_dir)
    return [
        all_c["chair"],
        all_c["medical_oncologist"],
        all_c["molecular_pathologist"],
    ]


def test_threshold_rule_comparators() -> None:
    eq_rule = ThresholdRule("metric", 0.0, "==")
    assert eq_rule.check(0.0) is True
    assert eq_rule.check(0.1) is False

    gte_rule = ThresholdRule("metric", 0.90, ">=")
    assert gte_rule.check(0.95) is True
    assert gte_rule.check(0.90) is True
    assert gte_rule.check(0.85) is False

    lte_rule = ThresholdRule("metric", 5.0, "<=")
    assert lte_rule.check(5.0) is True
    assert lte_rule.check(6.0) is False

    gt_rule = ThresholdRule("metric", 0.0, ">")
    assert gt_rule.check(1.0) is True
    assert gt_rule.check(0.0) is False

    lt_rule = ThresholdRule("metric", 10.0, "<")
    assert lt_rule.check(9.0) is True
    assert lt_rule.check(10.0) is False

    with pytest.raises(ValueError, match="Unknown comparator"):
        ThresholdRule("metric", 1.0, "invalid").check(1.0)


def test_role_evaluation_suite_passes_clean_session(
    board_charters: list[RoleCharter],
) -> None:
    fabric = GraphFabric()
    kg_chair = RoleKnowledgeGraph(role_id="chair", graph_id="session_state_kg")
    fabric.register_graph(kg_chair)

    kg_med = RoleKnowledgeGraph(role_id="medical_oncologist", graph_id="medical_oncologist_kg")
    kg_med.add_node(
        GraphNode(
            node_id="med-1",
            role_provenance="medical_oncologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="Endocrine therapy plus CDK4/6 inhibitor indicated",
            citation_id="NCCN-BC-2024",
            citation_url="https://doi.org/10.1016/j.annonc.2024.01.001",
            anchors=(IdentityAnchor(AnchorType.HGNC, "ESR1"),),
        )
    )
    fabric.register_graph(kg_med)

    kg_mol = RoleKnowledgeGraph(
        role_id="molecular_pathologist", graph_id="molecular_pathologist_kg"
    )
    fabric.register_graph(kg_mol)

    record = run_board(
        case={"case_id": "case-eval-001"},
        roles=board_charters,
        fabric=fabric,
    )

    suite = RoleEvaluationSuite()
    report = suite.evaluate_role(board_charters[1], record)

    assert report.role_id == "medical_oncologist"
    assert report.jurisdiction_violation_rate == 0.0
    assert report.grounded_ratio == 1.0
    assert report.passed_safety_gate is True
    # Should not raise
    report.assert_safety_gate()


def test_role_evaluation_blocks_on_jurisdiction_violation(
    board_charters: list[RoleCharter],
) -> None:
    fabric = GraphFabric()
    kg_chair = RoleKnowledgeGraph(role_id="chair", graph_id="session_state_kg")
    fabric.register_graph(kg_chair)

    kg_med = RoleKnowledgeGraph(role_id="medical_oncologist", graph_id="medical_oncologist_kg")
    fabric.register_graph(kg_med)

    kg_mol = RoleKnowledgeGraph(
        role_id="molecular_pathologist", graph_id="molecular_pathologist_kg"
    )
    fabric.register_graph(kg_mol)

    record = run_board(
        case={"case_id": "case-eval-002"},
        roles=board_charters,
        fabric=fabric,
    )

    # Inject an out-of-jurisdiction claim into medical_oncologist findings
    bad_finding = Finding(
        finding_id="fnd-bad",
        role_id="medical_oncologist",
        claim_kind=ClaimKind.MOLECULAR_VARIANT_INTERPRETATION,  # Reserved for molecular pathologist
        statement="Unauthorized molecular variant interpretation",
        evidence_class=EvidenceClass.DOCUMENTED,
        citations=("NCCN-BC-2024",),
        citation_urls=("https://doi.org/10.1016/j.annonc.2024.01.001",),
    )
    record_with_violation = dataclasses.replace(
        record,
        findings_by_lane={"medical_oncologist": (bad_finding,)},
        all_findings=(bad_finding,),
    )

    suite = RoleEvaluationSuite()
    report = suite.evaluate_role(board_charters[1], record_with_violation)

    assert report.jurisdiction_violations == 1
    assert report.jurisdiction_violation_rate > 0.0
    assert report.passed_safety_gate is False

    with pytest.raises(ReleaseSafetyBlockError, match="failed pre-committed safety gate"):
        report.assert_safety_gate()


def test_evaluate_board_evaluates_all_non_chair_roles(
    board_charters: list[RoleCharter],
) -> None:
    fabric = GraphFabric()
    kg_chair = RoleKnowledgeGraph(role_id="chair", graph_id="session_state_kg")
    fabric.register_graph(kg_chair)

    kg_med = RoleKnowledgeGraph(role_id="medical_oncologist", graph_id="medical_oncologist_kg")
    fabric.register_graph(kg_med)

    kg_mol = RoleKnowledgeGraph(
        role_id="molecular_pathologist", graph_id="molecular_pathologist_kg"
    )
    fabric.register_graph(kg_mol)

    record = run_board(
        case={"case_id": "case-eval-003"},
        roles=board_charters,
        fabric=fabric,
    )

    suite = RoleEvaluationSuite()
    cards = suite.evaluate_board(board_charters, record)
    assert "chair" not in cards
    assert "medical_oncologist" in cards
    assert "molecular_pathologist" in cards
