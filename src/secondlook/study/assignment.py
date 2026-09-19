"""Deterministic arm/case schedule for a study reviewer (protocol section 2).

Arm order follows a 3x3 Latin square across reviewers (reviewer index mod 3),
and each reviewer reads a contiguous, wrapping window of the case pool, so
across reviewers every case is seen in every arm. No RNG is involved: the
schedule is a pure function of (reviewer index, pool), so it can be committed
and audited before the first session, which the protocol's freeze step
requires.

Exact balance holds when the pool holds twice a reviewer's slots (a pool of 18
with 9 slots) and the reviewer count is a multiple of 6; other geometries are
only approximately balanced, and `arm_case_counts` lets a caller check.
"""

from __future__ import annotations

from collections import Counter

ARM_ORDERS: tuple[tuple[str, str, str], ...] = (
    ("diff_first", "dashboard", "chat"),
    ("dashboard", "chat", "diff_first"),
    ("chat", "diff_first", "dashboard"),
)


def build_schedule(
    reviewer_index: int, case_ids: list[str], *, cases_per_arm: int = 3
) -> list[tuple[str, str]]:
    """Ordered (case_id, arm) pairs for one reviewer: block 1 in the first arm, etc."""
    if reviewer_index < 0:
        raise ValueError("reviewer_index must be >= 0")
    if cases_per_arm < 1:
        raise ValueError("cases_per_arm must be >= 1")
    slots = cases_per_arm * len(ARM_ORDERS[0])
    pool = len(case_ids)
    if len(set(case_ids)) != pool:
        raise ValueError("case_ids must be unique")
    if pool < slots:
        raise ValueError(
            f"need at least {slots} cases for {cases_per_arm} per arm, pool has {pool}"
        )
    order = ARM_ORDERS[reviewer_index % len(ARM_ORDERS)]
    start = (reviewer_index * slots) % pool
    return [
        (case_ids[(start + slot) % pool], order[slot // cases_per_arm]) for slot in range(slots)
    ]


def arm_case_counts(
    reviewer_count: int, case_ids: list[str], *, cases_per_arm: int = 3
) -> Counter[tuple[str, str]]:
    """How often each (case, arm) pair occurs across reviewers 0..reviewer_count-1."""
    counts: Counter[tuple[str, str]] = Counter()
    for reviewer in range(reviewer_count):
        counts.update(build_schedule(reviewer, case_ids, cases_per_arm=cases_per_arm))
    return counts
