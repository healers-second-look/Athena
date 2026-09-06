"""Knowledge-graph context & FalkorDB retrieval -- issue #103, Phases 4, 5, and 6.

Phase 4: Structured facts passed to the prompt.
Phase 5: Subgraph extraction with Cypher query for visual graph rendering.
Phase 6: Real evidence retrieval from FalkorDB grounding the turn in citations.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

GRAPH_NAME = os.environ.get("FALKORDB_GRAPH_NAME", "secondlook_tier1")

# Named Cypher queries
_COUNT_BY_LABEL = "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC"
_DISEASES = "MATCH (d:Disease) RETURN d.name AS name, d.doid AS doid ORDER BY d.name"

_GENES_WITH_EVIDENCE = """
MATCH (g:Gene)-[:HAS_VARIANT]->(v:Variant)<-[:SUPPORTS]-(e:EvidenceItem)
RETURN g.symbol AS symbol, count(DISTINCT e) AS evidence_count
ORDER BY evidence_count DESC, symbol
"""

_GENE_FACTS = """
MATCH (g:Gene {symbol: $symbol})-[:HAS_VARIANT]->(v:Variant)
OPTIONAL MATCH (e:EvidenceItem)-[:SUPPORTS]->(v)
OPTIONAL MATCH (v)-[:PREDICTS_RESPONSE_TO]->(d:Drug)
OPTIONAL MATCH (v)-[:OBSERVED_IN]->(dis:Disease)
RETURN coalesce(v.hgvs_p, v.name) AS variant, e.evidence_level AS level,
       d.name AS drug, dis.name AS disease
LIMIT $limit
"""

_DISEASE_FACTS = """
MATCH (v:Variant)-[:OBSERVED_IN]->(dis:Disease {name: $name})
MATCH (g:Gene)-[:HAS_VARIANT]->(v)
OPTIONAL MATCH (e:EvidenceItem)-[:SUPPORTS]->(v)
OPTIONAL MATCH (v)-[:PREDICTS_RESPONSE_TO]->(dr:Drug)
RETURN g.symbol AS gene, coalesce(v.hgvs_p, v.name) AS variant,
       dr.name AS drug, e.evidence_level AS level
LIMIT $limit
"""

_EVIDENCE_BY_ENTITIES = """
MATCH (g:Gene)-[:HAS_VARIANT]->(v:Variant)
WHERE (size($genes) > 0 AND g.symbol IN $genes)
   OR (size($genes) = 0 AND coalesce(v.hgvs_p, v.name) IN $variants)
OPTIONAL MATCH (e:EvidenceItem)-[:SUPPORTS]->(v)
OPTIONAL MATCH (v)-[:PREDICTS_RESPONSE_TO]->(d:Drug)
OPTIONAL MATCH (v)-[:OBSERVED_IN]->(dis:Disease)
WHERE e.citation_url IS NOT NULL
RETURN g.symbol AS gene, coalesce(v.hgvs_p, v.name) AS variant, d.name AS drug,
       dis.name AS disease, e.evidence_level AS level, e.summary AS summary,
       e.citation_url AS citation_url, e.civic_id AS civic_id
ORDER BY e.evidence_level ASC
LIMIT $limit
"""

_EVIDENCE_FOR_CONTEXT = """
MATCH (g:Gene {symbol: $symbol})-[:HAS_VARIANT]->(v:Variant)
OPTIONAL MATCH (e:EvidenceItem)-[:SUPPORTS]->(v)
OPTIONAL MATCH (v)-[:PREDICTS_RESPONSE_TO]->(d:Drug)
OPTIONAL MATCH (v)-[:OBSERVED_IN]->(dis:Disease)
WHERE e.citation_url IS NOT NULL
RETURN g.symbol AS gene, coalesce(v.hgvs_p, v.name) AS variant, d.name AS drug,
       dis.name AS disease, e.evidence_level AS level, e.summary AS summary,
       e.citation_url AS citation_url, e.civic_id AS civic_id
