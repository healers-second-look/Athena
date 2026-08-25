from __future__ import annotations

import uuid
from datetime import UTC, datetime

from secondlook.query.case_summary import get_case_summary

from .fakes import FakeCase, FakeEvent, FakeQuestion, FakeStore


def test_missing_case_is_empty_with_reason():
    result = get_case_summary(FakeStore(), uuid.uuid4())
    assert result.items == ()
    assert result.empty_reason is not None
    assert "no case" in result.empty_reason


def test_summary_folds_events_once_and_counts_questions():
    case_id = uuid.uuid4()
    store = FakeStore(
        case=FakeCase(id=case_id, label="C1", cancer_type="NSCLC", age_years=54),
        events=[
            FakeEvent(
                id=uuid.uuid4(),
                event_type="ALTERATION_OBSERVED",
                payload={"gene": "EGFR", "variant": "T790M"},
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ],
        questions=[
            FakeQuestion(
                id=uuid.uuid4(),
                text="evidence?",
                status="open",
                priority=1,
                created_at=datetime(2026, 1, 2, tzinfo=UTC),
            ),
            FakeQuestion(
                id=uuid.uuid4(),
                text="trials?",
                status="answered",
                priority=2,
                created_at=datetime(2026, 1, 3, tzinfo=UTC),
            ),
        ],
        findings=(),
    )
    result = get_case_summary(store, case_id)
    assert result.empty_reason is None
    summary = result.items[0]
    assert summary.label == "C1"
    assert summary.cancer_type == "NSCLC"
    assert summary.alterations[0].gene == "EGFR"
    assert summary.question_counts["open"] == 1
    assert summary.question_counts["answered"] == 1
    assert summary.active_finding_count == 0


def test_current_state_and_timeline_are_populated_not_just_top_level_alterations():
    """Issue #101: web/src/routes/CaseDashboard.jsx reads `current_state`
    and `timeline`, not just the top-level `alterations` list -- a case
    with real events must not silently render "none recorded" /
    "no events" through those two fields.
    """
    case_id = uuid.uuid4()
    event_id = uuid.uuid4()
    store = FakeStore(
        case=FakeCase(id=case_id, label="C1", cancer_type="NSCLC"),
        events=[
            FakeEvent(
                id=event_id,
                event_type="ALTERATION_OBSERVED",
                payload={"gene": "EGFR", "variant": "T790M"},
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
                source_document="pathology-report-001",
            )
        ],
    )
    summary = get_case_summary(store, case_id).items[0]

    assert summary.current_state.alterations[0].gene == "EGFR"
    assert summary.current_state.alterations[0].variant == "T790M"
    assert summary.current_state.biomarkers == []
    assert summary.current_state.treatments == []
    assert summary.current_state.assessments == []

    assert len(summary.timeline) == 1
    event = summary.timeline[0]
    assert event.id == str(event_id)
    assert event.event_type == "ALTERATION_OBSERVED"
    assert event.payload == {"gene": "EGFR", "variant": "T790M"}
    assert event.source_document == "pathology-report-001"
