"""Tests for per-arm reviewer views and task question stripping."""

from __future__ import annotations

from pathlib import Path

import pytest

from secondlook.study.cases import DEFAULT_CASE_SET_DIR, load_case_set
from secondlook.study.views import reviewer_view

ATHENA_VS = DEFAULT_CASE_SET_DIR / "athena_vs_usual_v1.yaml"


@pytest.fixture
def avu_case():
    case = load_case_set(ATHENA_VS).cases[0]
    assert case.tasks is not None
    return case


def test_reviewer_view_exposes_task_questions_only(avu_case):
    view = reviewer_view(avu_case, "athena_full")
    assert view.tasks is not None
    assert view.tasks.evidence_lookup.question == avu_case.tasks.evidence_lookup.question
    assert view.tasks.trial_match.question == avu_case.tasks.trial_match.question
    assert view.tasks.trial_match.region == avu_case.tasks.trial_match.region
    assert view.tasks.decision_rationale is not None


def test_reviewer_view_json_contains_no_gold_or_trial_ids(avu_case):
    view = reviewer_view(avu_case, "usual_care")
    blob = view.model_dump_json()
    assert avu_case.tasks.evidence_lookup.gold_answer not in blob
    for trial_id in avu_case.tasks.trial_match.eligible_trial_ids:
        assert trial_id not in blob
    assert avu_case.tasks.trial_match.snapshot_date not in blob


def test_athena_full_arm_includes_diff_usual_care_does_not(avu_case):
    full = reviewer_view(avu_case, "athena_full")
    usual = reviewer_view(avu_case, "usual_care")
    assert full.reported_changes
    assert full.reported_supersessions or full.questions
    assert usual.reported_changes == []
    assert usual.reported_supersessions == []
    assert usual.questions == []


def test_pilot_cases_without_tasks_have_no_tasks_field():
    pilot = load_case_set(DEFAULT_CASE_SET_DIR / "pilot_v0.yaml").cases[0]
    view = reviewer_view(pilot, "diff_first")
    assert view.tasks is None