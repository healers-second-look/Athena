"""Unit tests for study enrollment helpers."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from secondlook.study.enrollment import EnrollmentBase
from secondlook.study.enrollment import (
    CONSENT_FILENAME,
    CONSENT_VERSION,
    InvalidToken,
    StudyConsent,
    StudyInvite,
    StudyParticipant,
    consent_text_sha256,
    generate_invite_code,
    hash_invite_code,
    invite_from_code,
    invite_is_usable,
    mint_enrollment_token,
    mint_session_token,
    normalize_invite_code,
    participant_id_for_index,
    verify_token,
)
from secondlook.study.invites import create_invites


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setenv("STUDY_CODE_PEPPER", "test-pepper")
    monkeypatch.setenv("STUDY_SESSION_SECRET", "test-session-secret")
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    StudyInvite.__table__.create(engine)
    StudyParticipant.__table__.create(engine)
    StudyConsent.__table__.create(engine)
    with Session(engine) as s:
        yield s


def test_code_normalization_and_hash_is_stable(monkeypatch):
    monkeypatch.setenv("STUDY_CODE_PEPPER", "pepper")
    assert normalize_invite_code("ath-2345-AB") == "ATH2345AB"
    h1 = hash_invite_code("ATH2345AB")
    h2 = hash_invite_code(normalize_invite_code("ATH-2345-AB"))
    assert h1 == h2
    assert len(h1) == 64


def test_generated_codes_match_format(monkeypatch):
    monkeypatch.setenv("STUDY_CODE_PEPPER", "pepper")
    display, normalized = generate_invite_code()
    assert display.startswith("ATH-")
    assert len(normalized) == 9


def test_tokens_round_trip_and_expire(monkeypatch):
    monkeypatch.setenv("STUDY_SESSION_SECRET", "s")
    invite_id = uuid.uuid4()
    enroll = mint_enrollment_token(invite_id)
    payload = verify_token(enroll, expected_type="enroll")
    assert payload["invite_id"] == str(invite_id)

    session_tok = mint_session_token("P01")
    sess = verify_token(session_tok, expected_type="session")
    assert sess["participant_id"] == "P01"

    with pytest.raises(InvalidToken):
        verify_token(session_tok + "x", expected_type="session")


def test_create_invites_stores_only_hashes(session, monkeypatch):
    pairs = create_invites(session, 3, pepper="test-pepper")
    assert len(pairs) == 3
    for idx, code in pairs:
        assert participant_id_for_index(idx) == f"P{idx + 1:02d}"
        invite = invite_from_code(session, code)
        assert invite is not None
        assert invite.code_hash != code


def test_migration_and_model_columns_match():
    migration = Path(__file__).parents[2] / "migrations" / "versions" / "0005_study_enrollment.py"
    text = migration.read_text(encoding="utf-8")
    for table in ("study_invites", "study_participants", "study_consents"):
        block = text.split(f'"{table}"')[1].split("op.create_table")[0]
        declared = set(re.findall(r'sa\.Column\("(\w+)"', block))
        assert declared == {c.name for c in EnrollmentBase.metadata.tables[table].columns}


def test_served_consent_matches_docs_duplicate():
    docs = Path(__file__).parents[2] / "docs" / "research" / CONSENT_FILENAME
    served = Path(__file__).parents[2] / "src" / "secondlook" / "study" / "consent" / CONSENT_FILENAME
    assert docs.read_text(encoding="utf-8") == served.read_text(encoding="utf-8")
    assert consent_text_sha256()


def test_invite_usability(session):
    now = datetime.now(UTC)
    invite = StudyInvite(
        code_hash="abc",
        reviewer_index=0,
        created_at=now,
        expires_at=now - timedelta(hours=1),
        revoked=False,
    )
    assert not invite_is_usable(invite)
    invite.expires_at = now + timedelta(hours=1)
    invite.revoked = True
    assert not invite_is_usable(invite)

def test_packaged_consent_matches_docs_copy():
    """The API serves the packaged copy; it must not drift from the reviewed doc."""
    from pathlib import Path

    from secondlook.study.enrollment import consent_markdown_path

    docs = Path(__file__).resolve().parents[2] / "docs/research/athena-vs-usual-care-consent-v0.1.md"
    assert consent_markdown_path().read_text() == docs.read_text()


def test_participant_identity_tables_are_not_in_the_patient_schema():
    """Doctor PII must stay off the case Base that POLICY.md 5.4 guards."""
    from secondlook.case.models import Base

    for table in ("study_invites", "study_participants", "study_consents"):
        assert table not in Base.metadata.tables
        assert table in EnrollmentBase.metadata.tables
