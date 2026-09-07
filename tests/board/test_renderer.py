"""Tests for Subsystem AC (Board Record Renderer)."""

from datetime import UTC, datetime

import pytest

from secondlook.board.challenges import (
    Challenge,
    ChallengeType,
    DisagreementLedger,
)
from secondlook.board.charters import ClaimKind
from secondlook.board.fabric import (
    AnchorType,
    EvidenceClass,
    IdentityAnchor,
    LaneCoverage,
)
from secondlook.board.harness import (
    Finding,
    SessionTrace,
)
from secondlook.board.orchestrator import BoardRecord
from secondlook.board.renderer import (
    DisagreementLedgerHiddenError,
    render_board_record,
)
from secondlook.pipeline import DISCLAIMER as COMPUTED_SIGNAL_DISCLAIMER


@pytest.fixture
def sample_board_record() -> BoardRecord:
    finding_med = Finding(
        finding_id="fnd-med-1",
        role_id="medical_oncologist",
        claim_kind=ClaimKind.SYSTEMIC_THERAPY_OPTION,
        statement="Initiate Elacestrant monotherapy",
        evidence_class=EvidenceClass.DOCUMENTED,
        anchors=(IdentityAnchor(AnchorType.HGNC, "ESR1"),),
        citations=("EMERALD-Trial-2022",),
        citation_urls=("https://doi.org/10.1200/JCO.22.00338",),
    )

    finding_mol_computed = Finding(
        finding_id="fnd-mol-comp",
        role_id="molecular_pathologist",
        claim_kind=ClaimKind.ACTIONABILITY_CLASS,
        statement="mCSM-lig binding affinity shift: -1.82 kcal/mol",
        evidence_class=EvidenceClass.COMPUTED,  # Must carry disclaimer
        anchors=(IdentityAnchor(AnchorType.HGNC, "ESR1"),),
    )

    ch = Challenge(
        challenge_id="ch-render-1",
        challenger_role="molecular_pathologist",
        target_role="medical_oncologist",
        target_finding_id="fnd-med-1",
        challenge_type=ChallengeType.PRECONDITION,
        rationale="ESR1 Y537S mutation status not confirmed on plasma cfDNA",
        citation="ASCO-Guidelines-2023",
        citation_url="https://doi.org/10.1200/JCO.2023.1",
    )

    ledger = DisagreementLedger([ch])

    coverage = LaneCoverage(
        role_id="medical_oncologist",
        snapshot_id="snapshot-v1",
        node_count=5,
        edge_count=2,
        citation_density=0.8,
        contradiction_count=0,
        anchored_entity_count=3,
        graph_id="medical_oncology_kg",
        role_provenance="medical_oncologist",
        anchor_density=0.6,
        is_degraded=False,
    )

    return BoardRecord(
        session_id="board-test-session",
        case_id="case-breast-771",
        timestamp=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        roles=("medical_oncologist", "molecular_pathologist"),
        findings_by_lane={
            "medical_oncologist": (finding_med,),
            "molecular_pathologist": (finding_mol_computed,),
        },
        all_findings=(finding_med, finding_mol_computed),
        disagreement_ledger=ledger,
        missing_data_union=("Plasma cfDNA ESR1 assay report",),
        abstention_audit={},
        lane_coverages={"medical_oncologist": coverage},
        trace=SessionTrace(session_id="trace-test"),
        quorum_verified=True,
    )


def test_renderer_refuses_to_hide_disagreements(sample_board_record: BoardRecord) -> None:
    # HARD INVARIANT: Refuses any request that attempts to hide the disagreement ledger
    with pytest.raises(DisagreementLedgerHiddenError) as exc_info:
        render_board_record(sample_board_record, hide_disagreements=True)
    assert "strictly forbidden" in str(exc_info.value)


def test_renderer_text_format(sample_board_record: BoardRecord) -> None:
    rendered = render_board_record(sample_board_record, format="text")

    # Header & metadata
    assert "Athena Tumor Board Record — Session board-test-session" in rendered
    assert "Case ID: case-breast-771" in rendered

    # Lane coverage visible
    assert "[medical_oncologist] HEALTHY" in rendered

    # Missing data audit
    assert "Plasma cfDNA ESR1 assay report" in rendered

    # Findings and clickable citations
    assert "Initiate Elacestrant monotherapy" in rendered
    assert "[EMERALD-Trial-2022](https://doi.org/10.1200/JCO.22.00338)" in rendered

    # Verbatim computed signal disclaimer present
    assert COMPUTED_SIGNAL_DISCLAIMER in rendered

    # Inline challenge present under target
    assert "[PRECONDITION] from molecular_pathologist" in rendered
    assert "ESR1 Y537S mutation status not confirmed" in rendered

    # Verbatim disagreement ledger section
    assert "## Disagreement Ledger (Full Verbatim Record)" in rendered
    assert "Challenge ch-render-1" in rendered


def test_renderer_html_format(sample_board_record: BoardRecord) -> None:
    rendered = render_board_record(sample_board_record, format="html")

    assert '<div class="athena-board-record"' in rendered
    assert 'data-role="medical_oncologist"' in rendered
    assert '<a href="https://doi.org/10.1200/JCO.22.00338"' in rendered
    assert COMPUTED_SIGNAL_DISCLAIMER in rendered
    assert 'class="inline-challenges"' in rendered
    assert 'class="challenge challenge-precondition"' in rendered
    assert 'class="disagreement-ledger"' in rendered
