"""Tests for Subsystem AA (Adversarial & Sycophancy Red-Team Corpus)."""

import dataclasses
from pathlib import Path

import pytest

from secondlook.board.challenges import (
    Challenge,
    ChallengeType,
)
from secondlook.board.charters import RoleCharter, load_all_charters
from secondlook.board.fabric import (
    EvidenceClass,
    GraphFabric,
    GraphNode,
    RoleKnowledgeGraph,
)
from secondlook.board.orchestrator import run_board
from secondlook.board.redteam import (
    VERSIONED_REDTEAM_CORPUS,
    RedTeamHarness,
    RedTeamRegressionError,
)


@pytest.fixture
def board_charters() -> list[RoleCharter]:
    charters_dir = Path(__file__).resolve().parent.parent.parent / "charters"
    all_c = load_all_charters(charters_dir)
    return [
        all_c["chair"],
        all_c["medical_oncologist"],
        all_c["clinical_pharmacologist"],
    ]


def _build_fabric() -> GraphFabric:
    fabric = GraphFabric()
    kg_chair = RoleKnowledgeGraph(role_id="chair", graph_id="session_state_kg")
    fabric.register_graph(kg_chair)

    kg_med = RoleKnowledgeGraph(role_id="medical_oncologist", graph_id="medical_oncologist_kg")
    fabric.register_graph(kg_med)

    kg_pharm = RoleKnowledgeGraph(
        role_id="clinical_pharmacologist", graph_id="clinical_pharmacologist_kg"
    )
    fabric.register_graph(kg_pharm)
    return fabric


def test_redteam_corpus_has_all_named_traps() -> None:
    trap_names = {t.trap_name for t in VERSIONED_REDTEAM_CORPUS}
    expected = {
        "consensus_trap",
        "jurisdiction_overreach_trap",
        "missing_staging_trap",
        "stale_guideline_trap",
    }
    assert expected.issubset(trap_names)


def test_consensus_trap_passes_when_contradiction_filed(
    board_charters: list[RoleCharter],
) -> None:
    fabric = _build_fabric()
    kg_med = fabric.get_graph("medical_oncologist_kg")
    kg_med.add_node(
        GraphNode(
            node_id="med-1",
            role_provenance="medical_oncologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="High-dose chemotherapy indicated without biomarkers",
            citation_id="NCCN-2024",
            citation_url="https://doi.org/10.1016/j.annonc.2024.01.001",
        )
    )

    def challenge_eval(charter, target_finding, kg):
        return Challenge(
            challenge_id="ch-contra",
            challenger_role=charter.role_id,
            target_role=target_finding.role_id,
            target_finding_id=target_finding.finding_id,
            challenge_type=ChallengeType.CONTRADICTION,
            rationale="Contraindicated due to lack of biomarker confirmation",
            citation="NCCN-2024",
        )

    record = run_board(
        case={"case_id": "case-redteam-001"},
        roles=board_charters,
        fabric=fabric,
        challenge_evaluators={"clinical_pharmacologist": challenge_eval},
    )

    harness = RedTeamHarness()
    passed, reason = harness.evaluate_board_record("consensus_trap", record)
    assert passed is True
    assert "resisted consensus trap" in reason
    harness.assert_trap_passed("consensus_trap", record)


def test_consensus_trap_fails_when_no_contradiction_filed(
    board_charters: list[RoleCharter],
) -> None:
    fabric = _build_fabric()
    record = run_board(
        case={"case_id": "case-redteam-002"},
        roles=board_charters,
        fabric=fabric,
    )

    harness = RedTeamHarness()
    passed, reason = harness.evaluate_board_record("consensus_trap", record)
    assert passed is False
    assert "succumbed to consensus trap" in reason

    with pytest.raises(RedTeamRegressionError, match="P0 Red-Team Regression"):
        harness.assert_trap_passed("consensus_trap", record)


def test_missing_staging_trap_eval(board_charters: list[RoleCharter]) -> None:
    fabric = _build_fabric()
    # Clean record with no missing staging audited
    record_fail = run_board(
        case={"case_id": "case-redteam-003"},
        roles=board_charters,
        fabric=fabric,
    )
    harness = RedTeamHarness()
    passed, _ = harness.evaluate_board_record("missing_staging_trap", record_fail)
    assert passed is False

    # Simulate missing staging recorded in missing_data_union via dataclasses.replace
    record_pass = dataclasses.replace(
        record_fail,
        missing_data_union=("Clinical TNM staging pending",),
    )
    passed_ok, reason_ok = harness.evaluate_board_record("missing_staging_trap", record_pass)
    assert passed_ok is True


def test_stale_guideline_trap_eval(board_charters: list[RoleCharter]) -> None:
    fabric = _build_fabric()
    record = run_board(
        case={"case_id": "case-redteam-004"},
        roles=board_charters,
        fabric=fabric,
    )
    harness = RedTeamHarness()
    passed, _ = harness.evaluate_board_record("stale_guideline_trap", record)
    assert passed is False

    # Add staleness challenge to ledger
    record.disagreement_ledger.add_challenge(
        Challenge(
            challenge_id="ch-stale-01",
            challenger_role="medical_oncologist",
            target_role="clinical_pharmacologist",
            target_finding_id="f-old",
            challenge_type=ChallengeType.STALENESS,
            rationale="Guideline superseded by ASCO 2024 update",
            citation="ASCO-2024",
        )
    )
    passed_ok, _ = harness.evaluate_board_record("stale_guideline_trap", record)
    assert passed_ok is True


def test_harness_unknown_trap(board_charters: list[RoleCharter]) -> None:
    fabric = GraphFabric()
    kg_chair = RoleKnowledgeGraph(role_id="chair", graph_id="session_state_kg")
    fabric.register_graph(kg_chair)
    record = run_board(case={"case_id": "c1"}, roles=board_charters[:1], fabric=fabric)

    harness = RedTeamHarness()
    with pytest.raises(KeyError, match="No red-team trap named"):
        harness.evaluate_board_record("nonexistent_trap", record)
