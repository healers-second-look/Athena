"""Agent Harness Runtime.

Subsystem Y (Issue #80, P0).

Executes a single tumor board role under strict isolation:
1. Loads role charter from registry.
2. Binds only explicitly allowed tools.
3. Restricts KG access strictly to charter.kg_id; reading an out-of-charter
   graph fails the call immediately with SandboxedKGViolationError.
4. Executes at temperature 0 against pinned models or deterministic generators.
5. Records the complete execution trace in SessionTrace.
6. Enforces that emitted findings comply strictly with the role's jurisdiction
   and prohibited claim lists. Any violation fails immediately (no warning).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from secondlook.board.charters import (
    CharterRegistry,
    ClaimKind,
    JurisdictionViolationError,
    RoleCharter,
)
from secondlook.board.fabric import (
    ComputedCitationForbiddenError,
    EvidenceClass,
    GraphFabric,
    IdentityAnchor,
    RoleKnowledgeGraph,
)


class RuntimeJurisdictionError(JurisdictionViolationError):
    """Raised at runtime when an agent emits a claim outside its charter jurisdiction."""


class SandboxedKGViolationError(PermissionError):
    """Raised when an agent attempts to access a knowledge graph outside its charter."""


class UnstructuredClaimError(ValueError):
    """Raised when an agent outputs unstructured, untyped, or empty claims."""


class ToolNotPermittedError(PermissionError):
    """Raised when an agent attempts to execute a tool not in its charter's allowed list."""


@dataclass(frozen=True)
class Finding:
    """An immutable, structured finding produced by a single role."""

    finding_id: str
    role_id: str
    claim_kind: ClaimKind
    statement: str
    evidence_class: EvidenceClass
    anchors: tuple[IdentityAnchor, ...] = ()
    citations: tuple[str, ...] = ()
    citation_urls: tuple[str, ...] = ()
    supporting_node_ids: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    abstentions: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.finding_id:
            raise ValueError("finding_id cannot be empty")
        if not self.role_id:
            raise ValueError("role_id cannot be empty")
        if not self.statement or not self.statement.strip():
            raise UnstructuredClaimError("Finding statement cannot be blank or empty")

        # Invariant: Computed evidence cannot carry citations (ARCHITECTURE.md §5)
        if self.evidence_class == EvidenceClass.COMPUTED and (self.citations or self.citation_urls):
            raise ComputedCitationForbiddenError(
                f"Finding '{self.finding_id}' with evidence_class=COMPUTED cannot carry citations"
            )


