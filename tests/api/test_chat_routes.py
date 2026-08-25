"""API route tests for chat interface endpoints (Phases 1-6)."""

import os

import pytest
from fastapi.testclient import TestClient

from secondlook.api.app import create_app

os.environ["ATHENA_API_AUTH_DISABLED"] = "true"


def test_chat_catalogs():
    app = create_app()
    client = TestClient(app)

    res_models = client.get("/api/chat/models")
    assert res_models.status_code == 200
    models = res_models.json()
    assert any(m["id"] == "mock-outline" for m in models)

    res_attach = client.get("/api/chat/attachments")
    assert res_attach.status_code == 200
    attach = res_attach.json()
    assert any(a["id"] == "variant-normalizer" for a in attach)

    res_ctx = client.get("/api/chat/contexts")
    assert res_ctx.status_code == 200
    assert isinstance(res_ctx.json(), list)


def test_chat_session_lifecycle_and_turn():
    app = create_app()
    client = TestClient(app)

    # 1. Create session
    create_res = client.post(
        "/api/chat/sessions",
        json={"model_id": "mock-outline", "attachment_ids": ["variant-normalizer"]},
    )
    assert create_res.status_code == 200
    session_data = create_res.json()
    session_id = session_data["id"]
    assert session_data["model_id"] == "mock-outline"

    # 2. Get session
    get_res = client.get(f"/api/chat/sessions/{session_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == session_id

    # 3. Patch session
    patch_res = client.patch(
        f"/api/chat/sessions/{session_id}",
        json={"model_id": "mock-terse", "attachment_ids": ["citation-guard"]},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["model_id"] == "mock-terse"
    assert patch_res.json()["attachment_ids"] == ["citation-guard"]

    # 4. Post a turn
    turn_res = client.post(
        f"/api/chat/sessions/{session_id}/turns",
        json={"message": "What are resistance options for EGFR T790M?"},
    )
    assert turn_res.status_code == 200
    turn_data = turn_res.json()
    assert turn_data["user_message"]["content"] == "What are resistance options for EGFR T790M?"
    assert turn_data["assistant_message"]["content"] is not None
    assert turn_data["turn"]["model_id"] == "mock-terse"

    # 5. Delete session
    del_res = client.delete(f"/api/chat/sessions/{session_id}")
    assert del_res.status_code == 200
    assert del_res.json() == {"deleted": True}

    # 6. Verify 404 after delete
    assert client.get(f"/api/chat/sessions/{session_id}").status_code == 404


@pytest.mark.integration
def test_phase5_subgraph_endpoint():
    app = create_app()
    client = TestClient(app)

    res = client.get("/api/chat/contexts/gene:EGFR/graph")
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data
    assert "cypher" in data
    assert "MATCH" in data["cypher"]
    assert isinstance(data["nodes"], list)


@pytest.mark.integration
def test_phase6_retrieval_grounding_in_turn():
    app = create_app()
    client = TestClient(app)

    # Create session with variant-normalizer
    create_res = client.post(
        "/api/chat/sessions",
        json={
            "model_id": "mock-outline",
            "attachment_ids": ["variant-normalizer", "citation-guard"],
        },
    )
    session_id = create_res.json()["id"]

    turn_res = client.post(
        f"/api/chat/sessions/{session_id}/turns",
        json={"message": "What are the therapies for ETV6::NTRK3 fusion?"},
    )
    assert turn_res.status_code == 200
    turn_data = turn_res.json()

    # Assert Phase 6 sources returned
    sources = turn_data["turn"]["sources"]
    assert len(sources) > 0
    assert any(
        "Larotrectinib" in s.get("title", "") or "Larotrectinib" in s.get("summary", "")
        for s in sources
    )
    assert any(s.get("citation_url") for s in sources)
