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


# ---------------------------------------------------------------------------
# Boundary hardening. Every case below returned 200 or a 500 stack trace when
# the chat surface first shipped: `unknown_ids` was written, exported and
# unit-tested but never called from a route, and `LLMClientError` -- which
# `build_client` raises by design for a model this deployment cannot serve --
# was caught nowhere.
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(create_app())


class TestUnknownConfigurationIsRejected:
    def test_unknown_attachment_id(self, client):
        res = client.post("/api/chat/sessions", json={"attachment_ids": ["totally-made-up"]})
        assert res.status_code == 422
        assert "totally-made-up" in res.json()["detail"]

    def test_unknown_model_id(self, client):
        res = client.post("/api/chat/sessions", json={"model_id": "gpt-9-ultra"})
        assert res.status_code == 422
        assert "mock-outline" in res.json()["detail"], "the error should list what IS valid"

    def test_malformed_context_id(self, client):
        res = client.post("/api/chat/sessions", json={"context_id": "patient:nobody"})
        assert res.status_code == 422

    def test_a_well_formed_context_id_is_accepted_without_touching_the_database(self, client):
        # Validation is shape-only on purpose: refusing to let someone
        # configure a session while FalkorDB is down makes the outage worse.
        res = client.post("/api/chat/sessions", json={"context_id": "gene:EGFR"})
        assert res.status_code == 200

    def test_patch_validates_too(self, client):
        session_id = client.post("/api/chat/sessions", json={}).json()["id"]
        res = client.patch(f"/api/chat/sessions/{session_id}", json={"model_id": "nope"})
        assert res.status_code == 422

    def test_an_empty_message_is_rejected(self, client):
        session_id = client.post("/api/chat/sessions", json={}).json()["id"]
        assert (
            client.post(
                f"/api/chat/sessions/{session_id}/turns", json={"message": "   "}
            ).status_code
            == 422
        )


class TestAFailedTurnLeavesNoTrace:
    """A turn lands as a user/assistant pair or not at all.

    The user message used to be appended before the engine ran, so a turn
    that raised left it orphaned in history -- and the client, having
    received a 500, resent it and duplicated it.
    """

    def _unconfigured_session(self, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        session_id = client.post("/api/chat/sessions", json={}).json()["id"]
        client.patch(f"/api/chat/sessions/{session_id}", json={"model_id": "anthropic"})
        return session_id

    def test_an_unconfigured_model_is_a_conflict_not_a_crash(self, client, monkeypatch):
        session_id = self._unconfigured_session(client, monkeypatch)
        res = client.post(f"/api/chat/sessions/{session_id}/turns", json={"message": "hi"})
        assert res.status_code == 409
        assert "not configured" in res.json()["detail"]

    def test_history_is_untouched_after_the_failure(self, client, monkeypatch):
        session_id = self._unconfigured_session(client, monkeypatch)
        client.post(f"/api/chat/sessions/{session_id}/turns", json={"message": "hi"})
        history = client.get(f"/api/chat/sessions/{session_id}").json()["history"]
        assert history == [], "a failed turn must not orphan the user message"

    def test_retrying_does_not_duplicate(self, client, monkeypatch):
        session_id = self._unconfigured_session(client, monkeypatch)
        for _ in range(3):
            client.post(f"/api/chat/sessions/{session_id}/turns", json={"message": "hi"})
        assert client.get(f"/api/chat/sessions/{session_id}").json()["history"] == []


class TestOnlyThePaidPathIsGated:
    """The turn endpoint is the only route here that can spend money, and it
    shipped with no auth while cases/findings writes required a key."""

    def test_the_offline_mocks_stay_open(self, client):
        # They cost nothing, reach no network, and are the whole reviewable
        # demo. Gating them would break `Phase 1` for no security gain.
        created = client.post("/api/chat/sessions", json={"model_id": "mock-outline"})
        session_id = created.json()["id"]
        res = client.post(f"/api/chat/sessions/{session_id}/turns", json={"message": "EGFR?"})
        assert res.status_code == 200

    def test_a_paid_model_requires_the_api_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
        monkeypatch.setenv("ATHENA_API_KEY", "secret")
        monkeypatch.delenv("ATHENA_API_AUTH_DISABLED", raising=False)
        client = TestClient(create_app())

        session_id = client.post("/api/chat/sessions", json={"model_id": "anthropic"}).json()["id"]
        res = client.post(f"/api/chat/sessions/{session_id}/turns", json={"message": "hi"})
        assert res.status_code == 401, "an open proxy to a paid API"


class TestTurnPayloadCarriesRetrievalStatus:
    def test_retrieval_failure_reaches_the_client(self, client):
        """Not only the server log. The clinician reads the answer, not stdout."""
        session_id = client.post("/api/chat/sessions", json={}).json()["id"]
        turn = client.post(
            f"/api/chat/sessions/{session_id}/turns", json={"message": "EGFR T790M?"}
        ).json()["turn"]

        assert "retrieval_failed" in turn
        assert "retrieval_error" in turn
        if turn["retrieval_failed"]:
            assert turn["retrieval_error"], "a failure must say why"
            assert any("retrieval FAILED" in n for n in turn["notes"])
