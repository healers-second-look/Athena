"""Write a `ProjectionPlan` into FalkorDB as a derived, rebuildable index.

This is the only module in the patient-projection pair that talks to the
graph. The planner (`projection.py`) is pure; this file takes an injected
graph handle and never opens its own connection as a default side effect.

Two hard rules:

1. Bridge edges MATCH world nodes that already exist. This module must
   never CREATE or MERGE a `:Variant`, `:Drug`, `:Disease`, `:Gene`, or
   `:EvidenceItem`. Inventing a world node from a patient record would
   let an unverified alteration masquerade as curated CIViC evidence.
2. Rebuild is scoped: delete only the six patient labels for *this*
   `case_id`, then replay the plan. World nodes, and other cases' patient
   nodes, are untouched. Unmatched bridges are counted on the result
   (`ARCHITECTURE.md` §8.1), never silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from secondlook.case.projection import CASE, PATIENT_NODE_TYPES, ProjectionPlan

PATIENT_LABELS: tuple[str, ...] = tuple(nt.label for nt in PATIENT_NODE_TYPES)


class ProjectionFailed(RuntimeError):
    """A FalkorDB call made while writing a patient projection failed."""


@dataclass(frozen=True)
class WriteResult:
    unmatched_variants: int
    unmatched_drugs: int
    unmatched_diseases: int
    unmatched_reason: str | None


_DELETE_LABEL_PREDICATE = " OR ".join(f"n:{label}" for label in PATIENT_LABELS)
_DELETE_QUERY = f"""
MATCH (n)
WHERE n.case_id = $case_id AND ({_DELETE_LABEL_PREDICATE})
DETACH DELETE n
"""

_BRIDGE_VARIANT = """
MATCH (oa:ObservedAlteration {case_id: $case_id, source_event_id: $source_event_id})
MATCH (g:Gene {symbol: $gene})-[:HAS_VARIANT]->(v:Variant)
WHERE v.hgvs_p = $variant OR v.name = $variant
MERGE (oa)-[:INSTANCE_OF]->(v)
RETURN v
"""

_BRIDGE_DRUG = """
MATCH (tl:TreatmentLine {case_id: $case_id, source_event_id: $source_event_id})
MATCH (d:Drug {name: $name})
MERGE (tl)-[:USES]->(d)
RETURN d
"""

_BRIDGE_DISEASE = """
MATCH (c:Case {case_id: $case_id})
MATCH (d:Disease)
WHERE toLower(d.name) = toLower($name)
MERGE (c)-[:DIAGNOSED_WITH]->(d)
RETURN d
"""


def write_projection(graph, plan: ProjectionPlan) -> WriteResult:
    """MERGE patient nodes and ownership edges; MATCH-only for world bridges.

    No `falkordb` import anywhere in this module: the graph handle is
    injected, so the client is the caller's dependency, not ours. That is
    what keeps `ARCHITECTURE.md` §8.10 satisfied without a no-op import.
    """
    for node in plan.nodes:
        _merge_patient_node(graph, node)
    for edge in plan.edges:
        if edge.kind == "ownership":
            _merge_ownership(graph, plan, edge)
    return _write_bridges(graph, plan)


def rebuild_case_projection(graph, plan: ProjectionPlan) -> WriteResult:
    """Drop this case's patient nodes, then write `plan`. Idempotent."""
    _query(graph, _DELETE_QUERY, {"case_id": plan.case_id})
    return write_projection(graph, plan)


def _query(graph, cypher: str, params: dict[str, Any] | None = None):
    try:
        return graph.query(cypher, params=params)
    except OSError as exc:
        raise ProjectionFailed(f"graph I/O failed: {exc}") from exc
    except TimeoutError as exc:
        raise ProjectionFailed(f"graph query timed out: {exc}") from exc
    except ValueError as exc:
        raise ProjectionFailed(f"graph query rejected: {exc}") from exc
    except TypeError as exc:
        raise ProjectionFailed(f"graph query type error: {exc}") from exc
    except _redis_error_type() as exc:
        raise ProjectionFailed(f"graph server error: {exc}") from exc


