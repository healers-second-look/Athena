"""Real Tier 1 backing for the contracts in `tier1_contract.py`.

`tier1_contract.py` pins the *shape* of the Tier 1 boundary and ships inert
placeholders so Tier 2 can run with no Tier 1 present. This module is the other
half: it implements those same Protocols against the actual Tier 1
implementation (`secondlook.tier1`, from the Athena_Tier_1 repo).

## Why every Tier 1 import is lazy

Tier 1 declares a dependency on Tier 2 (it reuses `mutation_validation.py` and
`uniprot.py`). If Tier 2 imported `secondlook.tier1` at module scope, the two
packages would import-cycle, and — worse — Tier 2 would stop working in any
environment where Tier 1 is not installed. That would defeat the entire point
of the seam. So `secondlook.tier1.*` is imported *inside* the functions that
need it, exactly as Tier 1 itself imports `falkordb` lazily in
`graph_connection.connect_graph()`.

The practical consequence: `import secondlook.tier1_adapter` always succeeds.
Only *calling* a method here requires Tier 1, and the error when it is missing
names the reason rather than surfacing a bare ImportError.

## The activation rule is Tier 1's, not ours

`tier1-retrieval.md` §Activation owns the thresholds. They are reproduced in
`_classify` as executable code and nowhere else in this repo — Tier 2 must not
grow a second, drifting copy. The spec also flags them as **initial values to
be tuned against real query logs**, so `ActivationDecision.reason` records
which clause fired, making the hit-rate distribution recoverable from output
rather than requiring a re-run with logging turned on.
"""

from __future__ import annotations

from dataclasses import dataclass

from secondlook.graph import StructuralSignal
from secondlook.tier1_contract import ActivationDecision, Tier1ResultItem

#: §Activation: "≥1 CIViC evidence item at level A or B for this exact variant".
#: CIViC grades A (validated) through E (inferential); A/B are the two levels
#: the spec treats as strong enough to stand without a computed signal.
STRONG_EVIDENCE_LEVELS = frozenset({"A", "B"})

#: Raised as the message when Tier 1 is not importable. Named so tests can
#: assert on it without matching an ImportError string that varies by platform.
TIER1_MISSING_MESSAGE = (
    "Tier 1 (secondlook.tier1) is not installed in this environment. Install the "
    "Athena_Tier_1 package alongside Tier 2 with "
    "`pip install -e . --config-settings editable_mode=compat` in BOTH repos, or "
    "use tier1_contract.AlwaysRunTier2Policy to run Tier 2 standalone."
)


def _import_retrieval():
    """Import Tier 1's retrieval module, or raise with an actionable message."""
    try:
        from secondlook.tier1 import retrieval
    except ImportError as exc:
        raise Tier1UnavailableError(TIER1_MISSING_MESSAGE) from exc
    return retrieval


class Tier1UnavailableError(RuntimeError):
    """Tier 1 was asked for but is not installed. Distinct from a query failure."""


def to_result_item(row: dict) -> Tier1ResultItem:
    """Convert one Tier 1 retrieval dict into the `api-contracts.md` dataclass.

    Tier 1's `retrieval._row_to_item` returns a dict with a nested
    `{"citation": {"id", "url"}}`; `Tier1ResultItem` flattens that to
    `citation_id` / `citation_url` because the API contract does. Doing the
    flattening in one place keeps the two representations from being manually
    re-derived at every call site.

    `Tier1ResultItem.__post_init__` rejects a missing `citation_url`, so a row
    that somehow escaped Tier 1's own `if not citation_url: return None` filter
    still cannot become a result item here.
    """
    citation = row.get("citation") or {}
    return Tier1ResultItem(
        source=row["source"],
        evidence_level=row["evidence_level"],
        citation_id=str(citation.get("id", "")),
        citation_url=citation.get("url", ""),
        summary=row.get("summary") or "",
        drug=row.get("drug"),
        trial_status=row.get("trial_status"),
    )


