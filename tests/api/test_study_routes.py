"""Tests for the study API routes (issue #136).

The tests that matter most here are the ones about *leaking*: the study is
worthless if a reviewer's browser can be sent the answer key, or if arms B and
C can be sent the diff that only arm A is meant to have.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from secondlook.api.app import create_app
from secondlook.api.deps import get_session
from secondlook.study.cases import DEFAULT_CASE_SET_DIR, load_case_set
from secondlook.study.events import ARMS, StudyEvent

API_KEY = "test-key"
EVENT = {
    "participant_id": "P01",
    "session_id": "S1",
    "case_id": "pilot-001",
    "arm": "diff_first",
    "event_type": "case_opened",
    "client_ts": "2026-01-01T09:00:00Z",
    "payload": {},
}


def _make_client(monkeypatch, *, enabled=True, allow_unreviewed=True):
    monkeypatch.setenv("ATHENA_API_KEY", API_KEY)
    monkeypatch.delenv("ATHENA_API_AUTH_DISABLED", raising=False)
    monkeypatch.delenv("ATHENA_STUDY_CASE_SET", raising=False)
    monkeypatch.setenv("ATHENA_STUDY_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("ATHENA_STUDY_ALLOW_UNREVIEWED", "true" if allow_unreviewed else "false")
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    StudyEvent.__table__.create(engine)
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
    return TestClient(app)


@pytest.fixture
def client(monkeypatch):
    return _make_client(monkeypatch)


def test_study_routes_do_not_exist_unless_enabled(monkeypatch):
    disabled = _make_client(monkeypatch, enabled=False)
    assert disabled.get("/api/study/cases").status_code == 404
    assert disabled.post("/api/study/events", json={"events": [EVENT]}).status_code == 404


def test_an_unreviewed_case_set_is_refused_by_default(monkeypatch):
    strict = _make_client(monkeypatch, allow_unreviewed=False)
    response = strict.get("/api/study/cases")
    assert response.status_code == 503
    reasons = " ".join(response.json()["detail"]["reasons"])
    assert "clinician_reviewed" in reasons


def test_case_list_flags_unreviewed_content(client):
    body = client.get("/api/study/cases").json()
    assert body["unreviewed"] is True
    assert len(body["cases"]) == 5


def test_diff_is_present_in_arm_a_and_structurally_absent_elsewhere(client):
    a = client.get("/api/study/cases/pilot-001?arm=diff_first").json()["case"]
    assert a["reported_supersessions"] and a["reported_changes"] and a["questions"]
    for arm in ("dashboard", "chat"):
        other = client.get(f"/api/study/cases/pilot-001?arm={arm}").json()["case"]
        assert other["reported_supersessions"] == []
        assert other["reported_changes"] == []
        assert other["questions"] == []


def test_content_is_matched_across_arms(client):
    """Same events and same findings in every arm; only the diff differs."""
    views = {
        arm: client.get(f"/api/study/cases/pilot-002?arm={arm}").json()["case"] for arm in ARMS
    }
    for key in ("baseline_events", "update_events", "findings", "decision_options"):
        assert views["diff_first"][key] == views["dashboard"][key] == views["chat"][key]


def test_ground_truth_never_reaches_the_browser(client):
    case_set = load_case_set(DEFAULT_CASE_SET_DIR / "pilot_v0.yaml")
    secrets = []
    for case in case_set.cases:
        secrets += [i.description for i in case.seeded_issues]
        secrets += [f.flaw for f in case.system_output.findings if f.flaw]
        secrets += list(case.reference_decision.concordant)
    forbidden_keys = (
        '"valid"',
        '"invalidated_by"',
        '"flaw"',
        '"seeded_issues"',
        '"concordant"',
        '"acceptable"',
        '"reference_decision"',
    )
    for case in case_set.cases:
        for arm in ARMS:
            text = client.get(f"/api/study/cases/{case.case_id}?arm={arm}").text
            for key in forbidden_keys:
                assert key not in text, f"{key} leaked in {case.case_id}/{arm}"
            for secret in secrets:
                if len(secret) > 3:  # skip one-letter option ids
                    assert secret not in text, f"ground truth leaked: {secret!r}"


def test_invalid_arm_and_unknown_case(client):
    assert client.get("/api/study/cases/pilot-001?arm=bogus").status_code == 422
    assert client.get("/api/study/cases/nope?arm=chat").status_code == 404


def test_events_can_be_written_without_a_key_and_read_back_with_one(client):
    assert client.post("/api/study/events", json={"events": [EVENT]}).status_code == 201
    assert client.get("/api/study/events").status_code == 401
    rows = client.get("/api/study/events", headers={"X-Athena-Api-Key": API_KEY}).json()
    assert len(rows) == 1
    assert rows[0]["participant_id"] == "P01"
    assert rows[0]["event_type"] == "case_opened"


def test_events_can_be_filtered_on_export(client):
    other = {**EVENT, "participant_id": "P02"}
    client.post("/api/study/events", json={"events": [EVENT, other]})
    rows = client.get(
        "/api/study/events?participant_id=P02", headers={"X-Athena-Api-Key": API_KEY}
    ).json()
    assert [r["participant_id"] for r in rows] == ["P02"]


@pytest.mark.parametrize(
    "bad",
    [
        {**EVENT, "case_id": "not-a-study-case"},
        {**EVENT, "arm": "sideways"},
        {**EVENT, "event_type": "invented"},
        {**EVENT, "participant_id": "a@b.org"},
        {**EVENT, "client_ts": "2026-01-01T09:00:00"},  # naive
        {**EVENT, "surprise": 1},  # extra field
    ],
)
def test_bad_events_are_rejected_and_nothing_is_written(client, bad):
    assert client.post("/api/study/events", json={"events": [EVENT, bad]}).status_code == 422
    rows = client.get("/api/study/events", headers={"X-Athena-Api-Key": API_KEY}).json()
    assert rows == []


def test_empty_batch_is_rejected(client):
    assert client.post("/api/study/events", json={"events": []}).status_code == 422
