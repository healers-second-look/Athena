"""Tests for the study event log (issue #136). Real SQL against in-memory SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from secondlook.case.models import NO_PHI_COLUMN_PATTERN, Base
from secondlook.study.events import (
    ARMS,
    MAX_BATCH,
    STUDY_EVENT_TYPES,
    InvalidStudyEvent,
    NewStudyEvent,
    StudyEvent,
    StudyEventStore,
)

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def _event(**overrides) -> NewStudyEvent:
    base = {
        "participant_id": "P01",
        "session_id": "S1",
        "case_id": "pilot-001",
        "arm": "diff_first",
        "event_type": "case_opened",
        "client_ts": T0,
        "payload": {},
    }
    base.update(overrides)
    return NewStudyEvent(**base)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    StudyEvent.__table__.create(engine)
    with Session(engine) as s:
        yield s


def test_events_round_trip_in_client_time_order(session):
    store = StudyEventStore(session)
    later = _event(event_type="case_submitted", client_ts=T0 + timedelta(minutes=5))
    earlier = _event(event_type="case_opened", client_ts=T0)
    assert store.append_many([later, earlier]) == 2
    rows = store.list_events(participant_id="P01")
    assert [r.event_type for r in rows] == ["case_opened", "case_submitted"]


def test_list_filters_by_participant_and_case(session):
    store = StudyEventStore(session)
    store.append_many(
        [
            _event(participant_id="P01", case_id="pilot-001"),
            _event(participant_id="P01", case_id="pilot-002"),
            _event(participant_id="P02", case_id="pilot-001"),
        ]
    )
    assert len(store.list_events(participant_id="P01")) == 2
    assert len(store.list_events(case_id="pilot-001")) == 2
    assert len(store.list_events(participant_id="P02", case_id="pilot-002")) == 0


def test_payload_is_stored_as_given(session):
    store = StudyEventStore(session)
    store.append_many([_event(event_type="confidence_set", payload={"finding": "p1-f1", "v": 80})])
    assert store.list_events()[0].payload == {"finding": "p1-f1", "v": 80}


def test_a_batch_with_one_bad_event_writes_nothing(session):
    store = StudyEventStore(session)
    with pytest.raises(InvalidStudyEvent):
        store.append_many([_event(), _event(event_type="not_a_real_type")])
    assert store.list_events() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"arm": "chat-ish"},
        {"event_type": "typo_event"},
        {"client_ts": datetime(2026, 1, 1, 9, 0)},  # naive
        {"participant_id": "someone@example.org"},  # an email is not a pseudonym
        {"participant_id": "Jane Doe"},
        {"participant_id": ""},
        {"case_id": "x" * 65},
        {"payload": {"blob": "x" * 9000}},
    ],
)
def test_invalid_events_are_rejected(session, overrides):
    with pytest.raises(InvalidStudyEvent):
        StudyEventStore(session).append_many([_event(**overrides)])


def test_batch_size_is_bounded(session):
    store = StudyEventStore(session)
    with pytest.raises(InvalidStudyEvent):
        store.append_many([])
    with pytest.raises(InvalidStudyEvent):
        store.append_many([_event() for _ in range(MAX_BATCH + 1)])


def test_the_store_has_no_update_or_delete_path():
    """Append-only is enforced by the class simply having no such method,
    same as case/store.py -- a future change that adds one fails here."""
    for name in dir(StudyEventStore):
        assert not name.startswith(("update", "delete", "remove", "clear")), name


def test_vocabulary_covers_the_protocols_outcomes():
    # Verification behaviour, calibration, decision, burden, recall, time:
    for needed in (
        "citation_opened",
        "confidence_set",
        "flag_set",
        "decision_submitted",
        "tlx_submitted",
        "recall_submitted",
        "case_opened",
        "case_submitted",
    ):
        assert needed in STUDY_EVENT_TYPES
    assert set(ARMS) == {"diff_first", "dashboard", "chat"}


def test_table_is_registered_and_carries_no_phi_columns():
    table = Base.metadata.tables["study_events"]
    for column in table.columns:
        assert not NO_PHI_COLUMN_PATTERN.search(column.name), column.name


def test_migration_and_model_declare_the_same_columns():
    """The migration is hand-written (like 0002's), so guard against drift."""
    import re
    from pathlib import Path

    migration = Path(__file__).parents[2] / "migrations" / "versions" / "0004_study_events.py"
    declared = set(re.findall(r'sa\.Column\(\s*"(\w+)"', migration.read_text(encoding="utf-8")))
    assert declared == {c.name for c in Base.metadata.tables["study_events"].columns}