@dataclass(frozen=True)
class Tier1Retrieval:
    """What a retrieval pass found, before the activation rule is applied."""

    items: tuple[Tier1ResultItem, ...]
    filtered_count: int
    mode: str

    @property
    def strong_levels(self) -> tuple[str, ...]:
        return tuple(
            i.evidence_level for i in self.items if i.evidence_level in STRONG_EVIDENCE_LEVELS
        )


class Tier1RetrievalPolicy:
    """`ActivationPolicy` backed by the live Tier 1 knowledge graph.

    Substitutable for `tier1_contract.AlwaysRunTier2Policy` — same Protocol,
    same return type — which is what the seam was built for.

    `graph` is injectable so tests can pass a fake with a `.query()` method and
    never need FalkorDB running; that is the same affordance Tier 1's own unit
    tests rely on.
    """

    is_placeholder = False

    def __init__(self, graph=None, *, include_relaxed: bool = True) -> None:
        self._graph = graph
        self._include_relaxed = include_relaxed

    def decide(
        self,
        *,
        gene: str,
        mutation: str | None = None,
        cancer_type: str | None = None,
        variant_name: str | None = None,
        drug_class: str | None = None,
        manual_override: bool = False,
    ) -> ActivationDecision:
        """Apply `tier1-retrieval.md` §Activation to a live retrieval.

        Signature deliberately matches `ActivationPolicy.decide` — keyword-only
        `gene` / `mutation` / `cancer_type` — so this is a drop-in replacement
        for `AlwaysRunTier2Policy`. `mutation` is the protein-level HGVS Tier 1
        calls `hgvs_p`; `cancer_type` is its `disease`. The extra keywords are
        optional additions, so the Protocol is still satisfied.
        """
        if manual_override:
            # The UI's "run Tier 2 anyway" button. Checked before querying:
            # the answer does not depend on what Tier 1 holds, and a doctor
            # waiting on a graph round-trip for a decision already made is
            # latency for nothing.
            return ActivationDecision(
                state="manual_override",
                should_run_tier2=True,
                reason="Clinician requested Tier 2 explicitly (UI override).",
                tier1_results=[],
                is_placeholder=False,
            )

        found = self.retrieve(
            gene,
            mutation,
            variant_name=variant_name,
            disease=cancer_type,
            drug_class=drug_class,
        )
        return self._classify(found)

    def retrieve(
        self,
        gene: str,
        hgvs_p: str | None = None,
        *,
        variant_name: str | None = None,
        disease: str | None = None,
        drug_class: str | None = None,
    ) -> Tier1Retrieval:
        """Mode 1, falling back to Mode 2 — Tier 1's own documented order.

        `retrieve_relaxed` is only called when `retrieve_exact` came back empty;
        its docstring says it is "only meaningful to call when retrieve_exact()
        returned no items", and it is passed the same variant key so its path
        (a) excludes the right variant.
        """
        retrieval = _import_retrieval()
        exact = retrieval.retrieve_exact(gene, hgvs_p, variant_name=variant_name, graph=self._graph)
        if exact.items:
            return Tier1Retrieval(
                items=tuple(to_result_item(r) for r in exact.items),
                filtered_count=exact.filtered_count,
                mode="exact",
            )
        if not self._include_relaxed:
            return Tier1Retrieval(items=(), filtered_count=exact.filtered_count, mode="exact")

        relaxed = retrieval.retrieve_relaxed(
            gene,
            hgvs_p,
            disease,
            variant_name=variant_name,
            drug_class=drug_class,
            graph=self._graph,
        )
        return Tier1Retrieval(
            items=tuple(to_result_item(r) for r in relaxed.items),
            # Both passes filtered rows; reporting only the second would
            # under-count what was dropped on the way to this answer.
            filtered_count=exact.filtered_count + relaxed.filtered_count,
            mode="relaxed" if relaxed.items else "none",
        )

    @staticmethod
    def _classify(found: Tier1Retrieval) -> ActivationDecision:
        """The §Activation thresholds, as executable code. Single source of truth.

        Note what is deliberately *not* here: clinical-trial matching. The spec's
        strong-hit clause is "level A/B evidence **OR** ≥1 recruiting trial", and
        Tier 1 as built loads CIViC and PubMed but not ClinicalTrials.gov/CTRI.
        Treating "no trial data" as "no trial" would silently convert an
        unimplemented source into a negative finding — so the trial half of the
        clause is unevaluated, and `reason` says so on every strong/weak
        decision rather than implying the full rule ran.
        """
        trial_caveat = " Trial half of the strong-hit rule not evaluated (no trial source loaded)."

        if not found.items:
            return ActivationDecision(
                state="no_hit",
                should_run_tier2=True,
                reason=(
                    "No documented evidence found in Tier 1 (Modes 1 and 2 both empty"
                    f", {found.filtered_count} row(s) filtered for missing citation)."
                ),
                tier1_results=[],
                is_placeholder=False,
            )

        strong = found.strong_levels
        if found.mode == "exact" and strong:
            return ActivationDecision(
                state="strong_hit",
                should_run_tier2=False,
                reason=(
                    f"{len(strong)} CIViC evidence item(s) at level "
                    f"{'/'.join(sorted(set(strong)))} "
                    f"for this exact variant." + trial_caveat
                ),
                tier1_results=list(found.items),
                is_placeholder=False,
            )

        if found.mode == "exact":
            levels = "/".join(sorted({i.evidence_level for i in found.items}))
            return ActivationDecision(
                state="weak_hit",
                should_run_tier2=True,
                reason=(
                    f"Exact-variant evidence found but only at level {levels} "
                    f"(strong requires A or B)." + trial_caveat
                ),
                tier1_results=list(found.items),
                is_placeholder=False,
            )

        return ActivationDecision(
            state="weak_hit",
            should_run_tier2=True,
            reason=(
                f"No exact-variant evidence; {len(found.items)} item(s) via Tier 1 Mode 2 "
                "relaxation (same gene / same disease+drug class)." + trial_caveat
            ),
            tier1_results=list(found.items),
            is_placeholder=False,
        )


