"""Offline tests for synthesis/llm_client.py -- no live LLM, no network."""

from __future__ import annotations

import json
import sys

import httpx
import pytest

from secondlook.synthesis.llm_client import (
    LLM_PROVIDERS,
    AnthropicClient,
    LLMClientError,
    OpenAICompatibleClient,
    get_llm_client,
    llm_enabled,
)
from secondlook.tier1.graph_schema import assert_valid


class TestLlmEnabled:
    def test_default_is_true(self, monkeypatch):
        monkeypatch.delenv("ATHENA_LLM_ENABLED", raising=False)
        assert llm_enabled() is True

    def test_false_string_is_false(self, monkeypatch):
        monkeypatch.setenv("ATHENA_LLM_ENABLED", "false")
        assert llm_enabled() is False

    def test_zero_is_false(self, monkeypatch):
        monkeypatch.setenv("ATHENA_LLM_ENABLED", "0")
        assert llm_enabled() is False

    def test_false_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ATHENA_LLM_ENABLED", "FALSE")
        assert llm_enabled() is False


class TestGetLlmClient:
    def test_disabled_returns_none_without_constructing_a_client(self, monkeypatch):
        monkeypatch.setenv("ATHENA_LLM_ENABLED", "false")

        def boom(*_a, **_k):
            raise AssertionError("client constructor must not run when disabled")

        monkeypatch.setattr("secondlook.synthesis.llm_client.AnthropicClient", boom)
        monkeypatch.setattr("secondlook.synthesis.llm_client.OpenAICompatibleClient", boom)
        assert get_llm_client() is None

    def test_disabled_does_not_import_anthropic(self, monkeypatch):
        monkeypatch.setenv("ATHENA_LLM_ENABLED", "false")
        sys.modules.pop("anthropic", None)
        get_llm_client()
        assert "anthropic" not in sys.modules

    def test_invalid_provider_raises_via_assert_valid(self, monkeypatch):
        monkeypatch.setenv("ATHENA_LLM_ENABLED", "true")
        monkeypatch.setenv("ATHENA_LLM_PROVIDER", "magic-8-ball")
        with pytest.raises(ValueError, match="ATHENA_LLM_PROVIDER"):
            get_llm_client()

    def test_providers_allowed_set_is_closed(self):
        assert_valid("anthropic", LLM_PROVIDERS, "ATHENA_LLM_PROVIDER")
        assert_valid("openai_compatible", LLM_PROVIDERS, "ATHENA_LLM_PROVIDER")
        with pytest.raises(ValueError):
            assert_valid("something_else", LLM_PROVIDERS, "ATHENA_LLM_PROVIDER")


class TestAnthropicLazyImport:
    def test_construction_does_not_import_anthropic(self, monkeypatch):
        sys.modules.pop("anthropic", None)

        class _Blocker:
            def find_module(self, name, path=None):  # noqa: ARG002 -- import hook
                if name == "anthropic" or name.startswith("anthropic."):
                    raise ImportError("anthropic must not be imported at construction")
                return None

            def find_spec(self, name, path=None, target=None):  # noqa: ARG002
                if name == "anthropic" or name.startswith("anthropic."):
                    raise ImportError("anthropic must not be imported at construction")
                return None

        blocker = _Blocker()
        monkeypatch.setattr(sys, "meta_path", [blocker, *sys.meta_path])
        client = AnthropicClient(model="claude-sonnet-4-5")
        assert client.model == "claude-sonnet-4-5"
        assert "anthropic" not in sys.modules

    def test_default_model_is_a_documented_constant(self, monkeypatch):
        monkeypatch.delenv("ATHENA_LLM_MODEL", raising=False)
        client = AnthropicClient()
        assert client.model
        assert isinstance(client.model, str)


class TestOpenAICompatibleConstruction:
    def test_reads_base_url_and_model_from_env(self, monkeypatch):
        monkeypatch.setenv("ATHENA_LLM_BASE_URL", "http://localhost:8000/v1")
        monkeypatch.setenv("ATHENA_LLM_MODEL", "candidate-model")
        client = OpenAICompatibleClient()
        assert client.base_url == "http://localhost:8000/v1"
        assert client.model == "candidate-model"

    def test_no_model_is_hardcoded(self, monkeypatch):
        monkeypatch.delenv("ATHENA_LLM_MODEL", raising=False)
        monkeypatch.delenv("ATHENA_LLM_BASE_URL", raising=False)
        with pytest.raises(Exception, match="ATHENA_LLM_"):
            OpenAICompatibleClient()