def _redis_error_type() -> type[BaseException]:
    try:
        import redis.exceptions as redis_exc
    except ImportError:
        return _Never
    return redis_exc.RedisError


class _Never(BaseException):
    """Stand-in so `except _redis_error_type()` is valid when redis is absent."""


def _rows(result) -> list:
    if result is None:
        return []
    return list(getattr(result, "result_set", None) or [])


def _props_dict(properties: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in properties:
        if isinstance(value, tuple):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def _merge_patient_node(graph, node) -> None:
    props = _props_dict(node.properties)
    if node.label == CASE.label:
        cypher = "MERGE (n:Case {case_id: $case_id}) SET n += $props"
        _query(graph, cypher, {"case_id": props["case_id"], "props": props})
        return
    cypher = (
        f"MERGE (n:{node.label} {{case_id: $case_id, source_event_id: $source_event_id}}) "
        f"SET n += $props"
    )
    _query(
        graph,
        cypher,
        {
            "case_id": props["case_id"],
            "source_event_id": props["source_event_id"],
            "props": props,
        },
    )


def _merge_ownership(graph, plan: ProjectionPlan, edge) -> None:
    child = next(node for node in plan.nodes if node.key == edge.to_key)
    source_event_id = dict(child.properties)["source_event_id"]
    cypher = (
        f"MATCH (a:Case {{case_id: $case_id}}) "
        f"MATCH (b:{edge.to_label} {{case_id: $case_id, source_event_id: $source_event_id}}) "
        f"MERGE (a)-[:{edge.rel_type}]->(b)"
    )
    _query(
        graph,
        cypher,
        {"case_id": plan.case_id, "source_event_id": source_event_id},
    )


def _write_bridges(graph, plan: ProjectionPlan) -> WriteResult:
    unmatched_variants = 0
    unmatched_drugs = 0
    unmatched_diseases = 0
    extra_by_key = {node.key: dict(node.properties) for node in plan.nodes}

    for edge in plan.edges:
        if edge.kind != "bridge":
            continue
        src_props = extra_by_key.get(edge.from_key, {})
        if edge.rel_type == "INSTANCE_OF":
            rows = _rows(
                _query(
                    graph,
                    _BRIDGE_VARIANT,
                    {
                        "case_id": plan.case_id,
                        "source_event_id": src_props.get("source_event_id"),
                        "gene": src_props.get("gene_symbol") or dict(edge.extra).get("gene_symbol"),
                        "variant": edge.match_value,
                    },
                )
            )
            if not rows:
                unmatched_variants += 1
        elif edge.rel_type == "USES":
            rows = _rows(
                _query(
                    graph,
                    _BRIDGE_DRUG,
                    {
                        "case_id": plan.case_id,
                        "source_event_id": src_props.get("source_event_id")
                        or dict(edge.extra).get("source_event_id"),
                        "name": edge.match_value,
                    },
                )
            )
            if not rows:
                unmatched_drugs += 1
        elif edge.rel_type == "DIAGNOSED_WITH":
            rows = _rows(
                _query(
                    graph,
                    _BRIDGE_DISEASE,
                    {"case_id": plan.case_id, "name": edge.match_value},
                )
            )
            if not rows:
                unmatched_diseases += 1

    total = unmatched_variants + unmatched_drugs + unmatched_diseases
    reason = None
    if total:
        reason = (
            f"{unmatched_variants} variant(s) unmatched, "
            f"{unmatched_drugs} drug(s) unmatched, "
            f"{unmatched_diseases} disease(s) unmatched; "
            "bridge omitted because no world node existed"
        )
    return WriteResult(
        unmatched_variants=unmatched_variants,
        unmatched_drugs=unmatched_drugs,
        unmatched_diseases=unmatched_diseases,
        unmatched_reason=reason,
    )
