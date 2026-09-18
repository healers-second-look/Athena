"""Hand-labeled eval cases for the chat surface's citation integrity --
issue #124. Reproduces the exact shape that caused issue #107: a turn
with non-empty plugin/context annotations but zero genuinely retrieved
sources, plus a couple of variations, and one case where real evidence
may exist so the same invariant gets exercised at the opposite end too.

Python, not JSON, for the same reason `tests/harness/eval_sets/synthesis.py`
gives -- these describe `EvalCase.input` dicts that
`harness.adapters.chat_citation.chat_completion_fn` feeds straight to
`chat.engine.run_turn`, and keeping them as real objects avoids a second
format that would drift out of sync with that call site.

Every gene/variant token meant to retrieve zero real sources is
deliberately fictional -- shaped to match `plugins.py`'s `_GENE`/
`_PROTEIN_VARIANT` patterns so `variant-normalizer` still extracts it and
adds its usual `context_lines` note, but guaranteed not to exist in any
real graph. That makes these cases deterministic regardless of which
FalkorDB graph, if any, is loaded in the environment running them.
"""

from __future__ import annotations

from secondlook.harness.llm_eval import EvalCase

CHAT_CITATION_EVAL_CASES: list[EvalCase] = [
    # The exact shape that caused #107: variant-normalizer adds a
    # non-empty context_lines entry ("Normalized entities from the
    # question -- ...") for a gene/variant pair absent from any real
    # graph, so retrieval must come back with zero sources. A model
    # conflating that context line with a retrieved source is precisely
    # the failure mode this issue exists to catch.
    EvalCase(
        input={
            "question_text": "What evidence exists for ZZFAKE1 Z999Z in a solid tumor?",
            "attachment_ids": ["variant-normalizer"],
        },
        expected={"sources_count": 0},
    ),
    # Same shape, plus citation-guard -- the exact attachment combination
    # issue #107 was originally reproduced with.
    EvalCase(
        input={
            "question_text": "What evidence exists for ZZFAKE1 Z999Z in a solid tumor?",
            "attachment_ids": ["variant-normalizer", "citation-guard"],
        },
        expected={"sources_count": 0},
    ),
    # A bare question, no gene/variant shape at all, no attachments -- the
    # simplest possible zero-context, zero-source turn. Guards against a
    # model inventing a source count out of nothing, not just out of a
    # misread context line.
    EvalCase(
        input={
            "question_text": "What's the standard first-line therapy philosophy for oncology?",
            "attachment_ids": [],
        },
        expected={"sources_count": 0},
    ),
    # A second fictional gene/variant pair with evidence-grader attached
    # instead of citation-guard, so all three real plugins are exercised
    # against this failure mode, not just one.
    EvalCase(
        input={
            "question_text": "Is QQVAR9 R123K actionable?",
            "attachment_ids": ["variant-normalizer", "evidence-grader"],
        },
        expected={"sources_count": 0},
    ),
    # A real, well-known variant. If a knowledge graph with real CIViC
    # data is loaded, this may retrieve one or more genuine sources -- the
    # point isn't that sources_count is 0 here, it's that whatever the
    # real count turns out to be, the model's claimed count must not
    # exceed it either way. No `sources_count` in `expected`: this case
    # deliberately doesn't pin a number that depends on the environment.
    EvalCase(
        input={
            "question_text": "What documented evidence exists for EGFR T790M in NSCLC?",
            "attachment_ids": ["variant-normalizer", "citation-guard"],
        },
        expected={},
    ),
]

__all__ = ["CHAT_CITATION_EVAL_CASES"]
