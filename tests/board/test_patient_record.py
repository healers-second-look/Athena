"""Tests for Subsystem AF (Patient-Readable Board Record)."""

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
from secondlook.board.patient_record import (
    generate_patient_readable_record,
    render_patient_record_html,
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


def _build_fabric() -> GraphFabric:
    fabric = GraphFabric()
    kg_chair = RoleKnowledgeGraph(role_id="chair", graph_id="session_state_kg")
    fabric.register_graph(kg_chair)

    kg_med = RoleKnowledgeGraph(role_id="medical_oncologist", graph_id="medical_oncologist_kg")
    fabric.register_graph(kg_med)

    kg_mol = RoleKnowledgeGraph(
        role_id="molecular_pathologist", graph_id="molecular_pathologist_kg"
    )
    fabric.register_graph(kg_mol)

    kg_pharm = RoleKnowledgeGraph(
        role_id="clinical_pharmacologist", graph_id="clinical_pharmacologist_kg"
    )
    fabric.register_graph(kg_pharm)
    return fabric


def test_generate_patient_readable_record_with_disagreements_and_missing(
    board_charters: list[RoleCharter],
) -> None:
    fabric = _build_fabric()
    kg_med = fabric.get_graph("medical_oncologist_kg")
    kg_med.add_node(
        GraphNode(
            node_id="med-1",
            role_provenance="medical_oncologist",
            evidence_class=EvidenceClass.DOCUMENTED,
            claim="Alpelisib plus Fulvestrant indicated",
            citation_id="NCCN-BC-2024",
            citation_url="https://doi.org/10.1016/j.annonc.2024.01.001",
        )
    )

    def pharm_eval(charter, target_finding, kg):
        return Challenge(
            challenge_id="ch-fpg",
            challenger_role=charter.role_id,
            target_role=target_finding.role_id,
            target_finding_id=target_finding.finding_id,
            challenge_type=ChallengeType.PRECONDITION,
            rationale=(
                "Baseline fasting plasma glucose and HbA1c required to assess hyperglycemia risk"
            ),
            citation="FDA-Piqray-Label",
        )

    record = run_board(
        case={"case_id": "case-pt-001"},
        roles=board_charters,
        fabric=fabric,
        challenge_evaluators={"clinical_pharmacologist": pharm_eval},
    )

    # Attach missing data to record via dataclasses.replace
    import dataclasses

    record = dataclasses.replace(record, missing_data_union=("Fasting plasma glucose",))

    patient_rec = generate_patient_readable_record(record)
    assert patient_rec.case_id == "case-pt-001"
    assert patient_rec.is_complete is True

    # 1. Missing tests surfaced
    assert any(
        "Fasting plasma glucose" in item for item in patient_rec.what_would_change_this_answer
    )

    # 2. Access routes surfaced
    assert len(patient_rec.access_pathways_and_next_steps) > 0

    # 3. Disagreements surfaced honestly
    assert len(patient_rec.open_disagreements) == 1
    d = patient_rec.open_disagreements[0]
    assert d["challenger"] == "Clinical Pharmacologist"
    assert d["target"] == "Medical Oncologist"
    assert "hyperglycemia risk" in d["question_raised"]

    # 4. HTML Rendering
    html_output = render_patient_record_html(patient_rec)
    assert '<article class="athena-patient-record"' in html_output
    assert "Your Tumor Board Review Summary" in html_output
    assert "What Additional Data Would Change This Answer?" in html_output
    assert "Fasting plasma glucose" in html_output
    assert "Clinical Pharmacologist" in html_output
    assert "Medical Oncologist" in html_output


def test_patient_readable_record_full_agreement(
    board_charters: list[RoleCharter],
) -> None:
    fabric = GraphFabric()
    kg_chair = RoleKnowledgeGraph(role_id="chair", graph_id="session_state_kg")
    fabric.register_graph(kg_chair)

    kg_med = RoleKnowledgeGraph(role_id="medical_oncologist", graph_id="medical_oncologist_kg")
    fabric.register_graph(kg_med)

    record = run_board(
        case={"case_id": "case-pt-002"},
        roles=board_charters[:2],
        fabric=fabric,
    )

    patient_rec = generate_patient_readable_record(record)
    assert len(patient_rec.open_disagreements) == 0

    html_output = render_patient_record_html(patient_rec)
    assert "Your team was in full agreement on all evaluated findings." in html_output