@dataclass
class SessionTrace:
    """Audit log recording all role calls, tool invocations, inputs, and outputs."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    records_by_role: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def log_event(self, role_id: str, event_type: str, data: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "role_id": role_id,
            "event_type": event_type,
            "data": data,
        }
        self.events.append(entry)
        self.records_by_role.setdefault(role_id, []).append(entry)


@dataclass(frozen=True)
class RoleExecutionRequest:
    """Payload passed into a role execution step."""

    role: RoleCharter
    case_state: Any
    kg: RoleKnowledgeGraph
    round_number: int
    published_findings: tuple[Finding, ...] = ()
    temperature: float = 0.0
    model_id: str = "pinned-deterministic"


@dataclass(frozen=True)
class RoleExecutionResult:
    """Output from a role execution step."""

    role_id: str
    findings: tuple[Finding, ...] = ()
    missing_data: tuple[str, ...] = ()
    abstentions: tuple[str, ...] = ()
    tools_executed: tuple[str, ...] = ()
    execution_time_ms: float = 0.0


# Signature for a role runner callable: (request, tool_invoker) -> RoleExecutionResult
RoleRunner = Callable[
    [RoleExecutionRequest, Callable[[str, dict[str, Any]], Any]], RoleExecutionResult
]


class AgentHarness:
    """Runtime harness executing roles within their sandboxed boundaries."""

    def __init__(
        self,
        registry: CharterRegistry,
        fabric: GraphFabric,
        trace: SessionTrace | None = None,
        runners: dict[str, RoleRunner] | None = None,
    ) -> None:
        self.registry = registry
        self.fabric = fabric
        self.trace = trace or SessionTrace()
        self.runners = dict(runners or {})

    def register_runner(self, role_id: str, runner: RoleRunner) -> None:
        self.runners[role_id] = runner

    def execute_role(
        self,
        role_id: str,
        case_state: Any,
        round_number: int,
        published_findings: tuple[Finding, ...] = (),
        requested_kg_id: str | None = None,
    ) -> RoleExecutionResult:
        """Executes a single role with sandboxed KG access and strict jurisdiction enforcement."""
        charter = self.registry.get(role_id)
        target_kg_id = requested_kg_id or charter.kg_id

        # Invariant: Sandboxed KG verification (cannot access any KG outside charter)
        if target_kg_id != charter.kg_id:
            msg = (
                f"Role '{role_id}' requested access to KG '{target_kg_id}', "
                f"but charter restricts access strictly to '{charter.kg_id}'"
            )
            self.trace.log_event(role_id, "SANDBOX_VIOLATION", {"error": msg})
            raise SandboxedKGViolationError(msg)

        kg = self.fabric.get_graph(charter.kg_id)
        self.trace.log_event(
            role_id,
            "ROLE_START",
            {
                "round": round_number,
                "kg_id": charter.kg_id,
                "node_count": len(kg.nodes),
            },
        )

        executed_tools: list[str] = []

        def tool_invoker(tool_name: str, args: dict[str, Any]) -> Any:
            if tool_name not in charter.allowed_tools:
                err_msg = (
                    f"Role '{role_id}' attempted to call tool '{tool_name}' "
                    f"not in allowed_tools {charter.allowed_tools}"
                )
                self.trace.log_event(role_id, "TOOL_PERMISSION_DENIED", {"tool": tool_name})
                raise ToolNotPermittedError(err_msg)
            executed_tools.append(tool_name)
            self.trace.log_event(role_id, "TOOL_CALL", {"tool": tool_name, "args": args})
            return {"status": "ok", "tool": tool_name}

        request = RoleExecutionRequest(
            role=charter,
            case_state=case_state,
            kg=kg,
            round_number=round_number,
            published_findings=published_findings,
            temperature=0.0,
            model_id="pinned-deterministic",
        )

        start_t = time.perf_counter()
        runner = self.runners.get(role_id)

        if runner is not None:
            raw_result = runner(request, tool_invoker)
        else:
            # Default deterministic baseline runner
            raw_result = self._default_deterministic_runner(request, tool_invoker)

        duration_ms = (time.perf_counter() - start_t) * 1000.0

        # Enforce jurisdiction and prohibition invariants on emitted findings
        for finding in raw_result.findings:
            if finding.claim_kind in charter.prohibited_claims:
                err = (
                    f"Role '{role_id}' emitted prohibited claim '{finding.claim_kind.value}' "
                    f"in finding '{finding.finding_id}'"
                )
                self.trace.log_event(role_id, "JURISDICTION_BREACH", {"error": err})
                raise RuntimeJurisdictionError(err)

            if finding.claim_kind not in charter.jurisdiction:
                err = (
                    f"Role '{role_id}' emitted claim '{finding.claim_kind.value}' "
                    f"outside its declared jurisdiction in finding '{finding.finding_id}'"
                )
                self.trace.log_event(role_id, "JURISDICTION_BREACH", {"error": err})
                raise RuntimeJurisdictionError(err)

        result = RoleExecutionResult(
            role_id=role_id,
            findings=raw_result.findings,
            missing_data=raw_result.missing_data,
            abstentions=raw_result.abstentions,
            tools_executed=tuple(executed_tools),
            execution_time_ms=duration_ms,
        )

        self.trace.log_event(
            role_id,
            "ROLE_COMPLETE",
            {
                "finding_count": len(result.findings),
                "missing_data_count": len(result.missing_data),
                "abstention_count": len(result.abstentions),
                "duration_ms": duration_ms,
            },
        )
        return result

    def _default_deterministic_runner(
        self,
        request: RoleExecutionRequest,
        tool_invoker: Callable[[str, dict[str, Any]], Any],
    ) -> RoleExecutionResult:
        """Baseline deterministic generator reading facts directly from the role's KG."""
        findings: list[Finding] = []
        kg = request.kg
        charter = request.role

        if charter.allowed_tools:
            tool_invoker(
                charter.allowed_tools[0],
                {"case_id": getattr(request.case_state, "case_id", "default")},
            )

        first_jurisdiction = charter.jurisdiction[0] if charter.jurisdiction else None

        for node in kg.nodes.values():
            if first_jurisdiction:
                citation_tuple = (node.citation_id,) if node.citation_id else ()
                url_tuple = (node.citation_url,) if node.citation_url else ()
                f = Finding(
                    finding_id=f"fnd-{node.node_id}",
                    role_id=charter.role_id,
                    claim_kind=first_jurisdiction,
                    statement=node.claim,
                    evidence_class=node.evidence_class,
                    anchors=node.anchors,
                    citations=(
                        citation_tuple if node.evidence_class != EvidenceClass.COMPUTED else ()
                    ),
                    citation_urls=(
                        url_tuple if node.evidence_class != EvidenceClass.COMPUTED else ()
                    ),
                    supporting_node_ids=(node.node_id,),
                    caveats=node.caveats,
                )
                findings.append(f)

        return RoleExecutionResult(
            role_id=charter.role_id,
            findings=tuple(findings),
            missing_data=(),
            abstentions=(),
            tools_executed=tuple(charter.allowed_tools[:1]),
        )
