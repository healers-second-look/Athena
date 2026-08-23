"""The Tier 1 integration seam — contracts Tier 2 depends on, plus placeholders.

Tier 1 (evidence retrieval + the FalkorDB knowledge graph) is owned and built
elsewhere; see `tier1-implementation-spec.md`. This module exists so Tier 2 can
be built, tested, and demoed *now* against the shape Tier 1 will eventually
provide, and so that dropping the real implementation in is a substitution
rather than a rewrite.

Nothing here is a Tier 1 implementation. Every placeholder is inert, obviously
named, and reports `is_placeholder = True`.

## The two directions of the boundary

**Tier 1 → Tier 2 (activation).** `tier1-implementation-spec.md` §6 owns the
rule deciding whether Tier 2 runs at all. Tier 2 must not reimplement it — the
thresholds there are explicitly flagged as untuned, and duplicating them would
create two divergent copies. `ActivationPolicy` pins the interface; the real
one arrives with Tier 1.

**Tier 2 → Tier 1 (graph).** Tier 2 emits `StructuralSignal` objects for the
graph. Per `tier2-implementation-spec.md` §7, Tier 2 **returns objects rather
than writing to FalkorDB directly** — that keeps this repo's test suite free of
a live database and matches every existing module's pattern of returning
structured results rather than performing side effects. `GraphSink` is the
handoff point; wiring it to a real `falkordb` client is Tier 1's call, and no
`falkordb` dependency is added here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

#: §6's activation states. `manual_override` covers the UI toggle letting a
#: doctor request Tier 2 even on a strong hit.
ActivationState = Literal["strong_hit", "weak_hit", "no_hit", "manual_override"]


@dataclass(frozen=True)
class Tier1ResultItem:
    """One documented-evidence item, per `api-contracts.md` "Tier 1 result item".

    Pinned here so Tier 2's assembly and any shared response builder agree on the
    shape before Tier 1 exists.

    Hard rule from that contract: an item with no `citation_url` must never be
    constructed. `__post_init__` enforces it rather than trusting call sites.
    """

    source: Literal["CIViC", "ClinicalTrials.gov", "CTRI", "PubMed"]
    evidence_level: str
    citation_id: str
    citation_url: str
    summary: str
    drug: str | None = None
    trial_status: str | None = None
    type: Literal["documented"] = "documented"

    def __post_init__(self) -> None:
        if not self.citation_url or not self.citation_url.strip():
            raise ValueError(
                "Tier1ResultItem requires a non-empty citation_url — api-contracts.md "
                "forbids constructing an evidence item without one."
            )


@dataclass(frozen=True)
class ActivationDecision:
    """Tier 1's verdict on whether Tier 2 should run, and why."""

    state: ActivationState
    should_run_tier2: bool
    reason: str
    #: What Tier 1 found, if anything. Empty on `no_hit`.
    tier1_results: list[Tier1ResultItem] = field(default_factory=list)
    #: True when this came from a placeholder rather than real Tier 1 retrieval.
    is_placeholder: bool = False


@runtime_checkable
class ActivationPolicy(Protocol):
    """Implemented by Tier 1. Tier 2 only ever consumes the decision."""

    def decide(
        self, *, gene: str, mutation: str, cancer_type: str | None
    ) -> ActivationDecision: ...


class AlwaysRunTier2Policy:
    """Placeholder activation policy: always runs Tier 2, never claims a Tier 1 hit.

    Chosen deliberately over a policy that fabricates plausible Tier 1 evidence.
    Returning `no_hit` with an empty result list is *honest* — Tier 1 genuinely
    hasn't looked — whereas synthetic evidence items would violate the
    system-wide "never state a fact you didn't retrieve" rule and would be
    indistinguishable from real retrieval downstream.

    Replace with Tier 1's real `ActivationPolicy` when it lands. Callers can
    detect this via `ActivationDecision.is_placeholder`.
    """

    is_placeholder = True

    def decide(self, *, gene: str, mutation: str, cancer_type: str | None) -> ActivationDecision:
        return ActivationDecision(
            state="no_hit",
            should_run_tier2=True,
            reason=(
                "Tier 1 is not wired up in this repo; this placeholder policy runs Tier 2 "
                "unconditionally and reports no documented evidence rather than inventing any."
            ),
            tier1_results=[],
            is_placeholder=True,
        )


@runtime_checkable
class GraphSink(Protocol):
    """Persists graph-ready nodes. Implemented by Tier 1 against FalkorDB."""

    def emit(self, signal: object) -> None: ...


class CollectingGraphSink:
    """Placeholder `GraphSink` that accumulates signals in memory.

    Useful for tests and for inspecting exactly what would be written once the
    real graph exists. Adds no database dependency.
    """

    is_placeholder = True

    def __init__(self) -> None:
        self.signals: list[object] = []

    def emit(self, signal: object) -> None:
        self.signals.append(signal)