class FalkorDBGraphSink:
    """`GraphSink` that persists `StructuralSignal`s into Tier 1's FalkorDB graph.

    Writes the §4 shape both repos agreed on::

        (Variant)-[:HAS_COMPUTATIONAL_SIGNAL]->(StructuralSignal)
        (StructuralSignal)-[:PREDICTS_BINDING_CHANGE {...}]->(Drug)

    Two deliberate choices:

    **`MERGE` on the Variant and Drug, `CREATE` on the signal.** A variant or
    drug may already exist from the CIViC load and must not be duplicated. A
    structural signal is a point-in-time computation — a second run against
    newer PDB data is a *new* signal, not an edit of the old one, and
    overwriting would destroy the provenance trail that `computed_at` /
    `pipeline_version` exist to keep.

    **Provenance via Tier 1's own helper.** `with_provenance` is imported from
    Tier 1 rather than reimplemented, so a signal node can never be written
    without source/source_version/retrieved_at, and cannot drift from how every
    other node in the graph records the same thing.
    """

    is_placeholder = False

    #: `source` recorded on the node's provenance. Not "CIViC" — this node is
    #: computed by Tier 2, and labelling it with an evidence database is exactly
    #: the computed/documented conflation `graph.py` is built to prevent.
    PROVENANCE_SOURCE = "SecondLook Tier 2"

    #: CIViC writes Variant.hgvs_p RefSeq-prefixed and three-letter
    #: ("NP_005148.2:p.Thr315Ile"); Tier 2 computes the bare form
    #: ("p.Thr315Ile"). Merging on the bare string therefore matches nothing
    #: and silently creates a SECOND Variant node for a variant the graph
    #: already has — orphaned from its Gene, invisible to every Tier 1 query,
    #: and indistinguishable from a genuinely new variant. Verified against the
    #: live graph on 2026-08-22: MERGE on "p.Arg273His" matched 0 of the 1
    #: existing TP53 R273H node.
    #:
    #: So resolution is a lookup, not a merge: find the gene's existing variant
    #: whose hgvs_p equals or ends with ours, and only create one when there is
    #: genuinely no match.
    _FIND_VARIANT = """
    MATCH (gn:Gene {symbol: $gene})-[:HAS_VARIANT]->(v:Variant)
    WHERE v.hgvs_p = $hgvs_p OR v.hgvs_p ENDS WITH $hgvs_suffix
    RETURN id(v) AS vid
    LIMIT 1
    """

    #: Only reached when the gene has no matching variant. Links to the Gene so
    #: the new node is reachable by the same traversals CIViC's variants are,
    #: and carries provenance saying Tier 2 minted it.
    _CREATE_VARIANT = """
    MERGE (gn:Gene {symbol: $gene})
    CREATE (v:Variant {hgvs_p: $hgvs_p, gene_symbol: $gene})
    SET v.source = $source, v.retrieved_at = $retrieved_at, v.source_version = $source_version
    CREATE (gn)-[:HAS_VARIANT]->(v)
    RETURN id(v) AS vid
    """

    _WRITE = """
    MATCH (v:Variant) WHERE id(v) = $vid
    MERGE (d:Drug {name: $drug})
    CREATE (s:StructuralSignal)
    SET s += $signal_props
    SET s.edge_snapshot = $edge_json
    CREATE (v)-[:HAS_COMPUTATIONAL_SIGNAL]->(s)
    CREATE (s)-[:PREDICTS_BINDING_CHANGE]->(d)
    RETURN id(s) AS signal_id
    """

    def __init__(self, graph=None) -> None:
        self._graph = graph

    def _connect(self):
        if self._graph is not None:
            return self._graph
        try:
            from secondlook.tier1.graph_connection import connect_graph
        except ImportError as exc:
            raise Tier1UnavailableError(TIER1_MISSING_MESSAGE) from exc
        self._graph = connect_graph()
        return self._graph

    def emit(self, signal: StructuralSignal) -> None:
        """Persist one signal. Raises rather than swallowing a write failure."""
        import json

        try:
            from secondlook.tier1.graph_schema import with_provenance
        except ImportError as exc:
            raise Tier1UnavailableError(TIER1_MISSING_MESSAGE) from exc

        graph = self._connect()
        props = with_provenance(
            signal.node_properties(),
            source=self.PROVENANCE_SOURCE,
            retrieved_at=signal.computed_at,
            source_version=signal.pipeline_version,
        )
        # FalkorDB stores scalars; a None-valued property is dropped rather than
        # written as null, which would make "not computed" and "computed as
        # null" indistinguishable on read-back.
        props = {k: v for k, v in props.items() if v is not None}
        vid = self._resolve_variant(graph, signal)
        graph.query(
            self._WRITE,
            params={
                "vid": vid,
                "drug": signal.drug,
                "signal_props": props,
                "edge_json": json.dumps(signal.edge_properties(), sort_keys=True),
            },
        )

    def _resolve_variant(self, graph, signal: StructuralSignal):
        """Return the id of the Variant this signal belongs to, creating it only
        if the gene genuinely has no matching variant. See `_FIND_VARIANT`."""
        # A bare "p.Thr315Ile" is the suffix of CIViC's
        # "NP_005148.2:p.Thr315Ile". Prefixing with ":" keeps the match anchored
        # at the accession boundary, so "p.Val60Glu" cannot match
        # "...:p.Val600Glu" by accident.
        suffix = signal.hgvs_p if signal.hgvs_p.startswith(":") else f":{signal.hgvs_p}"
        found = graph.query(
            self._FIND_VARIANT,
            params={"gene": signal.gene, "hgvs_p": signal.hgvs_p, "hgvs_suffix": suffix},
        )
        if found.result_set:
            return found.result_set[0][0]
        created = graph.query(
            self._CREATE_VARIANT,
            params={
                "gene": signal.gene,
                "hgvs_p": signal.hgvs_p,
                "source": self.PROVENANCE_SOURCE,
                "retrieved_at": signal.computed_at,
                "source_version": signal.pipeline_version,
            },
        )
        return created.result_set[0][0]
