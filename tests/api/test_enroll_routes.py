"""API tests for study enrollment."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from secondlook.api.app import create_app
from secondlook.api.deps import get_session
from secondlook.study.cases import DEFAULT_CASE_SET_DIR
from secondlook.study.enrollment import (
    CONSENT_VERSION,
    GENERIC_CODE_ERROR,
    GENERIC_RESUME_ERROR,
    StudyConsent,
    StudyInvite,
    StudyParticipant,
    consent_text_sha256,
    hash_invite_code,
    normalize_invite_code,
    reset_rate_limits,
)
from secondlook.study.events import StudyEvent
from secondlook.study.invites import create_invites

API_KEY = "test-key"
PEPPER = "route-test-pepper"
SECRET = "route-test-secret"
PROFILE = {
    "full_name": "Dr Pat Example",
    "email": "pat@example.org",
    "phone": None,
    "registration_number": "REG-1",
    "specialty": "medical_oncology",
    "years_in_oncology": 8,
    "institution": "Example Institute",
    "has_uptodate": True,
    "has_nccn": True,
    "ai_familiarity": 3,
}


def _answers(*, recording: bool = False) -> dict[str, bool]:
    return {
        "read_understood": True,
        "voluntary_withdraw": True,
        "synthetic_not_advice": True,
        "data_use": True,
        "screen_recording": recording,
    }


def _make_client(monkeypatch, *, require_enrollment: bool = True):
    monkeypatch.setenv("ATHENA_API_KEY", API_KEY)
    monkeypatch.delenv("ATHENA_API_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("ATHENA_STUDY_ENABLED", "true")
    monkeypatch.setenv("ATHENA_STUDY_ALLOW_UNREVIEWED", "true")
    if not (os.environ.get("ATHENA_STUDY_CASE_SET") or "").strip():
        monkeypatch.setenv(
            "ATHENA_STUDY_CASE_SET", str(DEFAULT_CASE_SET_DIR / "athena_vs_usual_v1.yaml")
        )
    monkeypatch.setenv("STUDY_CODE_PEPPER", PEPPER)
    monkeypatch.setenv("STUDY_SESSION_SECRET", SECRET)
    if require_enrollment:
        monkeypatch.setenv("STUDY_REQUIRE_ENROLLMENT", "true")
    else:
        monkeypatch.delenv("STUDY_REQUIRE_ENROLLMENT", raising=False)

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    StudyEvent.__table__.create(engine)
    StudyInvite.__table__.create(engine)
    StudyParticipant.__table__.create(engine)
    StudyConsent.__table__.create(engine)
    app = create_app()

    def _session():
        session = Session(engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_session] = _session
    return TestClient(app), engine


@pytest.fixture(autouse=True)
def _reset_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def enroll_bundle(monkeypatch):
    return _make_client(monkeypatch)


@pytest.fixture
def client(enroll_bundle):
    return enroll_bundle[0]


@pytest.fixture
def db_engine(enroll_bundle):
    return enroll_bundle[1]


def _seed_code(engine, code: str, reviewer_index: int = 0, **kwargs) -> None:
    normalized = normalize_invite_code(code)
    with Session(engine) as s:
        s.add(
            StudyInvite(
                code_hash=hash_invite_code(normalized, pepper=PEPPER),
                reviewer_index=reviewer_index,
                created_at=datetime.now(UTC),
                revoked=kwargs.get("revoked", False),
                expires_at=kwargs.get("expires_at"),
                participant_id=kwargs.get("participant_id"),
            )
        )
        s.commit()


def test_happy_path_enrollment_schedule_and_events(client, db_engine):
    pairs = []
    with Session(db_engine) as s:
        pairs = create_invites(s, 1, pepper=PEPPER)
        s.commit()
    code = pairs[0][1]

    step1 = client.post("/api/study/enroll/code", json={"code": code})
    assert step1.status_code == 200
    tok = step1.json()["enrollment_token"]
    assert step1.json()["consent_version"] == CONSENT_VERSION

    consent_body = {
        "enrollment_token": tok,
        "consent_version": CONSENT_VERSION,
        "consent_sha256": consent_text_sha256(),
        "signed_name": "Dr Pat Example",
        "answers": _answers(recording=False),
    }
    assert client.post("/api/study/enroll/consent", json=consent_body).status_code == 201

    profile = {"enrollment_token": tok, **PROFILE}
    step3 = client.post("/api/study/enroll/profile", json=profile)
    assert step3.status_code == 200
    session_token = step3.json()["token"]
    participant_id = step3.json()["participant_id"]
    assert participant_id == "P01"

    me = client.get("/api/study/me", headers={"Authorization": f"Bearer {session_token}"})
    assert me.status_code == 200
    arms = [i["arm"] for i in me.json()["items"]]
    assert arms == ["usual_care", "athena_full"] or arms == ["athena_full", "usual_care"]

    event = {
        "participant_id": participant_id,
        "session_id": "S1",
        "case_id": me.json()["items"][0]["case_id"],
        "arm": me.json()["items"][0]["arm"],
        "event_type": "case_opened",
        "client_ts": "2026-01-01T09:00:00Z",
        "payload": {},
    }
    assert (
        client.post(
            "/api/study/events",
            json={"events": [event]},
            headers={"Authorization": f"Bearer {session_token}"},
        ).status_code
        == 201
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: "BAD-CODE",
        lambda c: c,
    ],
)
def test_bad_code_generic_error(client, db_engine, mutate):
    _seed_code(db_engine, "ATH-2345-AB")
    bad = mutate("ATH-2345-AB")
    if bad == "ATH-2345-AB":
        from sqlalchemy import select

        with Session(db_engine) as s:
            invite = s.scalars(select(StudyInvite)).first()
            invite.revoked = True
            s.commit()
    resp = client.post("/api/study/enroll/code", json={"code": bad if bad != "ATH-2345-AB" else "ATH-2345-AB"})
    if bad != "ATH-2345-AB":
        assert resp.status_code == 404
        assert resp.json()["detail"] == GENERIC_CODE_ERROR
    else:
        assert resp.status_code == 404


def test_expired_code_generic(client, db_engine):
    _seed_code(
        db_engine,
        "ATH-3456-CD",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    resp = client.post("/api/study/enroll/code", json={"code": "ATH-3456-CD"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == GENERIC_CODE_ERROR


def test_used_code_returns_409(client, db_engine):
    _seed_code(db_engine, "ATH-4567-EF", participant_id="P01")
    resp = client.post("/api/study/enroll/code", json={"code": "ATH-4567-EF"})
    assert resp.status_code == 409


def test_profile_before_consent_rejected(client, db_engine):
    with Session(db_engine) as s:
        code = create_invites(s, 1, pepper=PEPPER)[0][1]
        s.commit()
    tok = client.post("/api/study/enroll/code", json={"code": code}).json()["enrollment_token"]
    profile = {"enrollment_token": tok, **PROFILE}
    assert client.post("/api/study/enroll/profile", json=profile).status_code == 422


def test_consent_rejects_required_false(client, db_engine):
    with Session(db_engine) as s:
        code = create_invites(s, 1, pepper=PEPPER)[0][1]
        s.commit()
    tok = client.post("/api/study/enroll/code", json={"code": code}).json()["enrollment_token"]
    body = {
        "enrollment_token": tok,
        "consent_version": CONSENT_VERSION,
        "consent_sha256": consent_text_sha256(),
        "signed_name": "Dr Pat Example",
        "answers": _answers(),
    }
    body["answers"]["data_use"] = False
    assert client.post("/api/study/enroll/consent", json=body).status_code == 422


def test_consent_accepts_recording_false(client, db_engine):
    with Session(db_engine) as s:
        code = create_invites(s, 1, pepper=PEPPER)[0][1]
        s.commit()
    tok = client.post("/api/study/enroll/code", json={"code": code}).json()["enrollment_token"]
    body = {
        "enrollment_token": tok,
        "consent_version": CONSENT_VERSION,
        "consent_sha256": consent_text_sha256(),
        "signed_name": "Dr Pat Example",
        "answers": _answers(recording=False),
    }
    assert client.post("/api/study/enroll/consent", json=body).status_code == 201


def test_resume_wrong_email_generic(client, db_engine):
    with Session(db_engine) as s:
        code = create_invites(s, 1, pepper=PEPPER)[0][1]
        s.commit()
    tok = client.post("/api/study/enroll/code", json={"code": code}).json()["enrollment_token"]
    client.post(
        "/api/study/enroll/consent",
        json={
            "enrollment_token": tok,
            "consent_version": CONSENT_VERSION,
            "consent_sha256": consent_text_sha256(),
            "signed_name": "Dr Pat Example",
            "answers": _answers(),
        },
    )
    client.post("/api/study/enroll/profile", json={"enrollment_token": tok, **PROFILE})
    resp = client.post(
        "/api/study/enroll/resume", json={"code": code, "email": "wrong@example.org"}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == GENERIC_RESUME_ERROR


def test_token_and_participant_enforcement(client, db_engine):
    with Session(db_engine) as s:
        code = create_invites(s, 1, pepper=PEPPER)[0][1]
        s.commit()
    tok = client.post("/api/study/enroll/code", json={"code": code}).json()["enrollment_token"]
    client.post(
        "/api/study/enroll/consent",
        json={
            "enrollment_token": tok,
            "consent_version": CONSENT_VERSION,
            "consent_sha256": consent_text_sha256(),
            "signed_name": "Dr Pat Example",
            "answers": _answers(),
        },
    )
    out = client.post("/api/study/enroll/profile", json={"enrollment_token": tok, **PROFILE}).json()
    token = out["token"]
    bad_event = {
        "participant_id": "P99",
        "session_id": "S1",
        "case_id": "avu-001",
        "arm": "usual_care",
        "event_type": "case_opened",
        "client_ts": "2026-01-01T09:00:00Z",
        "payload": {},
    }
    assert (
        client.post(
            "/api/study/events",
            json={"events": [bad_event]},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 403
    )
    assert client.get("/api/study/me", headers={"Authorization": "Bearer not.valid"}).status_code == 401


def test_withdraw_blocks_events(client, db_engine):
    with Session(db_engine) as s:
        code = create_invites(s, 1, pepper=PEPPER)[0][1]
        s.commit()
    tok = client.post("/api/study/enroll/code", json={"code": code}).json()["enrollment_token"]
    client.post(
        "/api/study/enroll/consent",
        json={
            "enrollment_token": tok,
            "consent_version": CONSENT_VERSION,
            "consent_sha256": consent_text_sha256(),
            "signed_name": "Dr Pat Example",
            "answers": _answers(),
        },
    )
    out = client.post("/api/study/enroll/profile", json={"enrollment_token": tok, **PROFILE}).json()
    token = out["token"]
    assert client.post("/api/study/withdraw", headers={"Authorization": f"Bearer {token}"}).status_code == 204
    event = {
        "participant_id": out["participant_id"],
        "session_id": "S1",
        "case_id": "avu-001",
        "arm": "usual_care",
        "event_type": "case_opened",
        "client_ts": "2026-01-01T09:00:00Z",
        "payload": {},
    }
    assert (
        client.post(
            "/api/study/events",
            json={"events": [event]},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 403
    )


def test_admin_csv_requires_key_and_events_are_pseudonymous(client, db_engine):
    with Session(db_engine) as s:
        code = create_invites(s, 1, pepper=PEPPER)[0][1]
        s.commit()
    tok = client.post("/api/study/enroll/code", json={"code": code}).json()["enrollment_token"]
    client.post(
        "/api/study/enroll/consent",
        json={
            "enrollment_token": tok,
            "consent_version": CONSENT_VERSION,
            "consent_sha256": consent_text_sha256(),
            "signed_name": "Dr Pat Example",
            "answers": _answers(),
        },
    )
    out = client.post("/api/study/enroll/profile", json={"enrollment_token": tok, **PROFILE}).json()
    token = out["token"]
    event = {
        "participant_id": out["participant_id"],
        "session_id": "S1",
        "case_id": "avu-001",
        "arm": "usual_care",
        "event_type": "case_opened",
        "client_ts": "2026-01-01T09:00:00Z",
        "payload": {},
    }
    client.post(
        "/api/study/events",
        json={"events": [event]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert client.get("/api/study/admin/events.csv").status_code == 401
    events_csv = client.get(
        "/api/study/admin/events.csv", headers={"X-Athena-Api-Key": API_KEY}
    ).text
    assert "pat@example.org" not in events_csv
    assert "Dr Pat" not in events_csv
    assert client.get("/api/study/admin/participants.csv").status_code == 401
    parts = client.get(
        "/api/study/admin/participants.csv", headers={"X-Athena-Api-Key": API_KEY}
    ).text
    assert "pat@example.org" in parts


def test_rate_limit_on_failed_attempts(client, db_engine):
    for _ in range(10):
        client.post("/api/study/enroll/code", json={"code": "ATH-0000-00"})
    resp = client.post("/api/study/enroll/code", json={"code": "ATH-0000-00"})
    assert resp.status_code == 429


def test_schedule_locked_without_enrollment_flag(monkeypatch):
    monkeypatch.setenv(
        "ATHENA_STUDY_CASE_SET", str(DEFAULT_CASE_SET_DIR / "pilot_v0.yaml")
    )
    open_client, _ = _make_client(monkeypatch, require_enrollment=True)
    assert open_client.get("/api/study/schedule/0").status_code == 401
    assert (
        open_client.get(
            "/api/study/schedule/0",
            headers={"X-Athena-Api-Key": API_KEY},
        ).status_code
        == 200
    )