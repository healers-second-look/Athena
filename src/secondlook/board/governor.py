"""Cost & Latency Governor.

Subsystem AE (Issue #86, P2).

Enforces per-case budget and per-role latency ceilings:
1. Tracks cumulative token consumption and execution latency per seat.
2. Triggers deterministic degrade path: If a seat breaches its ceiling,
   its lane is flagged as degraded, an abstention notice is recorded,
   and the orchestrator continues without crashing the board.
3. Degraded status is explicitly preserved on the final BoardRecord.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class GovernorLimitExceededError(TimeoutError):
    """Raised when hard governor limits are breached and no degrade path is configured."""


@dataclass(frozen=True)
class GovernorConfig:
    """Configurable budget and latency constraints."""

    max_case_tokens: int = 50_000
    per_role_token_limit: int = 10_000
    per_role_timeout_ms: float = 10_000.0
    allow_graceful_degrade: bool = True


@dataclass
class GovernorState:
    """Execution state tracking token spend and latency across roles."""

    total_tokens_consumed: int = 0
    tokens_by_role: dict[str, int] = field(default_factory=dict)
    latency_ms_by_role: dict[str, float] = field(default_factory=dict)
    degraded_roles: set[str] = field(default_factory=set)


class BoardGovernor:
    """Governs runtime resource usage and manages graceful degradation."""

    def __init__(self, config: GovernorConfig | None = None) -> None:
        self.config = config or GovernorConfig()
        self.state = GovernorState()

    def record_usage(
        self,
        role_id: str,
        tokens_used: int,
        duration_ms: float,
    ) -> bool:
        """Records seat usage and returns True if healthy, False if degraded."""
        self.state.total_tokens_consumed += tokens_used
        prev_tok = self.state.tokens_by_role.get(role_id, 0)
        self.state.tokens_by_role[role_id] = prev_tok + tokens_used

        prev_lat = self.state.latency_ms_by_role.get(role_id, 0.0)
        self.state.latency_ms_by_role[role_id] = prev_lat + duration_ms

        breached = False
        reasons: list[str] = []

        if duration_ms > self.config.per_role_timeout_ms:
            breached = True
            reasons.append(f"latency ({duration_ms:.1f}ms > {self.config.per_role_timeout_ms}ms)")

        if self.state.tokens_by_role[role_id] > self.config.per_role_token_limit:
            breached = True
            reasons.append("per-role token limit exceeded")

        if self.state.total_tokens_consumed > self.config.max_case_tokens:
            breached = True
            reasons.append("case-wide token limit exceeded")

        if breached:
            if not self.config.allow_graceful_degrade:
                raise GovernorLimitExceededError(
                    f"Governor halted session for role '{role_id}': {', '.join(reasons)}"
                )
            self.state.degraded_roles.add(role_id)
            return False

        return True

    def is_degraded(self, role_id: str) -> bool:
        return role_id in self.state.degraded_roles
