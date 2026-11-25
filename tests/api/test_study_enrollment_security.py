"""Security and authorization with STUDY_REQUIRE_ENROLLMENT enabled."""

from __future__ import annotations

import re

import pytest

from tests.api.test_enroll_routes import PROFILE, _answers, _make_client
from secondlook.study.invites import create_invites


PUBLIC_EXACT = {
    ("GET", "/healthz"),
    ("POST", "/api/study/enroll/code"),
    ("POST", "/api/study/enroll/consent"),
    ("POST", "/api/study/enroll/profile"),
    ("POST", "/api/study/enroll/resume"),
}


def _fill_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "0", path)


@pytest.fixture
def locked_client(monkeypatch):
    client, engine = _make_client(monkeypatch, require_enrollment=True)
    return client, engine


def _enroll_participant(client, engine):
    with engine.begin() as conn:
        from sqlalchemy.orm import Session

        with Session(bind=conn) as s:
            code = create_invites(s, 2, pepper="route-test-pepper")[0][1]
    step1 = client.post("/api/study/enroll/code", json={"code": code})
    tok = step1.json()["enrollment_token"]
    client.post(
        "/api/study/enroll/consent",
        json={
            "enrollment_token": tok,
            "consent_version": step1.json()["consent_version"],
            "consent_sha256": step1.json()["consent_sha256"],
            "signed_name": "Dr Pat Example",
            "answers": _answers(),
        },
    )
    out = client.post("/api/study/enroll/profile", json={"enrollment_token": tok, **PROFILE}).json()
    return out["token"], out["participant_id"]


def test_every_route_locked_without_credentials(locked_client):
    """Walks the OpenAPI schema: `app.routes` does not list included routers flat."""
    client, _ = locked_client
    checked = set()
    open_routes = []
    for path, operations in client.app.openapi()["paths"].items():
        for method in operations:
            key = (method.upper(), path)
            if key in PUBLIC_EXACT:
                continue
            checked.add(key)
            response = client.request(key[0], _fill_path(path), params={"arm": "athena_full"})
            if response.status_code not in {401, 403}:
                open_routes.append((*key, response.status_code))
    assert open_routes == []
    # Guards against the walk silently seeing no routes.
    assert len(checked) > 20
    assert {
        ("POST", "/api/chat/sessions"),
        ("POST", "/api/study/events"),
        ("POST", "/api/study/chat/sessions"),
    } <= checked


def test_api_docs_are_not_served_when_locked(locked_client):
    client, _ = locked_client
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert client.get("/healthz").status_code == 200


def test_participant_cannot_read_other_arm_or_unscheduled_case(locked_client):
    client, engine = locked_client
    token, participant_id = _enroll_participant(client, engine)
    me = client.get("/api/study/me", headers={"Authorization": f"Bearer {token}"}).json()
    own = me["items"][0]
    other_arm = "usual_care" if own["arm"] == "athena_full" else "athena_full"
    assert (
        client.get(
            f"/api/study/cases/{own['case_id']}?arm={other_arm}",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/study/cases/avu-999?arm=usual_care",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        in {403, 404}
    )


def test_study_chat_is_private_to_owner(locked_client, monkeypatch):
    from secondlook.api.routes import study as study_routes

    client, engine = locked_client
    monkeypatch.setenv("ATHENA_STUDY_ALLOW_UNREVIEWED", "true")
    monkeypatch.setattr(
        study_routes,
        "graph_live_evidence_ready",
        lambda **_: (True, []),
    )
    monkeypatch.setenv("ATHENA_STUDY_CHAT_MODEL", "gpt-test")
    token_a, _ = _enroll_participant(client, engine)
    from sqlalchemy.orm import Session

    with Session(engine) as s:
        from secondlook.study.invites import create_invites

        code_b = create_invites(s, 2, pepper="route-test-pepper")[1][1]
        s.commit()
    step1 = client.post("/api/study/enroll/code", json={"code": code_b})
    tok_b = step1.json()["enrollment_token"]
    client.post(
        "/api/study/enroll/consent",
        json={
            "enrollment_token": tok_b,
            "consent_version": step1.json()["consent_version"],
            "consent_sha256": step1.json()["consent_sha256"],
            "signed_name": "Dr B Example",
            "answers": _answers(),
        },
    )
    out_b = client.post(
        "/api/study/enroll/profile",
        json={"enrollment_token": tok_b, **{**PROFILE, "email": "b@example.org"}},
    ).json()
    token_b = out_b["token"]
    me_a = client.get("/api/study/me", headers={"Authorization": f"Bearer {token_a}"}).json()
    case_id = next(i["case_id"] for i in me_a["items"] if i["arm"] == "athena_full")
    session = client.post(
        "/api/study/chat/sessions",
        json={"case_id": case_id},
        headers={"Authorization": f"Bearer {token_a}"},
    ).json()
    assert (
        client.get(
            f"/api/study/chat/sessions/{session['id']}",
            headers={"Authorization": f"Bearer {token_b}"},
        ).status_code
        == 404
    )
    stolen = client.post(
        f"/api/study/chat/sessions/{session['id']}/turns",
        json={"message": "hello"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert stolen.status_code == 404


def test_events_reject_unscheduled_case_arm(locked_client):
    client, engine = locked_client
    token, participant_id = _enroll_participant(client, engine)
    me = client.get("/api/study/me", headers={"Authorization": f"Bearer {token}"}).json()
    own = me["items"][0]
    wrong_arm = "usual_care" if own["arm"] == "athena_full" else "athena_full"
    event = {
        "participant_id": participant_id,
        "session_id": "S1",
        "case_id": own["case_id"],
        "arm": wrong_arm,
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


def test_recall_and_case_reject_a_case_outside_the_schedule(locked_client, monkeypatch):
    from secondlook.api.routes import study as study_routes

    client, engine = locked_client
    token, _ = _enroll_participant(client, engine)
    auth = {"Authorization": f"Bearer {token}"}
    case_id = client.get("/api/study/me", headers=auth).json()["items"][0]["case_id"]
    assert client.get(f"/api/study/cases/{case_id}/recall", headers=auth).status_code == 200
    monkeypatch.setattr(study_routes, "participant_case_schedule", lambda *_: [])
    assert client.get(f"/api/study/cases/{case_id}/recall", headers=auth).status_code == 403
    for arm in ("usual_care", "athena_full"):
        response = client.get(f"/api/study/cases/{case_id}?arm={arm}", headers=auth)
        assert response.status_code == 403
