"""Event fold tests. Pure, offline, no database -- exercises `fold_events`
directly against hand-built `RawEvent` lists.
"""

from datetime import UTC, datetime, timedelta

import pytest

from secondlook.case.state import RawEvent, fold_events

CASE_ID = "11111111-1111-1111-1111-111111111111"

_BASE_DATE = datetime(2026, 1, 1, tzinfo=UTC)


def _event(event_id: str, event_type: str, payload: dict, day_offset: int) -> RawEvent:
    """`day_offset` is days after 2026-01-01 -- avoids the fixed-month bug of
    constructing `datetime(2026, 1, day_offset, ...)` directly, which breaks
    for any offset > 31.
    """
    return RawEvent(
        id=event_id,
        event_type=event_type,
        payload=payload,
        occurred_at=_BASE_DATE + timedelta(days=day_offset),
    )


def test_empty_event_list_produces_empty_state():
    state = fold_events(CASE_ID, [])
    assert state.case_id == CASE_ID
    assert state.alterations == ()
    assert state.biomarkers == {}
    assert state.treatments == ()
    assert state.latest_assessment is None


def test_alteration_observed_is_recorded():
    events = [
        _event(
            "e1",
            "ALTERATION_OBSERVED",
            {"gene": "EGFR", "variant": "T790M", "variant_type": "missense", "assay": "NGS panel"},
            1,
        )
    ]
    state = fold_events(CASE_ID, events)
    assert len(state.alterations) == 1
    assert state.alterations[0].gene == "EGFR"
    assert state.alterations[0].variant == "T790M"
    assert state.alterations[0].event_id == "e1"


def test_repeated_alteration_events_both_appear_in_state():
    """fold_events does not dedupe -- that's the diff engine's job
    (comparing two derived states), not the fold's.
    """
    events = [
        _event("e1", "ALTERATION_OBSERVED", {"gene": "EGFR", "variant": "T790M"}, 1),
        _event("e2", "ALTERATION_OBSERVED", {"gene": "EGFR", "variant": "T790M"}, 5),
    ]
    state = fold_events(CASE_ID, events)
    assert len(state.alterations) == 2


def test_biomarker_measured_keeps_latest_value_per_name():
    events = [
        _event("e1", "BIOMARKER_MEASURED", {"name": "PD-L1", "value": 35.0, "unit": "%"}, 1),
        _event("e2", "BIOMARKER_MEASURED", {"name": "PD-L1", "value": 62.0, "unit": "%"}, 14),
    ]
    state = fold_events(CASE_ID, events)
    assert len(state.biomarkers) == 1
    assert state.biomarkers["PD-L1"].value == 62.0
    assert state.biomarkers["PD-L1"].event_id == "e2"


def test_different_biomarkers_do_not_overwrite_each_other():
    events = [
        _event("e1", "BIOMARKER_MEASURED", {"name": "PD-L1", "value": 35.0}, 1),
        _event("e2", "BIOMARKER_MEASURED", {"name": "TMB", "value": 12.0}, 1),
    ]
    state = fold_events(CASE_ID, events)
    assert set(state.biomarkers) == {"PD-L1", "TMB"}


def test_treatment_line_started_and_stopped_both_kept():
    events = [
        _event("e1", "TREATMENT_LINE", {"regimen": "imatinib", "line": 1, "action": "started"}, 1),
        _event(
            "e2",
            "TREATMENT_LINE",
            {"regimen": "imatinib", "line": 1, "action": "stopped", "reason": "progression"},
            30,
        ),
    ]
    state = fold_events(CASE_ID, events)
    assert len(state.treatments) == 2
    assert {t.action for t in state.treatments} == {"started", "stopped"}


def test_disease_assessment_latest_assessment_reflects_most_recent():
    events = [
        _event("e1", "DISEASE_ASSESSMENT", {"status": "stable"}, 1),
        _event("e2", "DISEASE_ASSESSMENT", {"status": "progression"}, 60),
    ]
    state = fold_events(CASE_ID, events)
    assert state.latest_assessment == "progression"
    assert len(state.assessments) == 2


def test_clinical_question_is_recorded():
    events = [
        _event("e1", "CLINICAL_QUESTION", {"text": "Any targeted option for this fusion?"}, 1)
    ]
    state = fold_events(CASE_ID, events)
    assert state.clinical_questions == ("Any targeted option for this fusion?",)


def test_unknown_event_type_raises_rather_than_silently_dropping():
    """IMPLEMENTATION_PLAN.md SS13.1: no silent gaps."""
    events = [_event("e1", "SOMETHING_NEW", {}, 1)]
    with pytest.raises(ValueError, match="Unknown event_type"):
        fold_events(CASE_ID, events)


def test_determinism_same_input_same_output_100_runs():
    """The property the whole product rests on (IMPLEMENTATION_PLAN.md SS3.4),
    applied here to the fold itself, not just compute_diff.
    """
    events = [
        _event("e1", "ALTERATION_OBSERVED", {"gene": "EGFR", "variant": "T790M"}, 1),
        _event("e2", "BIOMARKER_MEASURED", {"name": "PD-L1", "value": 62.0}, 14),
        _event(
            "e3", "TREATMENT_LINE", {"regimen": "osimertinib", "line": 2, "action": "started"}, 20
        ),
        _event("e4", "DISEASE_ASSESSMENT", {"status": "response"}, 45),
    ]
    results = [fold_events(CASE_ID, events) for _ in range(100)]
    assert all(r == results[0] for r in results)
