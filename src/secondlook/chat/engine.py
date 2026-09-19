"""Chat engine -- the one function the API route calls (Phases 1-6).

`run_turn` coordinates:
- Entity extraction (via plugins / variant-normalizer)
- Knowledge graph facts (Phase 4)
- Live FalkorDB retrieval grounding (Phase 6)
- Plugin transformations (Phase 3)
- Model execution (Phase 2)
- Citation-count enforcement on the model's own output (issue #124)
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field

from secondlook.chat.knowledge import describe_context, retrieve_evidence_for_turn
from secondlook.chat.models import CONTEXT_MARKER, DEFAULT_MODEL_ID, SOURCE_MARKER, build_client
from secondlook.chat.plugins import Turn, apply_attachments

DEFAULT_SYSTEM = (
    "You are Athena, a clinical evidence synthesis assistant. You ground "
    "every claim in retrieved sources and cite them using bracketed indices "
    "like [1], [2]. Never fabricate citations. When no source exists for a "
    "claim, you state that explicitly."
)

# Issue #124: DEFAULT_SYSTEM above is only an instruction. Issue #107's fix
# (SOURCE_MARKER/CONTEXT_MARKER, `models._split_prompt`) makes it
# structurally impossible for the two mock clients to conflate context with
# sources -- they just template the prompt back. A real generative model has
# no such structural guarantee; it can still state a source count, or cite a
# bracket index, that the turn never actually retrieved. `citation_overclaim`
# below is the real backstop -- checked against `run_turn`'s output, not
# trusted from the prompt. `synthesis/citation_gate.py` plays the same role
# for the other pipeline, but its rule ("every sentence must carry a
# resolvable [ref:id] marker or be dropped") assumes the model never writes a
# legitimate uncited sentence -- chat's system prompt explicitly wants an
# honest, uncited "no source exists for this" disclaimer, so a per-sentence
# drop would shred that disclaimer along with any real fabrication. This
# checks the claim itself instead: did the model ever state or cite more
# sources than `turn.sources` actually holds. `harness/adapters/
# chat_citation.py`'s eval harness imports this exact function, not a
# lookalike copy, so the eval and the real enforcement can never drift apart.
_BRACKET_INDEX = re.compile(r"\[(\d+)\]")
_STATED_SOURCE_COUNT = re.compile(
    r"\b(\d+)\s+(?:retrieved\s+|attached\s+)?sources?\b", re.IGNORECASE
)


def citation_overclaim(content: str, source_count: int) -> str | None:
    """None if `content` never claims more sources than `source_count`,
    else a human-readable description of the overclaim.

    Two independent checks, either one enough to flag: a stated count
    ("3 retrieved sources") higher than `source_count`, or a cited bracket
    index (`[4]`) higher than `source_count`. A blunt regex check, not NLP
    -- same posture `harness/adapters/synthesis.py`'s
    SAFETY_LANGUAGE_PATTERNS documents for its own keyword check. It exists
    to catch the known #107-class failure mode cheaply, not to parse
    arbitrary prose perfectly.
    """
    stated = [int(n) for n in _STATED_SOURCE_COUNT.findall(content)]
    if stated and max(stated) > source_count:
        return f"stated {max(stated)} source(s) but only {source_count} were retrieved"
    cited = [int(n) for n in _BRACKET_INDEX.findall(content)]
    if cited and max(cited) > source_count:
        return f"cited [{max(cited)}] but only {source_count} source(s) were retrieved"
    return None


@dataclass
class TurnResult:
    """What the API sends back for one chat turn."""

    id: str
    role: str  # "assistant"
    content: str
    model_id: str
    timestamp: float
    entities: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    context_lines: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    sources_count: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def build_prompt(
    question: str, context_lines: list[str], source_lines: list[str] | None = None
) -> str:
    """Assemble the prompt the model actually sees.

    `context_lines` (plugin annotations, KG-context facts) and
    `source_lines` (genuinely retrieved evidence, `run_turn`'s numbered
    citations) render under separate markers -- see `models._split_prompt`
    for why the distinction is load-bearing, not cosmetic (issue #107).
    """
    parts = [question]
    if source_lines:
        parts.append("")
        parts.append(SOURCE_MARKER)
        for line in source_lines:
            parts.append(f"- {line}")
    if context_lines:
        parts.append("")
        parts.append(CONTEXT_MARKER)
        for line in context_lines:
            parts.append(f"- {line}")
    return "\n".join(parts)


def run_turn(
    message: str,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    attachment_ids: list[str] | None = None,
    context_id: str | None = None,
    system: str | None = None,
    sources_override: list[dict] | None = None,
    extra_context_lines: list[str] | None = None,
) -> TurnResult:
    """Execute one chat turn end-to-end (Phases 1-6).

    `sources_override` / `extra_context_lines` exist for the diff-first study's
    chat arm (issue #136): the "retrieved" sources are the case's own findings
    rather than a FalkorDB lookup, so the reviewer chats about exactly the
    content the other arms show. Passing `sources_override` skips graph
    retrieval entirely; `citation_overclaim` below still checks the model's
    output against those sources, so the #124 backstop applies unchanged.
    """
    turn = Turn(
        message=message,
        system_prompt=system or DEFAULT_SYSTEM,
    )

    # Phase 3 attachments pre-processing (e.g. variant-normalizer extracts entities)
    if attachment_ids:
        apply_attachments(turn, attachment_ids)

    # Phase 4: KG context facts
    if context_id:
        kg_lines = describe_context(context_id)
        turn.context_lines.extend(kg_lines)

    if extra_context_lines:
        turn.context_lines.extend(extra_context_lines)

    # Phase 6: Live FalkorDB evidence retrieval
    if sources_override is not None:
        retrieved_sources = list(sources_override)
    else:
        retrieved_sources = retrieve_evidence_for_turn(
            entities=turn.entities,
            context_id=context_id,
            limit=turn.max_sources,
        )
    turn.sources = retrieved_sources

    # Numbered citation lines for genuinely retrieved sources -- kept out of
    # turn.context_lines on purpose (issue #107): that list also holds
    # plugin annotations and KG-context facts, neither of which is evidence,
    # and a model counting "how many lines were in the prompt" as "how many
    # sources were retrieved" will confidently cite a plugin's own note.
    source_lines = [
        f"[{src['citation_index']}] (Level {src.get('evidence_level', 'B')}, "
        f"PMID {src.get('pmid', 'N/A')}) {src.get('title', '')}: "
        f"{src.get('summary', '')} [Ref: {src.get('citation_url', '')}]"
        for src in retrieved_sources
    ]

    # Re-apply citation-guard if attached now that sources are loaded
    if attachment_ids and "citation-guard" in attachment_ids:
        if turn.sources:
            turn.notes.append(f"retrieval attached {len(turn.sources)} live CIViC source(s)")

    # Build prompt and call model
    prompt = build_prompt(turn.message, turn.context_lines, source_lines)
    client = build_client(model_id)
    content = client.complete(prompt, system=turn.system_prompt)

    # Issue #124: the real enforcement backstop, not just DEFAULT_SYSTEM's
    # instruction. A model that overclaims has its answer withheld -- never
    # shown as if it were trustworthy -- and the violation is recorded,
    # never silently dropped, mirroring citation_gate.py's own "count and
    # return" rule for the other pipeline.
    violation = citation_overclaim(content, len(turn.sources))
    if violation:
        turn.notes.append(f"citation gate withheld model output -- {violation}")
        content = (
            f"This model's answer overstated the retrieved evidence ({violation}) "
            "and was withheld rather than shown. "
            f"Only {len(turn.sources)} source(s) were actually retrieved for this "
            "turn -- see the sources panel for what's real."
        )

    return TurnResult(
        id=str(uuid.uuid4()),
        role="assistant",
        content=content,
        model_id=model_id,
        timestamp=time.time(),
        entities=turn.entities,
        notes=turn.notes,
        context_lines=turn.context_lines,
        sources=turn.sources,
        sources_count=len(turn.sources),
    )


__all__ = ["DEFAULT_SYSTEM", "TurnResult", "build_prompt", "citation_overclaim", "run_turn"]
