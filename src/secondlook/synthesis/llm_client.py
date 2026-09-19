"""LLM client abstraction -- hosted API or self-hosted, same Protocol.

HARD RULE: no specific open-weight model is picked or hardcoded as a
default. Which models produce adequate citation-constrained synthesis is
unvalidated (issue #10). This module makes any OpenAI-compatible-serving
model swappable via config; it does not recommend one.

`ATHENA_LLM_ENABLED` is read in exactly one place: `get_llm_client()`.
`generate_synthesis()` takes an already-resolved `LLMClient | None` so
offline tests pass `llm_client=None` rather than monkeypatching env vars
to exercise the disabled path.

The `anthropic` SDK is imported inside `AnthropicClient.complete`, never
at module top and never in `__init__` -- a caller that never calls
`.complete()` (every offline test; every `ATHENA_LLM_ENABLED=false`
deployment) never pays for it (ARCHITECTURE.md §8 invariant #10).
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx

from secondlook.http_retry import with_retry
from secondlook.tier1.graph_schema import assert_valid

LLM_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai_compatible"})
DEFAULT_PROVIDER = "anthropic"
# Current documented default for the hosted path only. Not a
# recommendation for the open-weight path -- that model is chosen per
# deployment via ATHENA_LLM_MODEL and is unvalidated here.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"


class LLMClientError(RuntimeError):
    """Transport, HTTP, or payload failure from an LLM backend.

    Caught at the `generate_synthesis()` call site. Never a bare except.
    """


class LLMClient(Protocol):
    def complete(self, prompt: str, *, system: str | None = None) -> str: ...


def llm_enabled() -> bool:
    """True unless ATHENA_LLM_ENABLED is `false` or `0` (case-insensitive).

    Default true, matching IMPLEMENTATION_PLAN.md §12's invocation
    `ATHENA_LLM_ENABLED=false python -m ...` as the *off* switch.
    """
    raw = os.environ.get("ATHENA_LLM_ENABLED", "true")
    return raw.strip().lower() not in {"false", "0"}


class AnthropicClient:
    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        client=None,
    ) -> None:
        self.model = model or os.environ.get("ATHENA_LLM_MODEL") or DEFAULT_ANTHROPIC_MODEL
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = client

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        import anthropic

        sdk = self._client
        if sdk is None:
            if self._api_key:
                sdk = anthropic.Anthropic(api_key=self._api_key)
            else:
                sdk = anthropic.Anthropic()
            self._client = sdk
        try:
            message = sdk.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system or "",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            raise LLMClientError(f"Anthropic request failed: {exc}") from exc
        parts = [block.text for block in message.content if getattr(block, "text", None)]
        if not parts:
            raise LLMClientError("Anthropic response contained no text blocks")
        return "".join(parts)


class OpenAICompatibleClient:
    """Any server speaking the OpenAI chat-completions wire format.

    vLLM, Ollama, text-generation-inference, etc. The model name is
    whatever the server exposes -- this client does not know or care
    which weights are behind the URL.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("ATHENA_LLM_BASE_URL") or "").rstrip("/")
        self.model = model or os.environ.get("ATHENA_LLM_MODEL")
        self._api_key = (
            api_key or os.environ.get("ATHENA_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        )
        self._client = client
        if not self.base_url:
            raise LLMClientError("ATHENA_LLM_BASE_URL is required for openai_compatible")
        if not self.model:
            raise LLMClientError("ATHENA_LLM_MODEL is required for openai_compatible")

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        url = f"{self.base_url}/chat/completions"

        # Both the request and the status check live inside `attempt`, so
        # connection resets and timeouts -- which are raised by the request
        # call, not by raise_for_status() -- are retried and then converted
        # to LLMClientError rather than escaping as raw httpx errors.
        def attempt() -> httpx.Response:
            if self._client is not None:
                response = self._client.post(
                    url,
                    json={"model": self.model, "messages": messages},
                    headers=headers,
                    timeout=180.0,
                )
            else:
                response = httpx.post(
                    url,
                    json={"model": self.model, "messages": messages},
                    headers=headers,
                    timeout=180.0,
                )
            response.raise_for_status()
            return response

        try:
            response = with_retry(attempt)
            payload = response.json()
            return payload["choices"][0]["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(f"OpenAI-compatible request failed for {url}") from exc


def get_llm_client() -> LLMClient | None:
    """Single read of ATHENA_LLM_ENABLED / ATHENA_LLM_PROVIDER.

    Returns None when the flag is off -- generate_synthesis then takes
    the deterministic citable-items path.
    """
    if not llm_enabled():
        return None
    provider = os.environ.get("ATHENA_LLM_PROVIDER") or DEFAULT_PROVIDER
    assert_valid(provider, LLM_PROVIDERS, "ATHENA_LLM_PROVIDER")
    if provider == "anthropic":
        return AnthropicClient()
    return OpenAICompatibleClient()
