"""Per-Role Knowledge Graph Fabric.

Subsystem U (Issue #76, P0).

Implements the multi-graph federation architecture from §2 of the Tumor Board design:
1. Separate, isolated graphs per role (errors decorrelate, jurisdiction is enforced
   by construction).
2. Shared Identity Anchor Layer (HGNC, HGVS, RxNorm, InChIKey, NCT, etc.).
3. Structural prohibition: NO cross-KG edges exist except through an identity anchor.
4. Immutable `role_provenance` on every node.
5. Strict adherence to ARCHITECTURE.md §5 four evidence classes.
6. Temporal validity (`snapshot_id`, `valid_from`, `valid_until`).
7. First-class `CONTRADICTS` edge handling.
8. Per-lane coverage metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from secondlook.ligand_identity import connectivity_layer


class AnchorType(StrEnum):
    """Supported identity anchor taxonomies."""

    HGNC = "HGNC"
    HGVS = "HGVS"
    RXNORM = "RxNorm"
    INCHIKEY = "InChIKey"
    NCT = "NCT"
    CTRI = "CTRI"
    LOINC = "LOINC"
    SNOMED = "SNOMED"
    ICD_O_3 = "ICD-O-3"


class EvidenceClass(StrEnum):
    """Four evidence classes from ARCHITECTURE.md §5."""

    DOCUMENTED = "documented"
    COMPUTED = "computed"
    REGULATORY = "regulatory"
    CONTEXTUAL = "contextual"


class CrossGraphEdgeForbiddenError(PermissionError):
    """Direct cross-KG edges without traversing an identity anchor are strictly forbidden."""


class NodeProvenanceTamperError(ValueError):
    """Attempted to insert or modify a node with mismatched role provenance."""


class ComputedCitationForbiddenError(TypeError):
    """Computed evidence class must have no place for a citation."""


@dataclass(frozen=True)
class IdentityAnchor:
    """A canonical ontology anchor linking concepts across independent role graphs."""

    anchor_type: AnchorType
    identifier: str

    def __post_init__(self) -> None:
        if not self.identifier:
            raise ValueError("IdentityAnchor identifier cannot be empty")

    @property
    def canonical_key(self) -> str:
        ident = self.identifier
        if self.anchor_type == AnchorType.INCHIKEY and "-" in ident:
            ident = connectivity_layer(ident)
        return f"{self.anchor_type.upper()}:{ident.upper()}"


@dataclass(frozen=True)
class GraphNode:
    """An immutable node in a role's knowledge graph."""

    node_id: str
    role_provenance: str
    evidence_class: EvidenceClass
    claim: str
    anchors: tuple[IdentityAnchor, ...] = ()
    citation_url: str | None = None
    citation_id: str | None = None
    method: str | None = None
    version: str | None = None
    instrument: str | None = None
    snapshot_id: str = "initial"
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    caveats: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("node_id cannot be empty")
        if not self.role_provenance:
            raise ValueError("role_provenance is immutable and required")

        # Invariant: Computed cards must never carry a citation
        if self.evidence_class == EvidenceClass.COMPUTED:
            if self.citation_url is not None or self.citation_id is not None:
                raise ComputedCitationForbiddenError(
                    "Computed evidence class nodes must never carry citation_url or citation_id "
                    "(ARCHITECTURE.md §5 and IMPLEMENTATION_PLAN.md §9.2)"
                )
            if not self.method:
                raise ValueError("Computed evidence class node requires 'method'")

        # Invariant: Documented nodes require citations
        if self.evidence_class == EvidenceClass.DOCUMENTED:
            if not self.citation_url:
                raise ValueError("Documented evidence class node requires 'citation_url'")


@dataclass(frozen=True)
class GraphEdge:
    """A directed edge between two nodes."""

    source_id: str
    target_id: str
    relation: str  # e.g. "SUPPORTS", "CONTRADICTS", "EVIDENCED_BY", "ANCHORED_TO"
    role_provenance: str


@dataclass
class LaneCoverage:
    """Coverage and freshness metrics for a role's knowledge graph."""

    role_id: str
    snapshot_id: str
    node_count: int
    edge_count: int
    citation_density: float
    contradiction_count: int
    anchored_entity_count: int