ORDER BY e.evidence_level ASC
LIMIT $limit
"""


@dataclass(frozen=True)
class GraphContext:
    id: str
    label: str
    kind: str  # "graph" | "gene" | "disease"
    detail: str

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "kind": self.kind, "detail": self.detail}


class GraphUnavailable(RuntimeError):
    """FalkorDB could not be reached or queried."""


def _graph(graph=None):
    if graph is not None:
        return graph
    try:
        from secondlook.tier1.graph_connection import connect_graph

        return connect_graph(GRAPH_NAME)
    except Exception as exc:  # noqa: BLE001
        raise GraphUnavailable(f"FalkorDB unreachable: {exc}") from exc


def _rows(graph, query: str, params: dict | None = None) -> list[list]:
    try:
        result = graph.query(query, params) if params else graph.query(query)
    except Exception as exc:  # noqa: BLE001
        raise GraphUnavailable(f"graph query failed: {exc}") from exc
    return list(result.result_set or [])


def list_contexts(graph=None) -> list[GraphContext]:
    """KG contexts a session can attach, discovered from the live graph."""
    try:
        handle = _graph(graph)
        counts = {label: n for label, n in _rows(handle, _COUNT_BY_LABEL)}
        contexts = [
            GraphContext(
                id=f"graph:{GRAPH_NAME}",
                label="Full evidence graph",
                kind="graph",
                detail=", ".join(f"{n} {label}" for label, n in counts.items()),
            )
        ]
        for symbol, evidence_count in _rows(handle, _GENES_WITH_EVIDENCE)[:15]:
            contexts.append(
                GraphContext(
                    id=f"gene:{symbol}",
                    label=f"Gene: {symbol}",
                    kind="gene",
                    detail=f"{evidence_count} evidence item(s)",
                )
            )
        for name, doid in _rows(handle, _DISEASES)[:10]:
            contexts.append(
                GraphContext(
                    id=f"disease:{name}",
                    label=f"Disease: {name}",
                    kind="disease",
                    detail=f"DOID {doid}" if doid else "no DOID recorded",
                )
            )
        return contexts
    except GraphUnavailable as exc:
        logger.warning("KG contexts unavailable: %s", exc)
        return []


def describe_context(context_id: str, *, limit: int = 12, graph=None) -> list[str]:
    """Real facts for `context_id`, as prompt-ready lines (Phase 4)."""
    if not context_id:
        return []
    try:
        handle = _graph(graph)
        kind, _, value = context_id.partition(":")
        if kind == "gene":
            rows = _rows(handle, _GENE_FACTS, {"symbol": value, "limit": limit})
            lines = [
                f"KG[{value}] variant {variant}"
                + (f" in {disease}" if disease else "")
                + (f" predicts response to {drug}" if drug else "")
                + (f" -- CIViC level {level}" if level else "")
                for variant, level, drug, disease in rows
            ]
        elif kind == "disease":
            rows = _rows(handle, _DISEASE_FACTS, {"name": value, "limit": limit})
            lines = [
                f"KG[{value}] "
                + (f"{gene} " if gene else "")
                + (f"{variant} " if variant else "")
                + (f"-> {drug} " if drug else "")
                + (f"(level {level})" if level else "")
                for gene, variant, drug, level in rows
            ]
        else:
            counts = _rows(handle, _COUNT_BY_LABEL)
            lines = [f"KG[graph] {n} {label} node(s)" for label, n in counts]
        return [line.strip() for line in lines if line.strip()]
    except GraphUnavailable as exc:
        logger.warning("KG context %s unavailable: %s", context_id, exc)
        return [f"KG[{context_id}] UNAVAILABLE -- the graph could not be read: {exc}"]


def fetch_subgraph(context_id: str, *, limit: int = 60, graph=None) -> dict:
    """Nodes, edges, and Cypher query for `context_id` (Phase 5).

    Returns:
      {
        "context_id": "...",
        "cypher": "...",
        "params": {...},
        "nodes": [{"id", "label", "type", "properties"}],
        "edges": [{"source", "target", "type"}]
      }
    """
    handle = _graph(graph)
    kind, _, value = context_id.partition(":")
    if kind == "gene":
        query = """
MATCH (g:Gene {symbol: $value})-[r1:HAS_VARIANT]->(v:Variant)
OPTIONAL MATCH (e:EvidenceItem)-[r2:SUPPORTS]->(v)
OPTIONAL MATCH (v)-[r3:PREDICTS_RESPONSE_TO]->(d:Drug)
OPTIONAL MATCH (v)-[r4:OBSERVED_IN]->(dis:Disease)
RETURN g, r1, v, r2, e, r3, d, r4, dis LIMIT $limit
""".strip()
        params = {"value": value, "limit": limit}
    elif kind == "disease":
        query = """
