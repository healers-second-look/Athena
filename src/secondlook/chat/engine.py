"""Chat engine -- the one function the API route calls (Phases 1-6).

`run_turn` coordinates:
- Entity extraction (via plugins / variant-normalizer)
- Knowledge graph facts (Phase 4)
- Live FalkorDB retrieval grounding (Phase 6)
- Plugin transformations (Phase 3)
- Model execution (Phase 2)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field

from secondlook.chat.knowledge import (
    describe_context,
    retrieve_evidence_for_turn,
)
from secondlook.chat.models import CONTEXT_MARKER, DEFAULT_MODEL_ID, SOURCE_MARKER, build_client
from secondlook.chat.plugins import Turn, apply_attachments

DEFAULT_SYSTEM = (
    "You are Athena, a clinical evidence synthesis assistant. You ground "
    "every claim in retrieved sources and cite them using bracketed indices "
    "like [1], [2]. Never fabricate citations. When no source exists for a "
    "claim, you state that explicitly."
)


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
    #: True when the evidence store could not be reached. The client MUST
    #: render this: an empty source drawer means "we searched and found
    #: nothing", and showing it during an outage reports a server failure
    #: as a clinical negative.
    retrieval_failed: bool = False
    retrieval_error: str | None = None

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
) -> TurnResult:
    """Execute one chat turn end-to-end (Phases 1-6)."""
    turn = Turn(
        message=message,
        system_prompt=system or DEFAULT_SYSTEM,
    )

    # Phase 3, pre-retrieval hooks: entity extraction, skills, and the modes
    # that set `max_sources` -- which retrieval reads, so they must run first.
    if attachment_ids:
        apply_attachments(turn, attachment_ids, phase="pre")

    # Phase 4: KG context facts
    if context_id:
        kg_lines = describe_context(context_id)
        turn.context_lines.extend(kg_lines)

    # Phase 6: Live FalkorDB evidence retrieval
    retrieval = retrieve_evidence_for_turn(
        entities=turn.entities,
        context_id=context_id,
        limit=turn.max_sources,
    )
    retrieved_sources = retrieval.sources
    turn.sources = retrieved_sources
    turn.retrieval_failed = retrieval.failed
    turn.retrieval_error = retrieval.error

    # Phase 3, post-retrieval hooks. citation-guard lives here: it branches
    # on what was actually retrieved, and running it above would hand it an
    # empty list every time.
    if attachment_ids:
        apply_attachments(turn, attachment_ids, phase="post")

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

    if turn.retrieval_failed:
        # Stated in the prompt, not just in the payload: a model handed no
        # sources and no explanation will answer from its own weights and
        # present it as evidence-backed.
        turn.context_lines.append(
            f"RETRIEVAL UNAVAILABLE -- the evidence store could not be reached "
            f"({turn.retrieval_error}). No search was performed. This is not a "
            f"finding of 'no evidence'."
        )
        turn.notes.append(f"retrieval FAILED -- {turn.retrieval_error}")
    elif turn.sources:
        turn.notes.append(f"retrieval attached {len(turn.sources)} live CIViC source(s)")
    else:
        turn.notes.append("retrieval ran and matched no sources for this turn")

    # Build prompt and call model
    prompt = build_prompt(turn.message, turn.context_lines, source_lines)
    client = build_client(model_id)
    content = client.complete(prompt, system=turn.system_prompt)

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
        retrieval_failed=turn.retrieval_failed,
        retrieval_error=turn.retrieval_error,
    )


__all__ = ["DEFAULT_SYSTEM", "TurnResult", "build_prompt", "run_turn"]
