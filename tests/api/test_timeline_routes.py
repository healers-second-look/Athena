from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from secondlook.api.app import create_app
from secondlook.api.deps import get_dispatch, get_graph, get_llm_client, get_store

from .fakes import InMemoryStore


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setenv("ATHENA_API_AUTH_DISABLED", "true")
    monkeypatch.delenv("ATHENA_API_KEY", raising=False)
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_graph] = lambda: None
    app.dependency_overrides[get_llm_client] = lambda: None
    app.dependency_overrides[get_dispatch] = lambda: (lambda *a, **k: [])
    return TestClient(app)


def test_timeline_unknown_case_is_404_not_empty_reason(client):
    """Same non-negotiable rule test_routes.py already asserts for
    /changes: a missing case is a 404, never a 200-with-empty-timeline."""
    response = client.get(f"/api/cases/{uuid.uuid4()}/timeline")
    assert response.status_code == 404


def test_timeline_existing_case_returns_all_four_tracks(client, store):
    case = store.create_case(label="C1", cancer_type="NSCLC")
    response = client.get(f"/api/cases/{case.id}/timeline")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"events", "mrd", "cytometry", "lab_results"}
    assert len(body["events"]) > 0
    assert len(body["mrd"]) > 0
    assert len(body["cytometry"]) > 0
    assert len(body["lab_results"]) > 0


def test_timeline_event_shape_matches_the_schema(client, store):
    case = store.create_case(label="C1", cancer_type="NSCLC")
    body = client.get(f"/api/cases/{case.id}/timeline").json()
    event = body["events"][0]
    assert set(event.keys()) == {
        "date",
        "end_date",
        "category",
        "subcategory",
        "group",
        "title",
        "dose",
        "condition_track",
    }
    assert event["category"] in {"Treatments", "Procedures", "Imaging"}
