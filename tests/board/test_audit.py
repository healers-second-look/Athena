"""Tests for Subsystem AB (Replay, Trace & Audit Store)."""

from pathlib import Path

import pytest

from secondlook.board.audit import (
    AuditStore,
    diff_board_records,
    export_deidentified_record,
)
from secondlook.board.charters import RoleCharter, load_all_charters
from secondlook.board.fabric import (
    AnchorType,
    EvidenceClass,
    GraphFabric,
    GraphNode,
    IdentityAnchor,
    RoleKnowledgeGraph,
)
from secondlook.board.orchestrator import BoardRecord, run_board


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
def sample_board_record(board_charters: list[RoleCharter]) -> BoardRecord:
    fabric = GraphFabric()
    kg_chair = RoleKnowledgeGraph(role_id="chair", graph_id="session_state_kg")
    fabric.register_graph(kg_chair)

    kg_med = RoleKnowledgeGraph(role_id="medical_oncologist", graph_id="medical_oncologist_kg")
    kg_med.add_node(
        GraphNode(
            node_id="med-1",
            role_provenance="medical_oncologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="Fulvestrant plus Alpelisib indicated",
            citation_id="NCCN-BC-2024",
            citation_url="https://doi.org/10.1016/j.annonc.2024.01.001",
            anchors=(IdentityAnchor(AnchorType.HGNC, "PIK3CA"),),
        )
    )
    fabric.register_graph(kg_med)

    return run_board(
        case={"case_id": "case-audit-100"},
        roles=board_charters[:2],
        fabric=fabric,
    )


def test_diff_board_records_identical(sample_board_record: BoardRecord) -> None:
    diff = diff_board_records(sample_board_record, sample_board_record)
    assert diff.case_id == sample_board_record.case_id
    assert not diff.has_changes
    assert len(diff.added_findings) == 0
    assert len(diff.removed_findings) == 0
    assert len(diff.new_challenges) == 0


def test_diff_board_records_detects_changes(
    board_charters: list[RoleCharter],
    sample_board_record: BoardRecord,
) -> None:
    fabric_b = GraphFabric()
    kg_chair = RoleKnowledgeGraph(role_id="chair", graph_id="session_state_kg")
    fabric_b.register_graph(kg_chair)

    kg_med = RoleKnowledgeGraph(role_id="medical_oncologist", graph_id="medical_oncologist_kg")
    kg_med.add_node(
        GraphNode(
            node_id="med-2",
            role_provenance="medical_oncologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="Capivasertib plus Fulvestrant indicated for AKT1 mutation",
            citation_id="NCCN-BC-2024",
            citation_url="https://doi.org/10.1016/j.annonc.2024.01.001",
            anchors=(IdentityAnchor(AnchorType.HGNC, "AKT1"),),
        )
    )
    fabric_b.register_graph(kg_med)

    record_b = run_board(
        case={"case_id": "case-audit-100"},
        roles=board_charters[:2],
        fabric=fabric_b,
    )

    diff = diff_board_records(sample_board_record, record_b)
    assert diff.has_changes is True
    assert len(diff.added_findings) == 1
    assert diff.added_findings[0].finding_id == "fnd-med-2"
    assert len(diff.removed_findings) == 1
    assert diff.removed_findings[0].finding_id == "fnd-med-1"


def test_export_deidentified_record(sample_board_record: BoardRecord) -> None:
    deidentified = export_deidentified_record(sample_board_record)
    assert deidentified["deidentified_session_id"].startswith("audit-")
    assert deidentified["deidentified_case_id"].startswith("case-deidentified-")
    assert "case-audit-100" not in deidentified["deidentified_case_id"]
    assert deidentified["quorum_verified"] is True
    assert len(deidentified["findings"]) == 1
    f = deidentified["findings"][0]
    assert f["finding_id"] == "fnd-med-1"
    assert f["role_id"] == "medical_oncologist"
    assert f["anchors"] == ["HGNC:PIK3CA"]


def test_audit_store_crud_and_diff(sample_board_record: BoardRecord) -> None:
    store = AuditStore()
    store.store_record(sample_board_record)

    retrieved = store.get_record(sample_board_record.session_id)
    assert retrieved.session_id == sample_board_record.session_id

    case_records = store.list_records_for_case("case-audit-100")
    assert len(case_records) == 1
    assert case_records[0].session_id == sample_board_record.session_id

    with pytest.raises(KeyError):
        store.get_record("nonexistent-session")

    diff = store.compute_diff(sample_board_record.session_id, sample_board_record.session_id)
    assert diff.has_changes is False
