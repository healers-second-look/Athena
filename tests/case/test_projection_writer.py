"""Offline tests for the patient-graph projection writer.

No live FalkorDB. A fake graph handle records every Cypher string and
interprets the small query vocabulary this writer actually emits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from secondlook.case.projection import plan_projection
from secondlook.case.projection_writer import rebuild_case_projection, write_projection
from secondlook.case.state import (
    Alteration,
    BiomarkerValue,
    CaseState,
    DiseaseAssessment,
    TreatmentEntry,
)

CASE_ID = "case-proj-1"
OTHER_CASE = "case-other"

WORLD_LABELS = ("Variant", "Drug", "Disease", "Gene", "EvidenceItem")
PATIENT_LABELS = frozenset(
    {
        "Case",
        "ObservedAlteration",
        "TreatmentLine",
        "DiseaseAssessment",
        "ClinicalQuestion",
        "BiomarkerMeasurement",
    }
)

# MERGE/CREATE of a *node* with a world label. Relationship MERGE onto an
# already-bound world alias (no `:Label` on the MERGE line) is allowed.
_WORLD_NODE_WRITE = re.compile(
    r"\b(?:CREATE|MERGE)\s*\(\s*[a-zA-Z_][\w]*\s*:(" + "|".join(WORLD_LABELS) + r")\b",
    re.IGNORECASE,
)


def _populated_state() -> CaseState:
    return CaseState(
        case_id=CASE_ID,
        alterations=(
            Alteration(
                gene="EGFR",
                variant="T790M",
                variant_type="missense",
                assay="NGS",
                tested_on=None,
                event_id="evt-alt-1",
            ),
        ),
        biomarkers={
            "TMB": BiomarkerValue(
                name="TMB", value=16.0, unit="mut/Mb", measured_on=None, event_id="evt-bio-1"
            ),
        },
        treatments=(
            TreatmentEntry(
                regimen="osimertinib",
                line=1,
                action="started",
                reason=None,
                event_id="evt-tx-1",
            ),
        ),
        assessments=(
            DiseaseAssessment(
                status="stable", sites=["lung"], assessed_on=None, event_id="evt-dx-1"
            ),
        ),
        clinical_questions=("any trial?",),
    )


def _plan():
    return plan_projection(
        CASE_ID,
        _populated_state(),
        cancer_type="lung adenocarcinoma",
        primary_site="lung",
        histology="adenocarcinoma",
        stage="IV",
    )


@dataclass
class _Node:
    labels: frozenset[str]
    props: dict
    node_id: int


@dataclass
class FakeResult:
    result_set: list


class FakeGraph:
    """In-memory graph that records Cypher and applies this writer's queries."""

    def __init__(self) -> None:
        self.queries: list[tuple[str, dict]] = []
        self._nodes: dict[int, _Node] = {}
        self._edges: list[tuple[int, str, int]] = []
        self._next_id = 1

    def add_node(self, *labels: str, **props) -> int:
        node_id = self._next_id
        self._next_id += 1
        self._nodes[node_id] = _Node(labels=frozenset(labels), props=dict(props), node_id=node_id)
        return node_id

    def add_edge(self, src: int, rel: str, dst: int) -> None:
        edge = (src, rel, dst)
        if edge not in self._edges:
            self._edges.append(edge)

    def nodes_with_label(self, label: str) -> list[_Node]:
        return [n for n in self._nodes.values() if label in n.labels]

    def snapshot(self) -> tuple[frozenset, frozenset]:
        nodes = frozenset(
            (frozenset(n.labels), tuple(sorted((k, _freeze(v)) for k, v in n.props.items())))
            for n in self._nodes.values()
        )
        edges = frozenset(
            (
                frozenset(self._nodes[s].labels),
                tuple(sorted((k, _freeze(v)) for k, v in self._nodes[s].props.items())),
                rel,
                frozenset(self._nodes[d].labels),
                tuple(sorted((k, _freeze(v)) for k, v in self._nodes[d].props.items())),
            )
            for s, rel, d in self._edges
        )
        return nodes, edges

    def query(self, cypher: str, params: dict | None = None):
        params = params or {}
        self.queries.append((cypher, params))
        stripped = " ".join(cypher.split())

        if "DETACH DELETE" in stripped:
            self._delete(params.get("case_id"), stripped)
            return FakeResult([])

        merge_node = re.search(r"MERGE \(n:(\w+) \{([^}]+)\}\) SET n \+= \$props", stripped)
        if merge_node:
            label = merge_node.group(1)
            key_clause = merge_node.group(2)
            identity = _parse_identity(key_clause, params)
            props = dict(params.get("props") or {})
            props.update(identity)
            existing = self._find(label, identity)
            if existing is None:
                self.add_node(label, **props)
            else:
                existing.props.update(props)
            return FakeResult([[1]])

        if "MERGE (a)-[" in stripped or "MERGE (oa)-[" in stripped or "MERGE (tl)-[" in stripped:
            return FakeResult(self._merge_rel(stripped, params))

        if "MERGE (c)-[" in stripped:
            return FakeResult(self._merge_rel(stripped, params))

        return FakeResult([])

    def _delete(self, case_id, cypher: str) -> None:
        labels_in_query = set(re.findall(r"n:(\w+)", cypher))
        remove = []
        for nid, node in self._nodes.items():
            if node.props.get("case_id") != case_id:
                continue
            if not (node.labels & PATIENT_LABELS):
                continue
            if labels_in_query and not (node.labels & labels_in_query):
                continue
            remove.append(nid)
        for nid in remove:
            del self._nodes[nid]
            self._edges = [(s, r, d) for s, r, d in self._edges if s != nid and d != nid]

    def _find(self, label: str, identity: dict) -> _Node | None:
        for node in self.nodes_with_label(label):
            if all(node.props.get(k) == v for k, v in identity.items()):
                return node
        return None

    def _merge_rel(self, cypher: str, params: dict) -> list:
        rel_match = re.search(r"MERGE \(\w+\)-\[:(\w+)\]->\(\w+\)", cypher)
        if rel_match is None:
            return []
        rel = rel_match.group(1)

        if rel == "INSTANCE_OF":
            src = self._find(
                "ObservedAlteration",
                {
                    "case_id": params["case_id"],
                    "source_event_id": params["source_event_id"],
                },
            )
            gene = self._find("Gene", {"symbol": params["gene"]})
            variant = None
            if gene is not None:
                for s, r, d in self._edges:
                    if s == gene.node_id and r == "HAS_VARIANT":
                        v = self._nodes[d]
                        matched = (
                            v.props.get("hgvs_p") == params["variant"]
                            or v.props.get("name") == params["variant"]
                        )
                        if matched:
                            variant = v
                            break
            if src is None or variant is None:
                return []
            self.add_edge(src.node_id, rel, variant.node_id)
            return [[variant.node_id]]

        if rel == "USES":
            src = self._find(
                "TreatmentLine",
                {
                    "case_id": params["case_id"],
                    "source_event_id": params["source_event_id"],
                },
            )
            drug = self._find("Drug", {"name": params["name"]})
            if src is None or drug is None:
                return []
            self.add_edge(src.node_id, rel, drug.node_id)
            return [[drug.node_id]]

        if rel == "DIAGNOSED_WITH":
            src = self._find("Case", {"case_id": params["case_id"]})
            disease = None
            needle = (params.get("name") or "").lower()
            for node in self.nodes_with_label("Disease"):
                if str(node.props.get("name") or "").lower() == needle:
                    disease = node
                    break
            if src is None or disease is None:
                return []
            self.add_edge(src.node_id, rel, disease.node_id)
            return [[disease.node_id]]

        # Ownership: Case -> patient child
        src = self._find("Case", {"case_id": params["case_id"]})
        to_label = None
        for label in PATIENT_LABELS - {"Case"}:
            if f"b:{label}" in cypher or f"(b:{label}" in cypher:
                to_label = label
                break
        dst = None
        if to_label is not None:
            dst = self._find(
                to_label,
                {
                    "case_id": params["case_id"],
                    "source_event_id": params["source_event_id"],
                },
            )
        if src is None or dst is None:
            return []
        self.add_edge(src.node_id, rel, dst.node_id)
        return [[1]]


