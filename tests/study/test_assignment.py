"""Tests for the deterministic arm/case schedule (issue #136, protocol section 2)."""

from __future__ import annotations

from collections import Counter

import pytest

from secondlook.study.assignment import ARM_ORDERS, arm_case_counts, build_schedule

POOL = [f"case-{i:02d}" for i in range(18)]


def test_schedule_has_three_blocks_one_per_arm():
    schedule = build_schedule(0, POOL)
    assert len(schedule) == 9
    arms_in_order = [arm for _, arm in schedule]
    assert arms_in_order == ["diff_first"] * 3 + ["dashboard"] * 3 + ["chat"] * 3


def test_a_reviewer_never_sees_the_same_case_twice():
    for reviewer in range(12):
        cases = [c for c, _ in build_schedule(reviewer, POOL)]
        assert len(cases) == len(set(cases))


def test_arm_order_follows_a_latin_square():
    firsts = [build_schedule(r, POOL)[0][1] for r in range(3)]
    assert sorted(firsts) == sorted(["diff_first", "dashboard", "chat"])
    for arm_position in range(3):
        assert len({order[arm_position] for order in ARM_ORDERS}) == 3


def test_schedule_is_a_pure_function_of_its_inputs():
    assert build_schedule(4, POOL) == build_schedule(4, POOL)


def test_pool_of_eighteen_and_six_reviewers_is_perfectly_balanced():
    counts = arm_case_counts(6, POOL)
    assert set(counts.values()) == {1}  # every (case, arm) pair exactly once...
    assert len(counts) == 54  # 6 reviewers x 9 slots, all distinct
    per_case_arms = Counter(case for case, _ in counts)
    assert set(per_case_arms.values()) == {3}  # ...so each case meets all three arms


def test_larger_panels_stay_balanced_in_multiples_of_six():
    counts = arm_case_counts(12, POOL)
    assert set(counts.values()) == {2}


def test_cases_per_arm_can_shrink_for_a_dry_run():
    schedule = build_schedule(0, ["a", "b", "c", "d", "e"], cases_per_arm=1)
    assert len(schedule) == 3


@pytest.mark.parametrize(
    "kwargs, pool",
    [
        ({"reviewer_index": -1}, POOL),
        ({"reviewer_index": 0, "cases_per_arm": 0}, POOL),
        ({"reviewer_index": 0}, POOL[:5]),  # too few cases for 9 slots
        ({"reviewer_index": 0}, ["a", "a"] + POOL),  # duplicates
    ],
)
def test_bad_inputs_are_rejected(kwargs, pool):
    with pytest.raises(ValueError):
        build_schedule(case_ids=pool, **kwargs)
