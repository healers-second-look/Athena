"""Plugins, skills and modes a session can attach -- issue #103, Phase 3.

Phase 3's bar is explicit: "at least one real plugin (not just a UI toggle
with no backend effect) changes actual chat behaviour when attached vs.
not". So every entry here has a real hook, and the hooks are the only way
session configuration reaches the model:

  * a SKILL rewrites the system prompt
  * a PLUGIN transforms the turn -- it can read the user's message and
    contribute context lines that land in the prompt
  * a MODE sets envelope policy (how many sources, how strict)

`variant-normalizer` is the plugin to point at when reviewing Phase 3: it
extracts gene/variant tokens from free text and both annotates the turn
and hands the parsed entities to retrieval. Attached vs not is visible in
the response payload, not just in the UI.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# Gene symbols are upper-case alphanumerics (HGNC style: EGFR, TP53, ERBB2,
# ETV6). Variant tokens are either protein-level shorthand (T790M, V600E) or
# a named class CIViC uses (Fusion, Amplification, Overexpression).
_GENE = re.compile(r"\b([A-Z][A-Z0-9]{2,7})\b")
_PROTEIN_VARIANT = re.compile(r"\b([A-Z]\d{1,4}[A-Z*]|p\.[A-Za-z]{1,3}\d{1,4}[A-Za-z*]{0,3})\b")
_NAMED_VARIANT = re.compile(
    r"\b(fusion|amplification|overexpression|deletion|insertion)\b", re.IGNORECASE
)

# Words that match the gene shape but are not genes. Without this the
# normalizer "finds" a gene in every sentence containing an acronym, which
# would make its output look impressive and be wrong.
_NOT_GENES = frozenset(
    {
        # English that happens to fit the gene shape.
        "AND",
        "THE",
        "FOR",
        "WITH",
        "NOT",
        "ANY",
        "ALL",
        "CAN",
        "HAS",
        "WAS",
        "ARE",
        "BUT",
        "HOW",
        "WHY",
        "WHO",
        "DOES",
        "WHAT",
        "WHICH",
        # Domain vocabulary that is emphatically not a gene.
        "DNA",
        "RNA",
        "FDA",
        "NCI",
        "USA",
        "CIVIC",
        "PUBMED",
        "ATHENA",
        "KG",
        "AI",
        "LLM",
        "API",
        "PET",
        "MRI",
        "IHC",
        "NGS",
        "TKI",
        "OS",
        "PFS",
        # Cancer-type acronyms. Without these, "in NSCLC" reports a gene
        # called NSCLC -- confidently, and wrongly, on every lung question.
        "NSCLC",
        "SCLC",
        "AML",
        "CML",
        "CLL",
        "GIST",
        "TNBC",
        "HCC",
        "CRC",
        "RCC",
        "HNSCC",
        "DLBCL",
        "MDS",
        "MM",
        "GBM",
    }
)


@dataclass
class Turn:
    """One chat turn as it moves through the attachment pipeline.

    Mutable on purpose: each attachment gets to add to `context_lines` and
    `notes`, and the accumulated result is what `engine.build_prompt`
    renders. `notes` is returned to the client so a reviewer can see which
    attachment did what -- Phase 3 evidence without a debugger.
    """

    message: str
    system_prompt: str
    context_lines: list[str] = field(default_factory=list)
    # Retrieved evidence, kept separate from `context_lines`. A plugin's own
    # annotation is context but it is NOT a source, and citation-guard must
    # not be fooled into reporting "sources present" because the normalizer
    # left a note.
    sources: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    max_sources: int = 8


@dataclass(frozen=True)
class Attachment:
    id: str
    label: str
    kind: str  # "skill" | "plugin" | "mode"
    description: str
    apply: Callable[[Turn], None]

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "description": self.description,
        }


def _extract_entities(message: str) -> dict[str, list[str]]:
    """Variants are matched FIRST, then excluded from gene candidates.

    Order is load-bearing, not stylistic. `T790M` satisfies the gene shape
    (`[A-Z][A-Z0-9]{2,7}`) just as well as it satisfies the protein-variant
    shape, so scanning for genes first reports EGFR *and* T790M as two
    genes and finds no variant at all -- which is exactly backwards, and
    would hand retrieval a nonexistent gene to query.
    """
    variants = list(dict.fromkeys(_PROTEIN_VARIANT.findall(message)))
    named = [
        n.capitalize() for n in dict.fromkeys(m.lower() for m in _NAMED_VARIANT.findall(message))
    ]
    claimed = set(variants)
    genes = [
        g for g in dict.fromkeys(_GENE.findall(message)) if g not in _NOT_GENES and g not in claimed
    ]
    out: dict[str, list[str]] = {}
    if genes:
        out["genes"] = genes
    if variants or named:
        out["variants"] = variants + named
    return out


def _variant_normalizer(turn: Turn) -> None:
    """Parse gene/variant tokens out of free text. The Phase 3 exhibit.

    Real effect, checkable in the response JSON: `entities` goes from empty
    to populated, a note is added, and retrieval (Phase 6, someone else's
    branch) has structured keys to query with instead of a raw sentence.
    """
    entities = _extract_entities(turn.message)
    turn.entities.update(entities)
    if entities:
        rendered = "; ".join(f"{k}: {', '.join(v)}" for k, v in entities.items())
        turn.notes.append(f"variant-normalizer parsed -> {rendered}")
        turn.context_lines.append(f"Normalized entities from the question -- {rendered}")
    else:
        turn.notes.append("variant-normalizer found no gene/variant tokens in the message")


def _citation_guard(turn: Turn) -> None:
    """Make unsourced answers say so, in the prompt itself.

    The failure this exists to prevent is the confident sourceless
    paragraph. When nothing was retrieved, the model is told to lead with
    that fact rather than to answer anyway.
    """
    if turn.sources:
        turn.system_prompt += (
            "\n\nCITATION GUARD: cite a retrieved source for every clinical claim. "
            "If a claim is not supported by the retrieved context, mark it UNSOURCED."
        )
        turn.notes.append("citation-guard active with retrieved context present")
    else:
        turn.system_prompt += (
            "\n\nCITATION GUARD: nothing was retrieved for this turn. Open the reply "
            "by stating that no sources were available, and do not assert clinical "
            "facts as though they were sourced."
        )
        turn.notes.append("citation-guard active with NO retrieved context -- reply must say so")


def _evidence_grader(turn: Turn) -> None:
    turn.system_prompt += (
        "\n\nEVIDENCE GRADING: label each cited item with its CIViC evidence level "
        "(A validated, B clinical, C case study, D preclinical, E inferential) and "
        "never present a level C-E item with the confidence of a level A item."
    )
    turn.notes.append("evidence-grader added CIViC level rubric to the system prompt")


def _mode_explore(turn: Turn) -> None:
    turn.max_sources = 12
    turn.system_prompt += (
        "\n\nMODE explore: breadth over certainty. Surface adjacent findings and "
        "name open questions."
    )


def _mode_strict(turn: Turn) -> None:
    turn.max_sources = 4
    turn.system_prompt += (
        "\n\nMODE strict-evidence: only level A/B evidence. Prefer saying the "
        "evidence is insufficient over extrapolating."
    )


def _mode_tumor_board(turn: Turn) -> None:
    turn.max_sources = 8
    turn.system_prompt += (
        "\n\nMODE tumor-board: structure the reply for a multidisciplinary board -- "
        "what is established, what is contested, what to decide next. This mode is "
        "presentational only; it is NOT the formal Board Session Orchestrator "
        "designed in issue #78 and must not be described as clinically governed."
    )


ATTACHMENTS: tuple[Attachment, ...] = (
    Attachment(
        id="variant-normalizer",
        label="Variant normalizer",
        kind="plugin",
        description="Parses gene and variant tokens out of the question into structured keys.",
        apply=_variant_normalizer,
    ),
    Attachment(
        id="citation-guard",
        label="Citation guard",
        kind="plugin",
        description="Forces the reply to declare when a claim has no retrieved source.",
        apply=_citation_guard,
    ),
    Attachment(
        id="evidence-grader",
        label="Evidence grader",
        kind="skill",
        description="Applies the CIViC A-E evidence-level rubric to every cited item.",
        apply=_evidence_grader,
    ),
    Attachment(
        id="mode:explore",
        label="Explore",
        kind="mode",
        description="Breadth-first. More sources, adjacent findings, open questions.",
        apply=_mode_explore,
    ),
    Attachment(
        id="mode:strict-evidence",
        label="Strict evidence",
        kind="mode",
        description="Level A/B only. Fewer sources, refuses to extrapolate.",
        apply=_mode_strict,
    ),
    Attachment(
        id="mode:tumor-board",
        label="Tumor board",
        kind="mode",
        description="Presentational board framing. Not the issue #78 orchestrator.",
        apply=_mode_tumor_board,
    ),
)

_BY_ID = {a.id: a for a in ATTACHMENTS}


def list_attachments() -> list[Attachment]:
    return list(ATTACHMENTS)


def get_attachment(attachment_id: str) -> Attachment | None:
    return _BY_ID.get(attachment_id)


def unknown_ids(attachment_ids: list[str]) -> list[str]:
    return [a for a in attachment_ids if a not in _BY_ID]


def apply_attachments(turn: Turn, attachment_ids: list[str]) -> Turn:
    """Run each attached hook, in registry order rather than click order.

    Registry order matters: modes set `max_sources`, and a plugin that
    trims context must see the final budget. Honouring the order the user
    happened to click checkboxes in would make the same configuration
    behave differently between two sessions.
    """
    attached = [a for a in ATTACHMENTS if a.id in set(attachment_ids)]
    for attachment in attached:
        attachment.apply(turn)
    return turn


__all__ = [
    "ATTACHMENTS",
    "Attachment",
    "Turn",
    "apply_attachments",
    "get_attachment",
    "list_attachments",
    "unknown_ids",
]
