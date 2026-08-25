"""Model registry for the chat surface -- issue #103, Phase 2.

Every model a session can select resolves through the SAME `LLMClient`
Protocol synthesis already uses (`secondlook.synthesis.llm_client`): one
`complete(prompt, system=...) -> str` method. `engine.py` asks this module
for a client and calls it. It never branches on which model was chosen.
That is precisely Phase 2's "one common interface, not a per-model special
case in the request handler".

The two `mock-*` models are not filler. They are the offline proof that
the abstraction is real: same interface, same prompt, visibly different
output. They also let the whole chat surface run -- and be tested -- with
no API key and no network, which is the same posture
`ATHENA_LLM_ENABLED=false` gives the synthesis path.

HARD RULE inherited from llm_client.py: no open-weight model is named or
recommended as a default here. `openai-compatible` is whatever
ATHENA_LLM_BASE_URL is serving; this module does not know or care.
"""

from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass

from secondlook.synthesis.llm_client import (
    DEFAULT_ANTHROPIC_MODEL,
    AnthropicClient,
    LLMClient,
    LLMClientError,
    OpenAICompatibleClient,
)


@dataclass(frozen=True)
class ModelSpec:
    """What the picker shows and what the router needs to build a client.

    `available` is computed from configuration, never assumed. A model the
    deployment cannot actually reach is still listed -- greyed out with a
    reason -- rather than hidden, so a user who expects Claude and does not
    see it gets an explanation instead of a silently shorter list.
    """

    id: str
    label: str
    provider: str
    description: str
    available: bool
    unavailable_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "provider": self.provider,
            "description": self.description,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


class MockOutlineClient:
    """Deterministic. Answers in structured sections with source counts.

    Reads the prompt it is handed rather than ignoring it, so attaching a
    retrieval source or a knowledge graph visibly changes what comes back
    -- which is what makes it usable as evidence for Phases 3, 4 and 6
    instead of a decorative stub.
    """

    model = "mock-outline"

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        question, context_lines, source_lines = _split_prompt(prompt)
        parts = [f"## On: {question}", ""]
        outage = _retrieval_outage(context_lines)
        if outage:
            parts.append("### Evidence search could not be run")
            parts.append(f"- {outage}")
            parts.append("- This is NOT a finding that no evidence exists. Nothing was searched.")
        elif source_lines:
            parts.append(f"### What the {len(source_lines)} attached source(s) say")
            parts.extend(f"- {line}" for line in source_lines)
        else:
            parts.append("### No sources matched")
            parts.append(
                "- The evidence search ran and matched nothing for this question. "
                "Attach a retrieval source or a knowledge graph to widen it."
            )
        # Plugin/KG-context annotations, not evidence -- kept visibly separate
        # so they never inflate the source count above. The outage line is
        # excluded: it is already the lede, and repeating it here made the
        # reply state the same failure twice.
        extra = [line for line in context_lines if line is not outage]
        if extra:
            parts.append("")
            parts.append("### Additional context (not sources)")
            parts.extend(f"- {line}" for line in extra)
        parts += [
            "",
            "### Caveats",
            "- Deterministic offline model. It restates retrieved context; it does "
            "not reason over it and must not be read as clinical advice.",
        ]
        return "\n".join(parts)


class MockTerseClient:
    """Deterministic. Same inputs as MockOutlineClient, deliberately
    different shape: a couple of prose sentences, no headings.

    Phase 2 asks for two models that produce *visibly* different output
    from the same request. Outline-vs-prose is that difference, and it is
    visible in a screenshot without squinting at token counts.
    """

    model = "mock-terse"

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        question, context_lines, source_lines = _split_prompt(prompt)
        outage = _retrieval_outage(context_lines)
        if outage:
            return (
                f"No answer attempted for {question!r}: the evidence search could not "
                f"be run ({outage}). Nothing was searched, so this is not a finding "
                "that no evidence exists. Retry once the evidence store is reachable."
            )
        if not source_lines:
            return (
                f"No grounded answer available for {question!r}: the evidence search "
                "ran and matched zero sources. Attach CIViC, literature, or a "
                "knowledge graph and ask again."
            )
        head = source_lines[0]
        rest = len(source_lines) - 1
        tail = f" {rest} further source(s) were retrieved." if rest else ""
        return textwrap.fill(
            f"Across {len(source_lines)} retrieved source(s) for {question!r}, the "
            f"strongest is: {head}.{tail} Deterministic offline model -- restated "
            "evidence, not clinical advice.",
            width=100,
        )


CONTEXT_MARKER = "### Retrieved context"
SOURCE_MARKER = "### Retrieved sources"

#: `engine.run_turn` prefixes a context line with this when the evidence store
#: could not be reached. The mocks lead with it rather than printing their
#: usual "no sources attached -- attach a retrieval source", which during an
#: outage blames the user for a server failure and reads as a clinical
#: negative. A real model gets the same fact via the CITATION GUARD system
#: text; the mocks ignore `system`, so they read it from here.
RETRIEVAL_FAILED_MARKER = "RETRIEVAL UNAVAILABLE"


def _retrieval_outage(context_lines: list[str]) -> str | None:
    """The outage line, if `engine.run_turn` put one in the context block."""
    return next((line for line in context_lines if line.startswith(RETRIEVAL_FAILED_MARKER)), None)