class RoleKnowledgeGraph:
    """An isolated graph namespace owned exclusively by a single board seat."""

    def __init__(self, role_id: str, snapshot_id: str = "snapshot-v1") -> None:
        self.role_id = role_id
        self.snapshot_id = snapshot_id
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._anchor_index: dict[str, list[str]] = {}

    @property
    def nodes(self) -> dict[str, GraphNode]:
        return dict(self._nodes)

    @property
    def edges(self) -> list[GraphEdge]:
        return list(self._edges)

    def add_node(self, node: GraphNode) -> None:
        if node.role_provenance != self.role_id:
            prov = node.role_provenance
            raise NodeProvenanceTamperError(
                f"Cannot insert node with provenance '{prov}' into graph '{self.role_id}'"
            )
        self._nodes[node.node_id] = node
        for anchor in node.anchors:
            key = anchor.canonical_key
            self._anchor_index.setdefault(key, []).append(node.node_id)

    def add_edge(self, edge: GraphEdge) -> None:
        if edge.role_provenance != self.role_id:
            prov = edge.role_provenance
            raise NodeProvenanceTamperError(
                f"Cannot add edge with provenance '{prov}' to graph '{self.role_id}'"
            )
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            raise KeyError(
                "Both source and target nodes must exist in this role graph before creating edge"
            )
        self._edges.append(edge)

    def find_by_anchor(self, anchor: IdentityAnchor) -> tuple[GraphNode, ...]:
        key = anchor.canonical_key
        node_ids = self._anchor_index.get(key, [])
        return tuple(self._nodes[nid] for nid in node_ids)

    def coverage(self) -> LaneCoverage:
        total = len(self._nodes)
        if total == 0:
            return LaneCoverage(
                role_id=self.role_id,
                snapshot_id=self.snapshot_id,
                node_count=0,
                edge_count=0,
                citation_density=0.0,
                contradiction_count=0,
                anchored_entity_count=0,
            )

        documented_count = sum(
            1
            for n in self._nodes.values()
            if n.evidence_class in (EvidenceClass.DOCUMENTED, EvidenceClass.REGULATORY)
        )
        density = documented_count / total
        contradictions = sum(1 for e in self._edges if e.relation.upper() == "CONTRADICTS")

        return LaneCoverage(
            role_id=self.role_id,
            snapshot_id=self.snapshot_id,
            node_count=total,
            edge_count=len(self._edges),
            citation_density=round(density, 3),
            contradiction_count=contradictions,
            anchored_entity_count=len(self._anchor_index),
        )


class GraphFabric:
    """Federated coordinator managing per-role graphs and cross-graph resolution."""

    def __init__(self) -> None:
        self._graphs: dict[str, RoleKnowledgeGraph] = {}

    def register_graph(self, graph: RoleKnowledgeGraph) -> None:
        if graph.role_id in self._graphs:
            raise ValueError(f"Graph for role '{graph.role_id}' already registered")
        self._graphs[graph.role_id] = graph

    def get_graph(self, role_id: str) -> RoleKnowledgeGraph:
        if role_id not in self._graphs:
            raise KeyError(f"No graph registered for role '{role_id}'")
        return self._graphs[role_id]

    def all_roles(self) -> tuple[str, ...]:
        return tuple(self._graphs.keys())

    def add_cross_edge(
        self, source_role: str, target_role: str, source_id: str, target_id: str
    ) -> None:
        """Attempting to link two role graphs directly without an anchor is forbidden."""
        if source_role != target_role:
            msg = (
                f"Direct edge from {source_role}:{source_id} "
                f"to {target_role}:{target_id} is prohibited. "
                "Cross-KG resolution must strictly route through IdentityAnchors."
            )
            raise CrossGraphEdgeForbiddenError(msg)
        self.get_graph(source_role).add_edge(
            GraphEdge(
                source_id=source_id,
                target_id=target_id,
                relation="CONNECTED",
                role_provenance=source_role,
            )
        )

    def resolve_cross_graph(self, anchor: IdentityAnchor) -> dict[str, tuple[GraphNode, ...]]:
        """Find all nodes across all registered role KGs associated with a shared IdentityAnchor."""
        matches: dict[str, tuple[GraphNode, ...]] = {}
        for role_id, graph in self._graphs.items():
            found = graph.find_by_anchor(anchor)
            if found:
                matches[role_id] = found
        return matches

    def generate_coverage_report(self) -> dict[str, LaneCoverage]:
        """Aggregate coverage metrics for every lane in the fabric."""
        return {role_id: graph.coverage() for role_id, graph in self._graphs.items()}
