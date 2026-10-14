"""Tests for Subsystem AD (Clinician Feedback & Overrule Capture)."""

import pytest

from secondlook.board.overrule import (
    ClinicianOverrule,
    MissingOverruleReasonError,
    OverruleAction,
    OverruleLedger,
)


def test_clinician_overrule_creation() -> None:
    overrule = ClinicianOverrule(
        overrule_id="ovr-001",
        session_id="session-123",
        target_type="finding",
        target_id="med-1",
        role_id="medical_oncologist",
        clinician_id="dr-house",
        action=OverruleAction.OVERRULE_REJECTED,
        mandatory_reason="Patient has undocumented grade 3 neuropathy contraindicating taxane",
        suggested_alternative="Switch to capecitabine monotherapy",
    )
    assert overrule.overrule_id == "ovr-001"
    assert overrule.session_id == "session-123"
    assert overrule.target_type == "finding"
    assert overrule.action == OverruleAction.OVERRULE_REJECTED
    assert "neuropathy" in overrule.mandatory_reason
    assert overrule.suggested_alternative == "Switch to capecitabine monotherapy"


def test_clinician_overrule_mandatory_reason_enforced() -> None:
    with pytest.raises(MissingOverruleReasonError, match="must provide a mandatory reason"):
        ClinicianOverrule(
            overrule_id="ovr-bad",
            session_id="session-123",
            target_type="finding",
            target_id="med-1",
            role_id="medical_oncologist",
            clinician_id="dr-house",
            action=OverruleAction.OVERRULE_REJECTED,
            mandatory_reason="",  # Empty reason must raise error
        )

    with pytest.raises(MissingOverruleReasonError):
        ClinicianOverrule(
            overrule_id="ovr-bad-ws",
            session_id="session-123",
            target_type="finding",
            target_id="med-1",
            role_id="medical_oncologist",
            clinician_id="dr-house",
            action=OverruleAction.OVERRULE_REJECTED,
            mandatory_reason="   \t\n  ",
        )


def test_overrule_ledger_curation_queue_and_eval_labels() -> None:
    ledger = OverruleLedger()

    o1 = ClinicianOverrule(
        overrule_id="o1",
        session_id="s1",
        target_type="finding",
        target_id="med-1",
        role_id="medical_oncologist",
        clinician_id="c1",
        action=OverruleAction.OVERRULE_REJECTED,
        mandatory_reason="Missing consideration of prior doxorubicin cumulative dose",
        suggested_alternative="Consider non-anthracycline regimen",
    )
    o2 = ClinicianOverrule(
        overrule_id="o2",
        session_id="s1",
        target_type="finding",
        target_id="med-2",
        role_id="medical_oncologist",
        clinician_id="c1",
        action=OverruleAction.OVERRULE_AFFIRMED,
        mandatory_reason="Affirmed in accord with clinical presentation",
    )
    o3 = ClinicianOverrule(
        overrule_id="o3",
        session_id="s2",
        target_type="challenge",
        target_id="ch-1",
        role_id="clinical_pharmacologist",
        clinician_id="c2",
        action=OverruleAction.OVERRULE_MODIFIED,
        mandatory_reason="Dose reduction necessary instead of complete discontinuation",
    )

    ledger.record_overrule(o1)
    ledger.record_overrule(o2)
    ledger.record_overrule(o3)

    assert len(ledger.all_overrules()) == 3
    assert len(ledger.get_for_session("s1")) == 2
    assert len(ledger.get_for_session("s2")) == 1

    # Curation queue extracts rejected & modified for Subsystem V
    queue = ledger.get_curation_queue()
    assert len(queue) == 2
    assert queue[0]["target_id"] == "med-1"
    assert queue[1]["target_id"] == "ch-1"

    # Eval labels for Subsystem Z
    labels = ledger.export_eval_labels()
    assert len(labels) == 3
    assert labels[0]["action"] == "overrule_rejected"
    assert labels[1]["action"] == "overrule_affirmed"
    assert labels[2]["action"] == "overrule_modified"