def _bullets(text: str) -> list[str]:
    return [
        line.strip().lstrip("- ").strip()
        for line in text.splitlines()
        if line.strip().startswith("-")
    ]


def _split_prompt(prompt: str) -> tuple[str, list[str], list[str]]:
    """Pull the question, context bullets, and source bullets back apart.

    Two distinct sections, not one: `SOURCE_MARKER` bullets are genuinely
    retrieved evidence (`engine.run_turn`'s numbered citations);
    `CONTEXT_MARKER` bullets are everything else -- a plugin's own
    annotation, KG-context facts -- explicitly NOT sources (see
    `plugins.Turn`'s docstring). Conflating the two is exactly how a mock
    model previously ended up claiming a retrieved source existed when
    zero were retrieved (issue #107) -- a plugin's own note isn't
    evidence just because it appears in the prompt.

    `engine.build_prompt` is the only writer of this format, so the two
    live or die together; `tests/chat/test_models.py` pins the round trip
    so a change to one that forgets the other fails loudly rather than
    quietly producing sourceless answers.

    Markers are located independently (not via chained `.partition()`) so
    either can appear, in either order, or be entirely absent -- a prompt
    with sources but no other context must still find its sources.
    """
    context_idx = prompt.find(CONTEXT_MARKER)
    source_idx = prompt.find(SOURCE_MARKER)
    marker_positions = [i for i in (context_idx, source_idx) if i != -1]
    question_end = min(marker_positions) if marker_positions else len(prompt)
    question = prompt[:question_end]
    question_text = question.strip().splitlines()[-1].strip() if question.strip() else ""

    def _section(start: int, other: int) -> list[str]:
        if start == -1:
            return []
        end = other if other != -1 and other > start else len(prompt)
        marker_len = len(CONTEXT_MARKER) if start == context_idx else len(SOURCE_MARKER)
        return _bullets(prompt[start + marker_len : end])

    context_lines = _section(context_idx, source_idx)
    source_lines = _section(source_idx, context_idx)
    return question_text, context_lines, source_lines


def _anthropic_available() -> tuple[bool, str | None]:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True, None
    return False, "ANTHROPIC_API_KEY is not set in this deployment."


def _openai_compatible_available() -> tuple[bool, str | None]:
    missing = [
        name for name in ("ATHENA_LLM_BASE_URL", "ATHENA_LLM_MODEL") if not os.environ.get(name)
    ]
    if missing:
        return False, f"{' and '.join(missing)} not set in this deployment."
    return True, None


def list_models() -> list[ModelSpec]:
    """Every model this deployment can offer, availability computed live.

    Not cached: an operator who exports ANTHROPIC_API_KEY and restarts
    uvicorn --reload should see Claude become selectable without a code
    change, and a test that monkeypatches the env should see it too.
    """
    anthropic_ok, anthropic_why = _anthropic_available()
    openai_ok, openai_why = _openai_compatible_available()
    return [
        ModelSpec(
            id="mock-outline",
            label="Athena Outline (offline)",
            provider="mock",
            description="Deterministic. Structured sections over retrieved sources.",
            available=True,
        ),
        ModelSpec(
            id="mock-terse",
            label="Athena Terse (offline)",
            provider="mock",
            description="Deterministic. Two sentences of prose, same inputs.",
            available=True,
        ),
        ModelSpec(
            id="anthropic",
            label=f"Anthropic ({os.environ.get('ATHENA_LLM_MODEL') or DEFAULT_ANTHROPIC_MODEL})",
            provider="anthropic",
            description="Hosted Claude via the Anthropic API.",
            available=anthropic_ok,
            unavailable_reason=anthropic_why,
        ),
        ModelSpec(
            id="openai-compatible",
            label=f"Self-hosted ({os.environ.get('ATHENA_LLM_MODEL') or 'unconfigured'})",
            provider="openai_compatible",
            description=(
                "Any server speaking OpenAI chat-completions -- vLLM, Ollama, TGI. "
                "Which weights are behind the URL is a deployment choice."
            ),
            available=openai_ok,
            unavailable_reason=openai_why,
        ),
    ]


DEFAULT_MODEL_ID = "mock-outline"


def get_model_spec(model_id: str) -> ModelSpec | None:
    return next((spec for spec in list_models() if spec.id == model_id), None)


def build_client(model_id: str) -> LLMClient:
    """model id -> an `LLMClient`. The only place model choice is decoded.

    Raises `LLMClientError` for an unknown or unconfigured id rather than
    silently falling back to a mock: a session that believes it is talking
    to Claude and is quietly served a deterministic stub would make every
    screenshot taken of it a lie.
    """
    spec = get_model_spec(model_id)
    if spec is None:
        known = ", ".join(s.id for s in list_models())
        raise LLMClientError(f"unknown model {model_id!r}; known models are {known}")
    if not spec.available:
        raise LLMClientError(f"model {model_id!r} is not configured: {spec.unavailable_reason}")
    if spec.provider == "mock":
        return MockOutlineClient() if model_id == "mock-outline" else MockTerseClient()
    if spec.provider == "anthropic":
        return AnthropicClient()
    return OpenAICompatibleClient()


__all__ = [
    "CONTEXT_MARKER",
    "DEFAULT_MODEL_ID",
    "RETRIEVAL_FAILED_MARKER",
    "SOURCE_MARKER",
    "ModelSpec",
    "MockOutlineClient",
    "MockTerseClient",
    "build_client",
    "get_model_spec",
    "list_models",
]
