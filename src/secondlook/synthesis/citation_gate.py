"""Citation Verification Gate -- deterministic post-generation check that
every sentence in an LLM-generated synthesis maps to a retrieved item ID,
per IMPLEMENTATION_PLAN.md SS7 and docs/api-contracts.md's citation rule.

HARD RULE, unconditional: a sentence carrying no citation marker that
resolves to an item actually present in `retrieved_items` is REMOVED and
COUNTED. The count is returned to the caller, never only a log line --
mirrors tier1/retrieval.py's `filtered_count` (invariant #1,
IMPLEMENTATION_PLAN.md SS13: "every filtered item is counted and returned").

This gate is a pure, deterministic string transform -- no LLM call, no I/O,
stdlib only -- so it can be built and fully tested against synthetic LLM
output before subsystem I's LLM integration exists (per the issue's own
rationale for splitting this out).

Expected synthesis_text shape (docs/api-contracts.md SS"Rule: every
sentence-level claim..."): sentences each ending with one or more
`[ref:<item_id>]` markers, e.g. "Drug X shows response.[ref:civic_123]".
A sentence with zero markers, or whose markers all fail to resolve, is
dropped.
"""

from __future__ import annotations

import re

_REF_MARKER = re.compile(r"\[ref:([^\]\s]+)\]")

# A sentence boundary is whitespace immediately preceded by a sentence-end
# punctuation mark or the closing bracket of a ref marker -- so a trailing
# [ref:id] chain stays attached to the sentence it terminates. Deliberately
# a plain regex, not an NLP tokenizer: the synthesis prompt contract
# constrains output to `<claim>.[ref:id]...` sentences, so this only needs
# to split on that shape, not arbitrary prose (e.g. "5.5 mg" mid-sentence
# is not a boundary this gate needs to handle, given that contract).
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?\]])\s+")


def _item_id(item: dict) -> str | None:
    """The ID a retrieved item is citable by: `citation.id` (documented
    Tier 1 shape) falling back to a top-level `id` (Tier 2 / future item
    shapes that don't carry a `citation` sub-object)."""
    citation = item.get("citation")
    if isinstance(citation, dict) and citation.get("id"):
        return str(citation["id"])
    if item.get("id"):
        return str(item["id"])
    return None


def enforce_citations(
    synthesis_text: str,
    retrieved_items: list[dict],
) -> tuple[str, list[str], int]:
    """Returns (accepted_text, cited_ids, dropped_sentence_count).

    Every sentence must carry >=1 citation marker resolving to an item
    actually present in retrieved_items. Sentences that don't are REMOVED
    and COUNTED. The count is returned and rendered -- never silently
    swallowed. Mirrors tier1/retrieval.py's existing `filtered_count`.
    """
    valid_ids = {vid for item in retrieved_items if (vid := _item_id(item)) is not None}

    accepted_sentences: list[str] = []
    cited_ids: list[str] = []
    dropped_count = 0

    for sentence in _SENTENCE_BOUNDARY.split(synthesis_text.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue

        markers = _REF_MARKER.findall(sentence)
        valid_markers = [marker for marker in markers if marker in valid_ids]

        if not valid_markers:
            dropped_count += 1
            continue

        accepted_sentences.append(sentence)
        cited_ids.extend(valid_markers)

    accepted_text = " ".join(accepted_sentences)
    return accepted_text, list(dict.fromkeys(cited_ids)), dropped_count
