"""Tests for the study case-set format, validator and eligibility gate (issue #136)."""

from __future__ import annotations

from dataclasses import replace

import pytest
import yaml

from secondlook.study.cases import (
    DEFAULT_CASE_SET_DIR,
    CaseSetError,
    IneligibleCaseSetError,
    assert_eligible_for_study,
    content_hash,
    load_case_set,
    parse_case_set,
    prevalence,
    validate_case,
    validate_case_set,
)

PILOT = DEFAULT_CASE_SET_DIR / "pilot_v0.yaml"


@pytest.fixture
def pilot():
    return load_case_set(PILOT)


def _case(pilot, case_id):
    return next(c for c in pilot.cases if c.case_id == case_id)


def _raw():
    with open(PILOT, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# --- the shipped pilot set -----------------------------------------------------


def test_pilot_set_is_internally_consistent(pilot):
    assert validate_case_set(pilot) == []


def test_pilot_set_exercises_every_issue_type_and_a_control(pilot):
    counts = prevalence(pilot)
    assert counts["change_visible"] >= 1
    assert counts["change_missed"] >= 1
    assert counts["change_independent"] >= 1
    assert counts["no_issue_controls"] >= 1


def test_pilot_set_is_refused_for_a_study_run(pilot):
    """The pilot is harness-debug only. If this ever passes, an unreviewed set
    with placeholder citations could be run against real reviewers."""
    with pytest.raises(IneligibleCaseSetError) as exc:
        assert_eligible_for_study(pilot)
    joined = " ".join(exc.value.reasons)
    assert "clinician_reviewed" in joined
    assert "citations_verified" in joined


def test_a_reviewed_and_verified_set_is_eligible(pilot):
    reviewed = replace(
        pilot,
        review_status="clinician_reviewed",
        reviewed_by="Dr Example",
        cases=tuple(replace(c, citations_verified=True) for c in pilot.cases),
    )
    assert_eligible_for_study(reviewed)


def test_reviewed_status_without_a_named_reviewer_is_invalid(pilot):
    errs = validate_case_set(replace(pilot, review_status="clinician_reviewed"))
    assert any("reviewed_by" in e for e in errs)


def test_content_hash_is_stable_and_sensitive_to_content(pilot):
    assert content_hash(pilot) == content_hash(load_case_set(PILOT))
    first = pilot.cases[0]
    changed = replace(pilot, cases=(replace(first, label="edited"),) + pilot.cases[1:])
    assert content_hash(changed) != content_hash(pilot)


# --- structural parsing fails closed --------------------------------------------


def test_unknown_key_is_an_error_not_silently_ignored():
    raw = _raw()
    raw["cases"][0]["system_output"]["findings"][0]["vaild"] = True  # typo'd field
    with pytest.raises(CaseSetError, match="unknown key"):
        parse_case_set(raw)


def test_missing_required_key_is_an_error():
    raw = _raw()
    del raw["cases"][0]["reference_decision"]
    with pytest.raises(CaseSetError, match="missing required"):
        parse_case_set(raw)


def test_non_boolean_ground_truth_is_an_error():
    raw = _raw()
    raw["cases"][0]["system_output"]["findings"][0]["valid"] = "false"
    with pytest.raises(CaseSetError, match="boolean"):
        parse_case_set(raw)


# --- semantic rules -----------------------------------------------------------


def test_non_synthetic_case_is_rejected(pilot):
    errs = validate_case(replace(_case(pilot, "pilot-001"), synthetic=False))
    assert any("synthetic" in e for e in errs)


def _with_findings(case, findings):
    return replace(case, system_output=replace(case.system_output, findings=tuple(findings)))


def test_flawed_finding_with_no_seeded_issue_is_rejected(pilot):
    case = _case(pilot, "pilot-003")
    errs = validate_case(replace(case, seeded_issues=()))
    assert any("no seeded issue" in e for e in errs)


def test_change_visible_requires_a_reported_supersession(pilot):
    case = _case(pilot, "pilot-001")
    stripped = replace(case, system_output=replace(case.system_output, reported_supersessions=()))
    errs = validate_case(stripped)
    assert any("change_visible" in e for e in errs)


def test_change_missed_must_not_have_a_reported_supersession(pilot):
    case = _case(pilot, "pilot-001")
    relabelled = replace(
        case, seeded_issues=(replace(case.seeded_issues[0], type="change_missed"),)
    )
    errs = validate_case(relabelled)
    assert any("change_missed" in e for e in errs)


def test_change_independent_must_have_a_flaw_and_no_supersession(pilot):
    case = _case(pilot, "pilot-001")
    relabelled = replace(
        case, seeded_issues=(replace(case.seeded_issues[0], type="change_independent"),)
    )
    errs = validate_case(relabelled)
    assert any("change_independent" in e for e in errs)


def test_superseding_a_valid_finding_is_rejected(pilot):
    case = _case(pilot, "pilot-001")
    valid_id = next(f.id for f in case.system_output.findings if f.valid)
    bogus = replace(case.system_output.reported_supersessions[0], finding_id=valid_id)
    errs = validate_case(
        replace(case, system_output=replace(case.system_output, reported_supersessions=(bogus,)))
    )
    assert any("false supersession" in e for e in errs)


def test_documented_finding_without_a_citation_is_rejected(pilot):
    case = _case(pilot, "pilot-004")
    first, *rest = case.system_output.findings
    errs = validate_case(_with_findings(case, [replace(first, citation=None), *rest]))
    assert any("no citation, no item" in e for e in errs)


def test_computed_finding_must_not_carry_a_citation(pilot):
    case = _case(pilot, "pilot-004")
    first, *rest = case.system_output.findings
    computed = replace(first, evidence_class="computed", method="some-method")
    errs = validate_case(_with_findings(case, [computed, *rest]))
    assert any("computed finding must not carry a citation" in e for e in errs)


def test_invalidated_by_must_be_an_update_event(pilot):
    case = _case(pilot, "pilot-001")
    first, *rest = case.system_output.findings
    errs = validate_case(_with_findings(case, [replace(first, invalidated_by="p1-b1"), *rest]))
    assert any("not an update event" in e for e in errs)


def test_flawed_finding_needs_exactly_one_reason(pilot):
    case = _case(pilot, "pilot-001")
    first, *rest = case.system_output.findings
    both = replace(first, flaw="also flawed for another reason")
    errs = validate_case(_with_findings(case, [both, *rest]))
    assert any("exactly one of invalidated_by or flaw" in e for e in errs)


def test_update_events_must_follow_baseline(pilot):
    case = _case(pilot, "pilot-001")
    early = replace(case.update_events[0], occurred_on="2020-01-01")
    errs = validate_case(replace(case, update_events=(early, *case.update_events[1:])))
    assert any("after every baseline" in e for e in errs)


def test_unknown_event_type_is_rejected(pilot):
    case = _case(pilot, "pilot-001")
    bad = replace(case.baseline_events[0], event_type="NOT_A_TYPE")
    errs = validate_case(replace(case, baseline_events=(bad, *case.baseline_events[1:])))
    assert any("unknown event_type" in e for e in errs)


def test_reference_decision_must_name_real_options(pilot):
    case = _case(pilot, "pilot-001")
    bad = replace(case.reference_decision, concordant=("zzz",))
    errs = validate_case(replace(case, reference_decision=bad))
    assert any("unknown option" in e for e in errs)


def test_duplicate_case_ids_are_rejected(pilot):
    dup = replace(pilot, cases=(pilot.cases[0], pilot.cases[0]))
    assert any("not unique" in e for e in validate_case_set(dup))


def test_recall_distractor_that_is_a_real_event_is_rejected(pilot):
    case = _case(pilot, "pilot-001")
    real = case.update_events[0].summary
    errs = validate_case(replace(case, recall_distractors=(real,)))
    assert any("actually an event" in e for e in errs)


def test_duplicate_or_empty_recall_distractors_are_rejected(pilot):
    case = _case(pilot, "pilot-001")
    errs = validate_case(replace(case, recall_distractors=("Same thing", "same thing", " ")))
    assert any("listed twice" in e for e in errs)
    assert any("is empty" in e for e in errs)
