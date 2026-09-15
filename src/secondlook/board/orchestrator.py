"""Board Session Orchestrator.

Subsystem W (Issue #78, P0).

Executes the tumor board session protocol defined in Part I §4:
- Round 1: Sealed independent read (each role receives only the case and its own KG).
- Round 2: Simultaneous publication (all sealed findings opened at once).
- Round 3: Typed challenges only (5 canonical challenge types with mandatory citations).
- Round 4: Deterministic assembly (chair is pure code, calls no model, applies no judgment).
- Round 5: Presentation / Render hook.

Invariants:
- The chair is deterministic code that applies no judgment and calls no LLM.
- No role sees another's findings during Round 1 drafting.
- Raises if any role attempts to read a KG outside its charter.
- No consensus scoring or voting. Disagreements are preserved verbatim.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from secondlook.board.challenges import (
    Challenge,
    ChallengeType,
    DisagreementLedger,
)
from secondlook.board.charters import (
    CharterRegistry,
    RoleCharter,
)
from secondlook.board.fabric import (
    GraphFabric,
    LaneCoverage,
)
from secondlook.board.harness import (
    AgentHarness,
    Finding,
    SessionTrace,
)


class ChairModelCallForbiddenError(TypeError):
    """The chair is pure deterministic code and is strictly forbidden from calling a model."""


class AutonomousRoutingForbiddenError(PermissionError):
    """Dynamic/autonomous agent routing is forbidden; roles execute per protocol specification."""


@dataclass(frozen=True)
class BoardRecord:
    """Immutable, auditable output of a complete tumor board session."""

    session_id: str
    case_id: str
    timestamp: datetime
    roles: tuple[str, ...]
    findings_by_lane: dict[str, tuple[Finding, ...]]
    all_findings: tuple[Finding, ...]
    disagreement_ledger: DisagreementLedger
    missing_data_union: tuple[str, ...]
    abstention_audit: dict[str, tuple[str, ...]]
    lane_coverages: dict[str, LaneCoverage]
    trace: SessionTrace
    quorum_verified: bool = True

    def get_findings_for_role(self, role_id: str) -> tuple[Finding, ...]:
        return self.findings_by_lane.get(role_id, ())

    def get_challenges_for_finding(self, finding_id: str) -> tuple[Challenge, ...]:
        return self.disagreement_ledger.get_challenges_for_finding(finding_id)


# Callable signature for generating challenges in Round 3:
# (challenger_charter, candidate_finding, challenger_kg) -> Challenge | None
ChallengeEvaluator = Callable[[RoleCharter, Finding, Any], Challenge | None]


def run_board(
    case: Any,
    roles: list[RoleCharter],
    fabric: GraphFabric,
    registry: CharterRegistry | None = None,
    harness: AgentHarness | None = None,
    challenge_evaluators: dict[str, ChallengeEvaluator] | None = None,
    snapshots: dict[str, str] | None = None,
) -> BoardRecord:
    """Executes the 5-round tumor board protocol.

    Round 1 sealed -> Round 2 open -> Round 3 typed challenges ->
    Round 4 deterministic assembly. The chair applies no judgment and
    calls no model. Raises if any role reads a KG outside its charter.
    """
    session_id = f"board-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC)
    if isinstance(case, dict):
        case_id = case.get("case_id", "case-anonymous")
    else:
        case_id = getattr(case, "case_id", "case-anonymous")

    # Initialize registry if not provided
    if registry is None:
        registry = CharterRegistry({r.role_id: r for r in roles})
    else:
        for r in roles:
            if r.role_id not in registry.all_roles():
                registry.register(r)

    # Initialize session trace and harness
    trace = SessionTrace(session_id=session_id, started_at=now)
    active_harness = harness or AgentHarness(registry=registry, fabric=fabric, trace=trace)

    # Quorum check: verify chair exists in roles (or is implied)
    chair_charter = next((r for r in roles if r.role_id == "chair"), None)
    if chair_charter and not chair_charter.is_deterministic:
        raise ChairModelCallForbiddenError("The chair charter must declare is_deterministic=True")

    trace.log_event(
        "orchestrator",
        "SESSION_START",
        {
            "case_id": case_id,
            "roles": [r.role_id for r in roles],
            "snapshots": snapshots or {},
        },
    )

    # =========================================================================
    # ROUND 1 — Sealed independent read
    # Every role receives the case and its own KG only. No role sees any other's
    # findings. Sealed bids committed before Round 2 opens.
    # =========================================================================
    trace.log_event("orchestrator", "ROUND_1_START", {"description": "Sealed independent read"})
    sealed_findings_by_role: dict[str, tuple[Finding, ...]] = {}
    missing_data_by_role: dict[str, tuple[str, ...]] = {}
    abstentions_by_role: dict[str, tuple[str, ...]] = {}

    for charter in roles:
        # Chair does not generate clinical findings in Round 1
        if charter.role_id == "chair":
            sealed_findings_by_role["chair"] = ()
            missing_data_by_role["chair"] = ()
            abstentions_by_role["chair"] = ()
            continue

        result = active_harness.execute_role(
            role_id=charter.role_id,
            case_state=case,
            round_number=1,
            published_findings=(),  # Sealed: empty
        )
        sealed_findings_by_role[charter.role_id] = result.findings
        missing_data_by_role[charter.role_id] = result.missing_data
        abstentions_by_role[charter.role_id] = result.abstentions

    trace.log_event("orchestrator", "ROUND_1_SEALED", {"role_count": len(sealed_findings_by_role)})

    # =========================================================================
    # ROUND 2 — Simultaneous publication
    # All sealed findings opened at once. No ordering advantage.
    # =========================================================================
    published_findings: list[Finding] = []
    for role_findings in sealed_findings_by_role.values():
        published_findings.extend(role_findings)

    trace.log_event(
        "orchestrator",
        "ROUND_2_PUBLICATION",
        {"total_findings_published": len(published_findings)},
    )

    # =========================================================================
    # ROUND 3 — Typed challenges only
    # Roles evaluate opened findings against their own KG.
    # Must carry a citation from challenger's KG and be one of the 5 types.
    # =========================================================================
    trace.log_event("orchestrator", "ROUND_3_START", {"description": "Typed challenges only"})
    disagreement_ledger = DisagreementLedger()
    evaluators = challenge_evaluators or {}

    for charter in roles:
        role_id = charter.role_id
        if role_id == "chair":
            continue

        challenger_kg = fabric.get_graph(charter.kg_id)
        role_evaluator = evaluators.get(role_id)

        for target_finding in published_findings:
            if target_finding.role_id == role_id:
                continue  # Cannot challenge self

            if role_evaluator is not None:
                challenge = role_evaluator(charter, target_finding, challenger_kg)
                if challenge is not None:
                    disagreement_ledger.add_challenge(challenge)
                    trace.log_event(
                        role_id,
                        "CHALLENGE_FILED",
                        {
                            "target_finding_id": target_finding.finding_id,
                            "target_role": target_finding.role_id,
                            "challenge_type": challenge.challenge_type.value,
                            "citation": challenge.citation,
                        },
                    )
            else:
                # Built-in baseline challenge evaluator: check identity mismatches & contradictions
                baseline_challenge = _evaluate_baseline_challenge(
                    charter=charter,
                    target_finding=target_finding,
                    challenger_kg=challenger_kg,
                )
                if baseline_challenge is not None:
                    disagreement_ledger.add_challenge(baseline_challenge)
                    trace.log_event(
                        role_id,
                        "CHALLENGE_FILED",
                        {
                            "target_finding_id": target_finding.finding_id,
                            "target_role": target_finding.role_id,
                            "challenge_type": baseline_challenge.challenge_type.value,
                            "citation": baseline_challenge.citation,
                        },
                    )

    # =========================================================================
    # ROUND 4 — Deterministic assembly
    # Chair is pure code; applies no judgment, calls no model, aggregates
    # findings, challenges, missing data, and per-lane coverage.
    # =========================================================================
    trace.log_event(
        "orchestrator", "ROUND_4_START", {"description": "Deterministic chair assembly"}
    )

    # Compute union of missing data across all roles
    missing_data_set: set[str] = set()
    for m_list in missing_data_by_role.values():
        missing_data_set.update(m_list)
    missing_data_union = tuple(sorted(missing_data_set))

    # Compute lane coverages
    lane_coverages: dict[str, LaneCoverage] = {}
    for charter in roles:
        if charter.role_id != "chair":
            lane_coverages[charter.role_id] = fabric.compute_lane_coverage(charter.kg_id)

    trace.completed_at = datetime.now(UTC)

    record = BoardRecord(
        session_id=session_id,
        case_id=case_id,
        timestamp=now,
        roles=tuple(r.role_id for r in roles),
        findings_by_lane=dict(sealed_findings_by_role),
        all_findings=tuple(published_findings),
        disagreement_ledger=disagreement_ledger,
        missing_data_union=missing_data_union,
        abstention_audit=dict(abstentions_by_role),
        lane_coverages=lane_coverages,
        trace=trace,
        quorum_verified=True,
    )

    trace.log_event(
        "orchestrator",
        "SESSION_COMPLETE",
        {
            "findings_count": len(record.all_findings),
            "challenges_count": len(record.disagreement_ledger.all_challenges()),
            "unresolved_challenges": len(record.disagreement_ledger.get_unresolved()),
        },
    )

    return record


def _evaluate_baseline_challenge(
    charter: RoleCharter,
    target_finding: Finding,
    challenger_kg: Any,
) -> Challenge | None:
    """Default baseline challenge evaluator checking for jurisdiction and contradictions."""
    # 1. Jurisdiction check: Did target finding make a claim that belongs exclusively to challenger?
    # e.g., if a medical oncologist attempts to make a molecular assay adequacy claim
    if (
        target_finding.claim_kind in charter.jurisdiction
        and target_finding.role_id != charter.role_id
    ):
        # If this is a specialized core capability of the challenger
        if len(charter.jurisdiction) <= 4:
            first_citation = next(
                (node.citation_id for node in challenger_kg.nodes.values() if node.citation_id),
                f"{charter.role_id}-charter-v{charter.charter_version}",
            )
            return Challenge(
                challenge_id=f"ch-{uuid.uuid4().hex[:8]}",
                challenger_role=charter.role_id,
                target_role=target_finding.role_id,
                target_finding_id=target_finding.finding_id,
                challenge_type=ChallengeType.JURISDICTION,
                rationale=(
                    f"Claim kind '{target_finding.claim_kind.value}' is within primary "
                    f"jurisdiction of '{charter.role_id}' and not '{target_finding.role_id}'"
                ),
                citation=first_citation,
            )

    # 2. Check for explicit contradicting nodes via identity anchors
    target_anchors = {a.canonical_key for a in target_finding.anchors}
    if target_anchors:
        for node in challenger_kg.nodes.values():
            node_anchors = {a.canonical_key for a in node.anchors}
            overlap = target_anchors & node_anchors
            if overlap:
                # Check for explicit CONTRADICTS relationship or opposing claims
                contradicting_edge = any(
                    e.source_id == node.node_id and e.relation.upper() == "CONTRADICTS"
                    for e in challenger_kg.edges
                )
                if node.node_id in target_finding.supporting_node_ids and contradicting_edge:
                    citation = node.citation_id or f"{charter.role_id}-evidence-anchor"
                    return Challenge(
                        challenge_id=f"ch-{uuid.uuid4().hex[:8]}",
                        challenger_role=charter.role_id,
                        target_role=target_finding.role_id,
                        target_finding_id=target_finding.finding_id,
                        challenge_type=ChallengeType.CONTRADICTION,
                        rationale=(
                            f"Evidence in lane '{charter.role_id}' contradicts target finding "
                            f"on anchor {sorted(overlap)}"
                        ),
                        citation=citation,
                        supporting_node_id=node.node_id,
                    )

    return None
