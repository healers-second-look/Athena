"""Clinician Feedback & Overrule Capture.

Subsystem AD (Issue #85, P1).

Captures structured clinician overrules on findings and challenges:
1. Every overrule requires an explicit, non-empty clinical justification.
2. Overrules feed:
   - Subsystem Z eval sets (gold-standard negative/positive labels).
   - Subsystem V curation queue (often points to an uncurated KG gap).
3. HARD CAVEAT (§8): Overrules are for audit, curation, and eval sets ONLY.
   They are strictly forbidden from being used for unattended prompt drift
   or online model fine-tuning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal


class OverruleAction(StrEnum):
    OVERRULE_REJECTED = "overrule_rejected"
    OVERRULE_MODIFIED = "overrule_modified"
    OVERRULE_AFFIRMED = "overrule_affirmed"


class MissingOverruleReasonError(ValueError):
    """Raised when a clinician overrule is submitted without a mandatory clinical reason."""


@dataclass(frozen=True)
class ClinicianOverrule:
    """An immutable, structured record of a human clinician's judgment."""

    overrule_id: str
    session_id: str
    target_type: Literal["finding", "challenge"]
    target_id: str
    role_id: str
    clinician_id: str
    action: OverruleAction
    mandatory_reason: str
    suggested_alternative: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.overrule_id:
            raise ValueError("overrule_id cannot be empty")
        if not self.session_id:
            raise ValueError("session_id cannot be empty")
        if not self.target_id:
            raise ValueError("target_id cannot be empty")
        if not self.clinician_id:
            raise ValueError("clinician_id cannot be empty")

        # Invariant: A clinical overrule must carry a non-empty reason
        if not self.mandatory_reason or not self.mandatory_reason.strip():
            raise MissingOverruleReasonError(
                f"Overrule on {self.target_type} '{self.target_id}' must provide a mandatory reason"
            )


class OverruleLedger:
    """Durable ledger of clinician overrules and feedback."""

    def __init__(self, overrules: list[ClinicianOverrule] | None = None) -> None:
        self._overrules: list[ClinicianOverrule] = list(overrules or [])

    def record_overrule(self, overrule: ClinicianOverrule) -> None:
        self._overrules.append(overrule)

    def all_overrules(self) -> tuple[ClinicianOverrule, ...]:
        return tuple(self._overrules)

    def get_for_session(self, session_id: str) -> tuple[ClinicianOverrule, ...]:
        return tuple(o for o in self._overrules if o.session_id == session_id)

    def get_curation_queue(self) -> list[dict[str, Any]]:
        """Extracts items indicating missing or contested KG evidence for Subsystem V."""
        queue: list[dict[str, Any]] = []
        for o in self._overrules:
            if o.action in (OverruleAction.OVERRULE_REJECTED, OverruleAction.OVERRULE_MODIFIED):
                queue.append(
                    {
                        "source": "clinician_overrule",
                        "target_role": o.role_id,
                        "target_id": o.target_id,
                        "reason": o.mandatory_reason,
                        "suggested_alternative": o.suggested_alternative,
                        "timestamp": o.created_at.isoformat(),
                    }
                )
        return queue

    def export_eval_labels(self) -> list[dict[str, Any]]:
        """Exports structured supervision labels for Subsystem Z evaluation."""
        return [
            {
                "target_id": o.target_id,
                "action": o.action.value,
                "role_id": o.role_id,
                "reason": o.mandatory_reason,
            }
            for o in self._overrules
        ]