def _mock_transport(
    *, status_code: int = 200, json_body: dict | None = None, capture: dict | None = None
):
    """A fake HTTP server. `capture`, if given, records what the client
    actually sent -- the request method, URL, headers, and parsed JSON
    body -- so a test can assert on the real wire traffic, not just the
    parsed return value.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["method"] = request.method
            capture["url"] = str(request.url)
            capture["headers"] = {k.lower(): v for k, v in request.headers.items()}
            capture["json"] = json.loads(request.content)
        return httpx.Response(status_code, json=json_body)

    return httpx.MockTransport(handler)


def _openai_chat_completion(content: str, *, model: str = "BioMistral-7B") -> dict:
    """The real response shape vLLM, Ollama, and text-generation-inference
    all emit when serving an OpenAI-compatible `/chat/completions`
    endpoint -- this is the standard OpenAI wire format those servers
    implement, not something specific to any one of them. A self-hosted
    BioMistral-7B deployment behind any of these three servers would
    return exactly this shape.
    """
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 42, "completion_tokens": 17, "total_tokens": 59},
    }


class TestOpenAICompatibleCompleteAgainstAVllmShapedServer:
    """Realistic mocked round-trip against the actual OpenAI-compatible
    wire format a self-hosted BioMistral-7B deployment (behind vLLM,
    Ollama, or TGI) would speak. This is issue #122's "confirm
    OpenAICompatibleClient works unmodified" deliverable, verified as far
    as an offline suite can: it proves the client sends a correctly
    shaped request and correctly parses a correctly shaped response. It
    does **not** prove a real, running BioMistral-7B server behaves this
    way in practice -- see `docs/deployment/biomistral-deployment.md`'s
    "What this does not verify" section for that gap, stated plainly
    rather than implied away by these tests passing.
    """

    def test_complete_returns_the_message_content(self):
        transport = _mock_transport(
            json_body=_openai_chat_completion(
                "EGFR T790M confers osimertinib sensitivity [ref:civic_12]."
            )
        )
        client = OpenAICompatibleClient(
            base_url="http://localhost:8000/v1",
            model="BioMistral-7B",
            client=httpx.Client(transport=transport),
        )
        result = client.complete("What evidence exists for EGFR T790M?")
        assert result == "EGFR T790M confers osimertinib sensitivity [ref:civic_12]."

    def test_request_hits_the_chat_completions_endpoint(self):
        capture: dict = {}
        transport = _mock_transport(json_body=_openai_chat_completion("ok"), capture=capture)
        client = OpenAICompatibleClient(
            base_url="http://localhost:8000/v1",
            model="BioMistral-7B",
            client=httpx.Client(transport=transport),
        )
        client.complete("question")
        assert capture["url"] == "http://localhost:8000/v1/chat/completions"
        assert capture["method"] == "POST"

    def test_trailing_slash_on_base_url_does_not_double_up(self):
        capture: dict = {}
        transport = _mock_transport(json_body=_openai_chat_completion("ok"), capture=capture)
        client = OpenAICompatibleClient(
            base_url="http://localhost:8000/v1/",
            model="BioMistral-7B",
            client=httpx.Client(transport=transport),
        )
        client.complete("question")
        assert capture["url"] == "http://localhost:8000/v1/chat/completions"

    def test_request_body_matches_the_openai_chat_format_with_system_prompt(self):
        capture: dict = {}
        transport = _mock_transport(json_body=_openai_chat_completion("ok"), capture=capture)
        client = OpenAICompatibleClient(
            base_url="http://localhost:8000/v1",
            model="BioMistral-7B",
            client=httpx.Client(transport=transport),
        )
        client.complete("What evidence exists for EGFR T790M?", system="Cite only retrieved items.")
        assert capture["json"]["model"] == "BioMistral-7B"
        assert capture["json"]["messages"] == [
            {"role": "system", "content": "Cite only retrieved items."},
            {"role": "user", "content": "What evidence exists for EGFR T790M?"},
        ]

    def test_no_system_prompt_omits_the_system_message(self):
        capture: dict = {}
        transport = _mock_transport(json_body=_openai_chat_completion("ok"), capture=capture)
        client = OpenAICompatibleClient(
            base_url="http://localhost:8000/v1",
            model="BioMistral-7B",
            client=httpx.Client(transport=transport),
        )
        client.complete("question, no system prompt")
        assert capture["json"]["messages"] == [
            {"role": "user", "content": "question, no system prompt"}
        ]

    def test_api_key_becomes_a_bearer_header_when_provided(self):
        capture: dict = {}
        transport = _mock_transport(json_body=_openai_chat_completion("ok"), capture=capture)
        client = OpenAICompatibleClient(
            base_url="http://localhost:8000/v1",
            model="BioMistral-7B",
            api_key="sk-test-123",
            client=httpx.Client(transport=transport),
        )
        client.complete("question")
        assert capture["headers"]["authorization"] == "Bearer sk-test-123"

    def test_no_api_key_sends_no_authorization_header(self):
        """The common case for a self-hosted model on an internal
        network: a local vLLM/Ollama deployment with no auth configured.
        """
        capture: dict = {}
        transport = _mock_transport(json_body=_openai_chat_completion("ok"), capture=capture)
        client = OpenAICompatibleClient(
            base_url="http://localhost:8000/v1",
            model="BioMistral-7B",
            client=httpx.Client(transport=transport),
        )
        client.complete("question")
        assert "authorization" not in capture["headers"]

    def test_non_2xx_status_raises_llm_client_error(self, monkeypatch):
        """500 is one of the statuses with_retry() treats as transient (see
        TestOpenAICompatibleRetry below), so this exercises the full retry
        budget before the wrapped error surfaces -- sleep is stubbed out so
        the test doesn't pay the real backoff delay."""
        monkeypatch.setattr("secondlook.http_retry.time.sleep", lambda _s: None)
        transport = _mock_transport(status_code=500, json_body={"error": "internal error"})
        client = OpenAICompatibleClient(
            base_url="http://localhost:8000/v1",
            model="BioMistral-7B",
            client=httpx.Client(transport=transport),
        )
        with pytest.raises(LLMClientError):
            client.complete("question")

    def test_malformed_json_response_raises_llm_client_error(self):
        def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
            return httpx.Response(200, content=b"not json at all")

        client = OpenAICompatibleClient(
            base_url="http://localhost:8000/v1",
            model="BioMistral-7B",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(LLMClientError):
            client.complete("question")

    def test_response_missing_choices_raises_llm_client_error(self):
        transport = _mock_transport(json_body={"id": "x", "object": "chat.completion"})
        client = OpenAICompatibleClient(
            base_url="http://localhost:8000/v1",
            model="BioMistral-7B",
            client=httpx.Client(transport=transport),
        )
        with pytest.raises(LLMClientError):
            client.complete("question")


class TestOpenAICompatibleRetry:
    """Covers issue #124: a transient 503 from the backend (observed live against
    Gemini Flash -- "This model is currently experiencing high demand") must not
    fail the whole chat turn."""

    def _client(self, transport: httpx.BaseTransport) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(
            base_url="http://llm.test/v1",
            model="test-model",
            client=httpx.Client(transport=transport),
        )

    def test_retries_then_succeeds_on_transient_503(self, monkeypatch):
        monkeypatch.setattr("secondlook.http_retry.time.sleep", lambda _s: None)
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) < 2:
                return httpx.Response(503, json={"error": "high demand"})
            return httpx.Response(200, json={"choices": [{"message": {"content": "final answer"}}]})

        client = self._client(httpx.MockTransport(handler))
        assert client.complete("prompt") == "final answer"
        assert len(calls) == 2

    def test_retry_exhausted_raises_llm_client_error(self, monkeypatch):
        """After the retry budget is spent, callers still get LLMClientError -- not
        a raw httpx exception -- matching how UniProtLookupError etc. already wrap
        an exhausted retry."""
        monkeypatch.setattr("secondlook.http_retry.time.sleep", lambda _s: None)
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(503, json={"error": "high demand"})

        client = self._client(httpx.MockTransport(handler))
        with pytest.raises(LLMClientError, match="OpenAI-compatible request failed"):
            client.complete("prompt")
        assert len(calls) == 3

    def test_transport_error_is_retried_then_wrapped(self, monkeypatch):
        """Connection resets (not just status codes) hit the same retry path, and
        the httpx call -- not just the status check -- must be inside the retry."""
        monkeypatch.setattr("secondlook.http_retry.time.sleep", lambda _s: None)

        class ResettingTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                raise httpx.ConnectError("reset by peer", request=request)

        client = self._client(ResettingTransport())
        with pytest.raises(LLMClientError, match="OpenAI-compatible request failed"):
            client.complete("prompt")

    def test_non_retryable_status_is_not_retried(self, monkeypatch):
        """A 400 is a real client error, not a transient blip -- one attempt only."""
        monkeypatch.setattr("secondlook.http_retry.time.sleep", lambda _s: None)
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(400, json={"error": "bad request"})

        client = self._client(httpx.MockTransport(handler))
        with pytest.raises(LLMClientError):
            client.complete("prompt")
        assert len(calls) == 1