def _freeze(value):
    if isinstance(value, list):
        return tuple(value)
    return value


def _parse_identity(clause: str, params: dict) -> dict:
    identity = {}
    for part in clause.split(","):
        key, _, raw = part.partition(":")
        key = key.strip()
        raw = raw.strip()
        if raw.startswith("$"):
            identity[key] = params[raw[1:]]
    return identity


def test_writer_never_creates_or_merges_world_nodes():
    graph = FakeGraph()
    write_projection(graph, _plan())
    offending = []
    for cypher, _params in graph.queries:
        if _WORLD_NODE_WRITE.search(cypher):
            offending.append(cypher)
    assert not offending, f"writer must MATCH world nodes, never CREATE/MERGE them: {offending}"


def test_unmatched_alteration_is_counted_not_dropped():
    graph = FakeGraph()
    result = write_projection(graph, _plan())
    assert result.unmatched_variants == 1
    assert result.unmatched_reason
    assert "variant" in result.unmatched_reason.lower()


def test_rebuild_is_idempotent_and_does_not_touch_world_or_other_cases():
    graph = FakeGraph()
    variant_id = graph.add_node("Variant", hgvs_p="T790M", name="T790M", civic_variant_id=34)
    other_id = graph.add_node(
        "ObservedAlteration",
        case_id=OTHER_CASE,
        gene_symbol="KRAS",
        variant="G12C",
        source_event_id="other-alt",
    )

    plan = _plan()
    first = rebuild_case_projection(graph, plan)
    snap_once = graph.snapshot()
    second = rebuild_case_projection(graph, plan)
    snap_twice = graph.snapshot()

    assert snap_once == snap_twice
    assert first == second
    assert variant_id in graph._nodes
    assert "Variant" in graph._nodes[variant_id].labels
    assert other_id in graph._nodes
    assert graph._nodes[other_id].props["case_id"] == OTHER_CASE

    delete_queries = [q for q, _p in graph.queries if "DETACH DELETE" in q]
    assert delete_queries
    delete_cypher = delete_queries[0]
    assert "$case_id" in delete_cypher
    for label in PATIENT_LABELS:
        assert re.search(rf"\bn:{label}\b", delete_cypher), delete_cypher
    for label in WORLD_LABELS:
        assert not re.search(rf"\bn:{label}\b", delete_cypher), delete_cypher


def test_matched_variant_bridge_is_not_counted_as_unmatched():
    graph = FakeGraph()
    gene_id = graph.add_node("Gene", symbol="EGFR")
    variant_id = graph.add_node("Variant", hgvs_p="T790M", name="T790M")
    graph.add_edge(gene_id, "HAS_VARIANT", variant_id)
    graph.add_node("Drug", name="osimertinib")
    graph.add_node("Disease", name="lung adenocarcinoma", doid="3908")

    result = write_projection(graph, _plan())
    assert result.unmatched_variants == 0
    assert result.unmatched_drugs == 0
    assert result.unmatched_diseases == 0
    assert result.unmatched_reason is None
    rels = {rel for _s, rel, _d in graph._edges}
    assert "INSTANCE_OF" in rels
    assert "USES" in rels
    assert "DIAGNOSED_WITH" in rels
