"""Multi-agent tumor board panel architecture.

Subsystems:
- T: Role Charter & Capability Registry (#75, P0)
- U: Per-Role Knowledge Graph Fabric (#76, P0)
- W: Board Session Orchestrator (#78, P0)
- X: Structured Challenge & Disagreement Ledger (#79, P1)
- Y: Agent Harness Runtime (#80, P0)
- AC: Board Record Renderer (#84, P1)
"""

from secondlook.board.challenges import (
    Challenge,
    ChallengeCitationMissingError,
    ChallengeStatus,
    ChallengeType,
    DisagreementLedger,
)
from secondlook.board.charters import (
    CharterRegistry,
    CharterValidationError,
    ClaimKind,
    JurisdictionViolationError,
    RoleCharter,
    load_all_charters,
    load_charter,
)
from secondlook.board.fabric import (
    AnchorType,
    ComputedCitationForbiddenError,
    CrossGraphEdgeForbiddenError,
    EvidenceClass,
    GraphEdge,
    GraphFabric,
    GraphNode,
    IdentityAnchor,
    LaneCoverage,
    NodeProvenanceTamperError,
    RoleKnowledgeGraph,
)
from secondlook.board.harness import (
    AgentHarness,
    Finding,
    RoleExecutionRequest,
    RoleExecutionResult,
    RuntimeJurisdictionError,
    SandboxedKGViolationError,
    SessionTrace,
    ToolNotPermittedError,
    UnstructuredClaimError,
)
from secondlook.board.orchestrator import (
    AutonomousRoutingForbiddenError,
    BoardRecord,
    ChairModelCallForbiddenError,
    run_board,
)
from secondlook.board.renderer import (
    DisagreementLedgerHiddenError,
    render_board_record,
)

__all__ = [
    "AgentHarness",
    "AnchorType",
    "AutonomousRoutingForbiddenError",
    "BoardRecord",
    "ChairModelCallForbiddenError",
    "Challenge",
    "ChallengeCitationMissingError",
    "ChallengeStatus",
    "ChallengeType",
    "CharterRegistry",
    "CharterValidationError",
    "ClaimKind",
    "ComputedCitationForbiddenError",
    "CrossGraphEdgeForbiddenError",
    "DisagreementLedger",
    "DisagreementLedgerHiddenError",
    "EvidenceClass",
    "Finding",
    "GraphEdge",
    "GraphFabric",
    "GraphNode",
    "IdentityAnchor",
    "JurisdictionViolationError",
    "LaneCoverage",
    "NodeProvenanceTamperError",
    "RoleCharter",
    "RoleExecutionRequest",
    "RoleExecutionResult",
    "RoleKnowledgeGraph",
    "RuntimeJurisdictionError",
    "SandboxedKGViolationError",
    "SessionTrace",
    "ToolNotPermittedError",
    "UnstructuredClaimError",
    "load_all_charters",
    "load_charter",
    "render_board_record",
    "run_board",
]
