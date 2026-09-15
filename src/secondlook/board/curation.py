"""KG Construction & Curation Pipeline.

Subsystem V (Issue #77, P0).

Provides:
1. Licensing-first ingestion: Rejects non-open, unlicensed, or proprietary sources.
2. Curator-gated staging: Ingested evidence enters 'pending_confirmation';
   never promoted automatically to active role knowledge graphs.
3. Versioning and temporal validity: Stamps valid_from, valid_until, and snapshot_id.
4. Contradiction preservation: Retains CONTRADICTS edges between conflicting nodes
   rather than silently overwriting past evidence.
5. Ingestion integration: Consumes candidate KG updates from Subsystem AD overrule items.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from secondlook.board.fabric import (
    EvidenceClass,
    GraphEdge,
    GraphFabric,
    GraphNode,
    IdentityAnchor,
)


class LicenseViolationError(PermissionError):
    """Raised when an evidence source violates open/permissible licensing constraints."""


class CuratorActionError(ValueError):
    """Raised when an invalid curator operation is attempted."""


class LicenseType(StrEnum):
    """Permissible and prohibited license categories for ingested KG clinical evidence."""

    CC0 = "CC0"
    CC_BY = "CC-BY"
    CC_BY_SA = "CC-BY-SA"
    OPEN_GOVERNMENT = "Open-Government"
    PUBLIC_DOMAIN = "Public-Domain"
    PROPRIETARY = "Proprietary"
    UNKNOWN = "Unknown"


PERMISSIBLE_LICENSES: frozenset[LicenseType] = frozenset(
    {
        LicenseType.CC0,
        LicenseType.CC_BY,
        LicenseType.CC_BY_SA,
        LicenseType.OPEN_GOVERNMENT,
        LicenseType.PUBLIC_DOMAIN,
    }
)


class StagedNodeStatus(StrEnum):
    PENDING_CONFIRMATION = "pending_confirmation"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class StagedKGNode:
    """An unpromoted candidate node awaiting curator review and validation."""

    staged_id: str
    role_id: str
    evidence_class: EvidenceClass
    claim: str
    citation_id: str
    citation_url: str | None
    license: LicenseType
    anchors: tuple[IdentityAnchor, ...] = ()
    valid_from: datetime = field(default_factory=lambda: datetime.now(UTC))
    valid_until: datetime | None = None
    status: StagedNodeStatus = StagedNodeStatus.PENDING_CONFIRMATION
    contradicts_node_ids: tuple[str, ...] = ()
    curator_id: str | None = None
    curation_reason: str | None = None
    snapshot_id: str = "curation_stage"

    def __post_init__(self) -> None:
        if not self.staged_id:
            raise ValueError("staged_id cannot be empty")
        if not self.role_id:
            raise ValueError("role_id cannot be empty")
        if not self.claim or not self.claim.strip():
            raise ValueError("claim cannot be empty")


class CurationPipeline:
    """Orchestrates licensing verification, curator review, and promotion to role KGs."""

    def __init__(self, fabric: GraphFabric) -> None:
        self.fabric = fabric
        self._staged_nodes: dict[str, StagedKGNode] = {}

    def stage_evidence(
        self,
        staged_id: str,
        role_id: str,
        evidence_class: EvidenceClass,
        claim: str,
        citation_id: str,
        citation_url: str | None,
        license: LicenseType,
        anchors: tuple[IdentityAnchor, ...] = (),
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        contradicts_node_ids: tuple[str, ...] = (),
    ) -> StagedKGNode:
        """Stages new candidate evidence after verifying licensing permission."""
        if license not in PERMISSIBLE_LICENSES:
            raise LicenseViolationError(
                f"License '{license.value}' is not permissible for clinical KG ingestion"
            )

        if evidence_class == EvidenceClass.DOCUMENTED and not citation_url:
            raise ValueError("Documented evidence requires citation_url")

        # Detect potential contradictions with existing nodes sharing the same anchors
        detected_contradictions: list[str] = list(contradicts_node_ids)
        try:
            role_kg = self.fabric.get_graph(role_id)
            for anchor in anchors:
                existing_nodes = role_kg.find_by_anchor(anchor)
                for existing in existing_nodes:
                    if existing.claim != claim and existing.node_id not in detected_contradictions:
                        detected_contradictions.append(existing.node_id)
        except KeyError:
            pass

        node = StagedKGNode(
            staged_id=staged_id,
            role_id=role_id,
            evidence_class=evidence_class,
            claim=claim,
            citation_id=citation_id,
            citation_url=citation_url,
            license=license,
            anchors=anchors,
            valid_from=valid_from or datetime.now(UTC),
            valid_until=valid_until,
            status=StagedNodeStatus.PENDING_CONFIRMATION,
            contradicts_node_ids=tuple(detected_contradictions),
        )

        self._staged_nodes[staged_id] = node
        return node

    def ingest_from_overrule(
        self,
        overrule_item: dict[str, Any],
        staged_id: str,
        license: LicenseType = LicenseType.PUBLIC_DOMAIN,
        citation_url: str = "https://athena.internal/overrules",
    ) -> StagedKGNode:
        """Bridges a clinician overrule queue item into a staged candidate KG node."""
        target_role = overrule_item["target_role"]
        reason = overrule_item["reason"]
        alternative = overrule_item.get("suggested_alternative")
        claim = alternative if alternative else f"Clinician overrule: {reason}"

        return self.stage_evidence(
            staged_id=staged_id,
            role_id=target_role,
            evidence_class=EvidenceClass.DOCUMENTED,
            claim=claim,
            citation_id=f"overrule-{overrule_item.get('target_id', 'unknown')}",
            citation_url=citation_url,
            license=license,
            anchors=(),
            contradicts_node_ids=(
                (overrule_item.get("target_id", ""),) if overrule_item.get("target_id") else ()
            ),
        )

    def approve_and_promote(
        self,
        staged_id: str,
        curator_id: str,
        notes: str,
        snapshot_id: str = "promoted-v1",
    ) -> GraphNode:
        """Promotes an approved staged node into the role's active knowledge graph.

        Preserves CONTRADICTS edges against conflicting existing nodes.
        """
        staged = self.get_staged_node(staged_id)
        if staged.status != StagedNodeStatus.PENDING_CONFIRMATION:
            raise CuratorActionError(
                f"Cannot approve node '{staged_id}' with status '{staged.status.value}'"
            )
        if not curator_id or not curator_id.strip():
            raise CuratorActionError("curator_id cannot be empty for promotion")

        # Promote to active RoleKnowledgeGraph
        role_kg = self.fabric.get_graph(staged.role_id)
        graph_node = GraphNode(
            node_id=staged.staged_id,
            role_provenance=staged.role_id,
            evidence_class=staged.evidence_class,
            claim=staged.claim,
            anchors=staged.anchors,
            citation_id=staged.citation_id,
            citation_url=staged.citation_url,
            snapshot_id=snapshot_id,
            valid_from=staged.valid_from,
            valid_until=staged.valid_until,
            caveats=tuple([f"Curated by {curator_id}: {notes}"] if notes else []),
        )

        role_kg.add_node(graph_node)

        # Wire CONTRADICTS edges to conflicting nodes in the same role graph
        for target_id in staged.contradicts_node_ids:
            if target_id in role_kg.nodes:
                role_kg.add_edge(
                    GraphEdge(
                        source_id=graph_node.node_id,
                        target_id=target_id,
                        relation="CONTRADICTS",
                        role_provenance=staged.role_id,
                    )
                )
                role_kg.add_edge(
                    GraphEdge(
                        source_id=target_id,
                        target_id=graph_node.node_id,
                        relation="CONTRADICTS",
                        role_provenance=staged.role_id,
                    )
                )

        # Update staged record to APPROVED
        updated = dataclasses.replace(
            staged,
            status=StagedNodeStatus.APPROVED,
            curator_id=curator_id,
            curation_reason=notes,
            snapshot_id=snapshot_id,
        )
        self._staged_nodes[staged_id] = updated
        return graph_node

    def reject(self, staged_id: str, curator_id: str, reason: str) -> StagedKGNode:
        """Marks a staged candidate node as rejected with an audit trail."""
        staged = self.get_staged_node(staged_id)
        if staged.status != StagedNodeStatus.PENDING_CONFIRMATION:
            raise CuratorActionError(
                f"Cannot reject node '{staged_id}' with status '{staged.status.value}'"
            )
        if not curator_id or not curator_id.strip():
            raise CuratorActionError("curator_id cannot be empty for rejection")
        if not reason or not reason.strip():
            raise CuratorActionError("Rejection requires an explicit reason")

        updated = dataclasses.replace(
            staged,
            status=StagedNodeStatus.REJECTED,
            curator_id=curator_id,
            curation_reason=reason,
        )
        self._staged_nodes[staged_id] = updated
        return updated

    def get_staged_node(self, staged_id: str) -> StagedKGNode:
        if staged_id not in self._staged_nodes:
            raise KeyError(f"No staged node found with id '{staged_id}'")
        return self._staged_nodes[staged_id]

    def get_pending_nodes(self) -> tuple[StagedKGNode, ...]:
        return tuple(
            n
            for n in self._staged_nodes.values()
            if n.status == StagedNodeStatus.PENDING_CONFIRMATION
        )
