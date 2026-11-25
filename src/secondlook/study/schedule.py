"""Shared enrolled-participant (case, arm) schedule for authorization checks."""

from __future__ import annotations

from secondlook.study.assignment import USUAL_VS_ATHENA_ORDERS, build_schedule
from secondlook.study.enrollment import cases_per_arm_for_usual_vs


def participant_case_schedule(
    reviewer_index: int,
    case_ids: list[str],
) -> list[tuple[str, str]]:
    """Ordered (case_id, arm) pairs for the usual-care vs athena_full protocol."""
    per_arm = cases_per_arm_for_usual_vs(len(case_ids))
    return build_schedule(
        reviewer_index,
        case_ids,
        cases_per_arm=per_arm,
        arm_orders=USUAL_VS_ATHENA_ORDERS,
    )


def schedule_contains(
    schedule: list[tuple[str, str]],
    *,
    case_id: str,
    arm: str,
) -> bool:
    return (case_id, arm) in schedule


__all__ = ["participant_case_schedule", "schedule_contains"]