MATCH (v:Variant)-[r1:OBSERVED_IN]->(dis:Disease {name: $value})
MATCH (g:Gene)-[r2:HAS_VARIANT]->(v)
OPTIONAL MATCH (v)-[r3:PREDICTS_RESPONSE_TO]->(d:Drug)
OPTIONAL MATCH (e:EvidenceItem)-[r4:SUPPORTS]->(v)
RETURN dis, r1, v, r2, g, r3, d, r4, e LIMIT $limit
""".strip()
        params = {"value": value, "limit": limit}
    else:
        query = """
MATCH (a)-[r]->(b)
WHERE NOT a:EvidenceItem
RETURN a, r, b LIMIT $limit
""".strip()
        params = {"limit": limit}

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(node) -> str | None:
        if node is None:
            return None
        node_id = str(getattr(node, "id", None) or id(node))
        if node_id not in nodes:
            props = dict(getattr(node, "properties", {}) or {})
            labels = list(getattr(node, "labels", []) or [])
            node_type = labels[0] if labels else "Node"

            # Smart label resolution
            label = (
                props.get("symbol")
                or props.get("hgvs_p")
                or props.get("name")
                or (f"CIViC:{props['civic_id']}" if "civic_id" in props else None)
                or props.get("title")
                or node_id
            )
            nodes[node_id] = {
                "id": node_id,
                "type": node_type,
                "label": str(label),
                "properties": {k: str(v) for k, v in props.items()},
            }
        return node_id

    for row in _rows(handle, query, params):
        for cell in row:
            if hasattr(cell, "labels"):
                add_node(cell)
            elif hasattr(cell, "relation"):
                src = str(getattr(cell, "src_node", ""))
                dst = str(getattr(cell, "dest_node", ""))
                edge_item = {"source": src, "target": dst, "type": cell.relation}
                if edge_item not in edges:
                    edges.append(edge_item)

    return {
        "context_id": context_id,
        "cypher": query,
        "params": params,
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def retrieve_evidence_for_turn(
    entities: dict[str, list[str]],
    context_id: str | None = None,
    *,
    limit: int = 6,
    graph=None,
) -> list[dict]:
    """Fetch structured evidence records for entities or context (Phase 6).

    Returns a list of evidence dicts ready for `turn.sources` and prompt assembly.
    """
    sources: list[dict] = []
    try:
        handle = _graph(graph)
        genes = entities.get("genes", [])
        variants = entities.get("variants", [])

        rows = []
        if genes or variants:
            rows = _rows(
                handle,
                _EVIDENCE_BY_ENTITIES,
                {"genes": genes, "variants": variants, "limit": limit},
            )

        if not rows and context_id and context_id.startswith("gene:"):
            symbol = context_id.split(":", 1)[1]
            rows = _rows(handle, _EVIDENCE_FOR_CONTEXT, {"symbol": symbol, "limit": limit})

        for i, row in enumerate(rows, start=1):
            gene, variant, drug, disease, level, summary, citation_url, civic_id = row
            pmid_match = re.search(r"pubmed/(\d+)", citation_url or "")
            pmid = pmid_match.group(1) if pmid_match else str(civic_id or i)

            title = (
                f"{gene} {variant}" if gene and variant else (gene or variant or "Evidence Item")
            )
            if drug:
                title += f" → {drug}"
            if disease:
                title += f" in {disease}"

            sources.append(
                {
                    "id": f"civic:{civic_id or i}",
                    "citation_index": i,
                    "title": title,
                    "gene": gene,
                    "variant": variant,
                    "drug": drug,
                    "disease": disease,
                    "evidence_level": level or "B",
                    "summary": summary or "No summary available.",
                    "citation_url": citation_url or "http://civicdb.org",
                    "pmid": pmid,
                }
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Evidence retrieval failed: %s", exc)

    return sources


__all__ = [
    "GRAPH_NAME",
    "GraphContext",
    "GraphUnavailable",
    "describe_context",
    "fetch_subgraph",
    "list_contexts",
    "retrieve_evidence_for_turn",
]
