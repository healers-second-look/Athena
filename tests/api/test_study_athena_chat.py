"""Study athena_full chat: live graph retrieval and turn limits."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.orm import Session

from secondlook.study.invites import create_invites
from tests.api.test_enroll_routes import PROFILE, _answers, _make_client


def _enrolled(client, engine, pepper):
    with Session(engine) as s:
        code = create_invites(s, 1, pepper=pepper)[0][1]
        s.commit()
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
    me = client.get("/api/study/me", headers={"Authorization": f"Bearer {out['token']}"}).json()
    athena_item = next(i for i in me["items"] if i["arm"] == "athena_full")
    return out["token"], athena_item["case_id"]


@pytest.fixture
def enrolled_athena(monkeypatch):
    client, engine = _make_client(monkeypatch, require_enrollment=True)
    monkeypatch.setenv("ATHENA_STUDY_ALLOW_UNREVIEWED", "true")
    monkeypatch.delenv("ATHENA_STUDY_CHAT_MODEL", raising=False)
    return client, engine


@pytest.fixture(autouse=True)
def _reset_study_chat_sessions():
    from secondlook.api.routes import study as study_routes
    from secondlook.chat.session import _sessions

    study_routes._STUDY_CHAT_SESSIONS.clear()
    _sessions.clear()
    yield
    study_routes._STUDY_CHAT_SESSIONS.clear()
    _sessions.clear()


def test_athena_full_503_when_mock_model(enrolled_athena, monkeypatch):
    from secondlook.api.routes import study as study_routes

    client, engine = enrolled_athena
    token, case_id = _enrolled(client, engine, os.environ["STUDY_CODE_PEPPER"])
    monkeypatch.setenv("ATHENA_STUDY_CHAT_MODEL", "mock-outline")
    monkeypatch.setattr(
        study_routes,
        "graph_live_evidence_ready",
        lambda **_: (True, []),
    )
    monkeypatch.setattr(study_routes, "study_chat_allows_degraded", lambda: False)
    resp = client.post(
        "/api/study/chat/sessions",
        json={"case_id": case_id, "arm": "athena_full"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 503
    assert "mock" in str(resp.json()["detail"]).lower()


def test_athena_full_degraded_with_allow_unreviewed(enrolled_athena, monkeypatch):
    client, engine = enrolled_athena
    monkeypatch.setenv("ATHENA_STUDY_CHAT_MODEL", "mock-outline")
    monkeypatch.setattr(
        "secondlook.api.routes.study.graph_live_evidence_ready",
        lambda **_: (False, ["graph down"]),
    )
    token, case_id = _enrolled(client, engine, os.environ["STUDY_CODE_PEPPER"])
    resp = client.post(
        "/api/study/chat/sessions",
        json={"case_id": case_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "degraded" in body
    assert body["degraded"]


def test_athena_full_turn_uses_live_retrieval(enrolled_athena, monkeypatch):
    client, engine = enrolled_athena
    monkeypatch.setenv("ATHENA_STUDY_CHAT_MODEL", "gpt-test")
    monkeypatch.setattr(
        "secondlook.api.routes.study.graph_live_evidence_ready",
        lambda **_: (True, []),
    )
    captured = {}

    def fake_run_turn(message, **kwargs):
        captured.update(kwargs)
        import time

        from secondlook.chat.engine import TurnResult

        return TurnResult(
            id="t1",
            role="assistant",
            content="ok",
            model_id=kwargs.get("model_id", "gpt-test"),
            timestamp=time.time(),
            sources=[],
            sources_count=0,
        )

    monkeypatch.setattr("secondlook.api.routes.study.run_turn", fake_run_turn)
    token, case_id = _enrolled(client, engine, os.environ["STUDY_CODE_PEPPER"])
    session = client.post(
        "/api/study/chat/sessions",
        json={"case_id": case_id},
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    client.post(
        f"/api/study/chat/sessions/{session['id']}/turns",
        json={"message": "Summarise."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert "sources_override" not in captured or captured.get("sources_override") is None
    assert captured.get("attachment_ids") == ["variant-normalizer", "citation-guard"]
    assert captured.get("extra_context_lines")
    ctx = captured.get("context_id")
    assert ctx is None or str(ctx).startswith("gene:")


def test_turn_limit_across_sessions(enrolled_athena, monkeypatch):
    client, engine = enrolled_athena
    monkeypatch.setenv("ATHENA_STUDY_CHAT_MODEL", "gpt-test")
    monkeypatch.setenv("STUDY_CHAT_MAX_TURNS", "2")
    monkeypatch.setattr(
        "secondlook.api.routes.study.graph_live_evidence_ready",
        lambda **_: (True, []),
    )

    def fake_run_turn(message, **kwargs):
        import time

        from secondlook.chat.engine import TurnResult

        return TurnResult(
            id="t1",
            role="assistant",
            content="ok",
            model_id="gpt-test",
            timestamp=time.time(),
        )

    monkeypatch.setattr("secondlook.api.routes.study.run_turn", fake_run_turn)
    token, case_id = _enrolled(client, engine, os.environ["STUDY_CODE_PEPPER"])
    for _ in range(2):
        sid = client.post(
            "/api/study/chat/sessions",
            json={"case_id": case_id},
            headers={"Authorization": f"Bearer {token}"},
        ).json()["id"]
        assert (
            client.post(
                f"/api/study/chat/sessions/{sid}/turns",
                json={"message": "hi"},
                headers={"Authorization": f"Bearer {token}"},
            ).status_code
            == 200
        )
    sid2 = client.post(
        "/api/study/chat/sessions",
        json={"case_id": case_id},
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]
    resp = client.post(
        f"/api/study/chat/sessions/{sid2}/turns",
        json={"message": "one more"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 429


def test_graph_lost_mid_case_is_an_error_not_an_ungrounded_answer(enrolled_athena, monkeypatch):
    from secondlook.api.routes import study as study_routes

    client, engine = enrolled_athena
    token, case_id = _enrolled(client, engine, os.environ["STUDY_CODE_PEPPER"])
    auth = {"Authorization": f"Bearer {token}"}
    monkeypatch.setenv("ATHENA_STUDY_CHAT_MODEL", "anthropic")
    monkeypatch.setattr(study_routes, "study_chat_allows_degraded", lambda: False)
    monkeypatch.setattr(study_routes, "graph_live_evidence_ready", lambda **_: (True, []))
    body = {"case_id": case_id, "arm": "athena_full"}
    session = client.post("/api/study/chat/sessions", json=body, headers=auth).json()
    monkeypatch.setattr(study_routes, "graph_live_evidence_ready", lambda **_: (False, ["down"]))
    monkeypatch.setattr(study_routes, "run_turn", lambda *a, **k: pytest.fail("model was called"))
    url = f"/api/study/chat/sessions/{session['id']}/turns"
    assert client.post(url, json={"message": "hi"}, headers=auth).status_code == 503
