"""Multi-agent tumor board panel architecture.

Subsystems:
- T: Role Charter & Capability Registry (#75, P0)
- U: Per-Role Knowledge Graph Fabric (#76, P0)
- V: KG Construction & Curation Pipeline (#77, P0)
- W: Board Session Orchestrator (#78, P0)
- X: Structured Challenge & Disagreement Ledger (#79, P1)
- Y: Agent Harness Runtime (#80, P0)
- Z: Role Evaluation Suite (#81, P0)
- AA: Adversarial & Sycophancy Red-Team Corpus (#82, P0)
- AB: Replay, Trace & Audit Store (#83, P1)
- AC: Board Record Renderer (#84, P1)
- AD: Clinician Feedback & Overrule Capture (#85, P1)
- AE: Cost & Latency Governor (#86, P2)
- AF: Patient-Readable Board Record (#87, P2)
"""

from secondlook.board.audit import (
    AuditStore,
    SessionDiff,
    diff_board_records,
    export_deidentified_record,
)
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
from secondlook.board.curation import (
    PERMISSIBLE_LICENSES,
    CurationPipeline,
    CuratorActionError,
    LicenseType,
    LicenseViolationError,
    StagedKGNode,
    StagedNodeStatus,
)
from secondlook.board.evaluation import (
    ReleaseSafetyBlockError,
    RoleEvaluationSuite,
    RoleReportCard,
    ThresholdRule,
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
from secondlook.board.governor import (
    BoardGovernor,
    GovernorConfig,
    GovernorLimitExceededError,
    GovernorState,
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
from secondlook.board.overrule import (
    ClinicianOverrule,
    MissingOverruleReasonError,
    OverruleAction,
    OverruleLedger,
)
from secondlook.board.patient_record import (
    PatientReadableRecord,
    generate_patient_readable_record,
    render_patient_record_html,
)
from secondlook.board.redteam import (
    VERSIONED_REDTEAM_CORPUS,
    RedTeamHarness,
    RedTeamRegressionError,
    RedTeamTrap,
)
from secondlook.board.renderer import (
    DisagreementLedgerHiddenError,
    render_board_record,
)

__all__ = [
    "AgentHarness",
    "AnchorType",
    "AuditStore",
    "AutonomousRoutingForbiddenError",
    "BoardGovernor",
    "BoardRecord",
    "ChairModelCallForbiddenError",
    "Challenge",
    "ChallengeCitationMissingError",
    "ChallengeStatus",
    "ChallengeType",
    "CharterRegistry",
    "CharterValidationError",
    "ClaimKind",
    "ClinicianOverrule",
    "ComputedCitationForbiddenError",
    "CrossGraphEdgeForbiddenError",
    "CurationPipeline",
    "CuratorActionError",
    "DisagreementLedger",
    "DisagreementLedgerHiddenError",
    "EvidenceClass",
    "Finding",
    "GovernorConfig",
    "GovernorLimitExceededError",
    "GovernorState",
    "GraphEdge",
    "GraphFabric",
    "GraphNode",
    "IdentityAnchor",
    "JurisdictionViolationError",
    "LaneCoverage",
    "LicenseType",
    "LicenseViolationError",
    "MissingOverruleReasonError",
    "NodeProvenanceTamperError",
    "OverruleAction",
    "OverruleLedger",
    "PERMISSIBLE_LICENSES",
    "PatientReadableRecord",
    "RedTeamHarness",
    "RedTeamRegressionError",
    "RedTeamTrap",
    "ReleaseSafetyBlockError",
    "RoleCharter",
    "RoleEvaluationSuite",
    "RoleExecutionRequest",
    "RoleExecutionResult",
    "RoleKnowledgeGraph",
    "RoleReportCard",
    "RuntimeJurisdictionError",
    "SandboxedKGViolationError",
    "SessionDiff",
    "SessionTrace",
    "StagedKGNode",
    "StagedNodeStatus",
    "ThresholdRule",
    "ToolNotPermittedError",
    "UnstructuredClaimError",
    "VERSIONED_REDTEAM_CORPUS",
    "diff_board_records",
    "export_deidentified_record",
    "generate_patient_readable_record",
    "load_all_charters",
    "load_charter",
    "render_board_record",
    "render_patient_record_html",
    "run_board",
]
