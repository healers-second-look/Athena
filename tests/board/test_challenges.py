"""Tests for Subsystem X (Structured Challenge & Disagreement Ledger)."""

import pytest

from secondlook.board.challenges import (
    Challenge,
    ChallengeCitationMissingError,
    ChallengeStatus,
    ChallengeType,
    DisagreementLedger,
)


def test_challenge_creation_and_types() -> None:
    # All 5 canonical types supported
    for c_type in ChallengeType:
        ch = Challenge(
            challenge_id=f"ch-{c_type.value}",
            challenger_role="clinical_pharmacologist",
            target_role="medical_oncologist",
            target_finding_id="fnd-1",
            challenge_type=c_type,
            rationale=f"Testing challenge {c_type.value}",
            citation="FDA-Label-2024",
        )
        assert ch.challenge_type == c_type
        assert ch.status == ChallengeStatus.UNRESOLVED


def test_challenge_citation_mandatory() -> None:
    # Missing or empty citation must fail
    with pytest.raises(ChallengeCitationMissingError) as exc_info:
        Challenge(
            challenge_id="ch-fail",
            challenger_role="radiation_oncologist",
            target_role="surgical_oncologist",
            target_finding_id="fnd-2",
            challenge_type=ChallengeType.PRECONDITION,
            rationale="Dose limit violated",
            citation="",  # Empty!
        )
    assert "must carry a citation" in str(exc_info.value)


def test_challenge_self_challenge_forbidden() -> None:
    with pytest.raises(ValueError) as exc_info:
        Challenge(
            challenge_id="ch-self",
            challenger_role="medical_oncologist",
            target_role="medical_oncologist",
            target_finding_id="fnd-3",
            challenge_type=ChallengeType.CONTRADICTION,
            rationale="Contradicting myself",
            citation="ESMO-2024",
        )
    assert "cannot file a challenge against its own finding" in str(exc_info.value)


def test_disagreement_ledger_queries_and_rates() -> None:
    ledger = DisagreementLedger()

    ch1 = Challenge(
        challenge_id="ch-1",
        challenger_role="molecular_pathologist",
        target_role="medical_oncologist",
        target_finding_id="fnd-1",
        challenge_type=ChallengeType.CONTRADICTION,
        rationale="Variant is VUS, not oncogenic driver",
        citation="CIVIC-456",
    )
    ch2 = Challenge(
        challenge_id="ch-2",
        challenger_role="clinical_pharmacologist",
        target_role="medical_oncologist",
        target_finding_id="fnd-1",
        challenge_type=ChallengeType.PRECONDITION,
        rationale="Severe CYP3A4 interaction forecloses combination",
        citation="Lexicomp-2024",
    )
    ch3 = Challenge(
        challenge_id="ch-3",
        challenger_role="molecular_pathologist",
        target_role="radiologist",
        target_finding_id="fnd-2",
        challenge_type=ChallengeType.IDENTITY,
        rationale="Biopsy site mismatch",
        citation="PathReport-123",
        status=ChallengeStatus.UPHELD,
    )

    ledger.add_challenge(ch1)
    ledger.add_challenge(ch2)
    ledger.add_challenge(ch3)

    assert len(ledger.all_challenges()) == 3
    assert len(ledger.get_challenges_for_finding("fnd-1")) == 2
    assert len(ledger.get_challenges_by_challenger("molecular_pathologist")) == 2
    assert len(ledger.get_challenges_by_target_role("medical_oncologist")) == 2

    # Unresolved count
    unresolved = ledger.get_unresolved()
    assert len(unresolved) == 2
    assert set(c.challenge_id for c in unresolved) == {"ch-1", "ch-2"}

    # Challenge rate tracking per lane
    active_seats = [
        "molecular_pathologist",
        "clinical_pharmacologist",
        "radiologist",
        "medical_oncologist",
    ]
    rates = ledger.challenge_rate_per_lane(active_seats)
    assert rates["molecular_pathologist"] == pytest.approx(2 / 3)
    assert rates["clinical_pharmacologist"] == pytest.approx(1 / 3)
    assert rates["radiologist"] == 0.0


def test_disagreement_ledger_serialization_round_trip() -> None:
    ledger = DisagreementLedger()
    ch = Challenge(
        challenge_id="ch-rt",
        challenger_role="radiation_oncologist",
        target_role="surgical_oncologist",
        target_finding_id="fnd-10",
        challenge_type=ChallengeType.PRECONDITION,
        rationale="Prior chest wall radiation precludes re-irradiation margin",
        citation="ASTRO-2023",
        citation_url="https://doi.org/10.1016/j.radonc.2023.01.001",
    )
    ledger.add_challenge(ch)

    serialized = ledger.to_dict()
    restored = DisagreementLedger.from_dict(serialized)

    assert len(restored.all_challenges()) == 1
    restored_ch = restored.all_challenges()[0]
    assert restored_ch.challenge_id == "ch-rt"
    assert restored_ch.challenge_type == ChallengeType.PRECONDITION
    assert restored_ch.citation == "ASTRO-2023"
    assert restored_ch.citation_url == "https://doi.org/10.1016/j.radonc.2023.01.001"
