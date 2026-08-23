"""Live Postgres integration tests for CaseStore.

    docker compose up -d postgres
    pytest tests/case -m integration

Deselected by default (`pytest -m integration` to run). Skips cleanly if
Postgres isn't reachable, following the same pattern as
tests/test_tier1_integration.py -- a database being down must produce a
skip, never an error.

The `session` fixture below provisions its own schema per test via
`Base.metadata.create_all`/`drop_all` -- it does NOT need `alembic upgrade
head` run first, and deliberately doesn't depend on Alembic at all, so this
suite stays runnable against a bare, just-started Postgres container.

**Do not run `alembic upgrade head` by hand against the same long-lived
container you're also running this suite against in the same session.**
Alembic's own bookkeeping (the `alembic_version` table) and this fixture's
create_all/drop_all both manage the same tables independently, and mixing
the two leaves Alembic believing revision 0001 is applied while the tables
it created no longer exist (this suite's `drop_all` removes them without
Alembic's knowledge). Neither tool is wrong -- they're just two independent
ways of managing schema, and this repo hasn't chosen to make the test
suite Alembic-aware. If you need to verify the migration itself, use a
throwaway database, or drop and re-`alembic upgrade head` fresh afterward.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get(
    "ATHENA_DATABASE_URL", "postgresql+psycopg://athena:athena@localhost:5432/athena"
)


@pytest.fixture
def session():
    pytest.importorskip("sqlalchemy")
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    from secondlook.case.models import Base

    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip(
            "Postgres not reachable at ATHENA_DATABASE_URL; run `docker compose up -d postgres`"
        )

    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
        db_session.rollback()
    Base.metadata.drop_all(engine)


def test_create_case_and_append_event_round_trip(session):
    from secondlook.case.store import CaseStore

    store = CaseStore(session)
    case = store.create_case(
        label="Case A — synthetic", cancer_type="Synovial sarcoma", age_years=34
    )

    event = store.append_event(
        case.id,
        event_type="ALTERATION_OBSERVED",
        payload={"gene": "EGFR", "variant": "T790M", "assay": "NGS panel"},
        occurred_at=datetime(2026, 2, 14, tzinfo=UTC),
    )

    events = store.list_events(case.id)
    assert len(events) == 1
    assert events[0].id == event.id


def test_append_event_rejects_unknown_event_type(session):
    from secondlook.case.store import CaseStore

    store = CaseStore(session)
    case = store.create_case(label="Case B", cancer_type="NSCLC")

    with pytest.raises(ValueError, match="Unknown event_type"):
        store.append_event(
            case.id,
            event_type="NOT_A_REAL_TYPE",
            payload={},
            occurred_at=datetime.now(UTC),
        )


def test_case_store_exposes_no_event_mutation_methods():
    """The append-only invariant, enforced in code: CaseStore has no
    update_event or delete_event method at all. This is the test that fails
    CI if a future PR adds one.
    """
    from secondlook.case.store import CaseStore

    forbidden = {"update_event", "delete_event", "edit_event", "remove_event"}
    present = forbidden & set(dir(CaseStore))
    assert not present, f"CaseStore must never expose event mutation methods: {present}"


def test_derive_state_folds_events_in_occurred_at_order(session):
    from secondlook.case.store import CaseStore

    store = CaseStore(session)
    case = store.create_case(label="Case C", cancer_type="Sarcoma")

    # Insert out of chronological order -- list_events must still return
    # them sorted by occurred_at, since fold_events relies on that ordering.
    store.append_event(
        case.id,
        event_type="DISEASE_ASSESSMENT",
        payload={"status": "progression"},
        occurred_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    store.append_event(
        case.id,
        event_type="DISEASE_ASSESSMENT",
        payload={"status": "stable"},
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    state = store.derive_state(case.id)
    assert state.latest_assessment == "progression"


def test_mark_superseded_never_deletes_the_finding(session):
    from secondlook.case.store import CaseStore

    store = CaseStore(session)
    case = store.create_case(label="Case D", cancer_type="Sarcoma")
    question = store.create_question(case.id, text="Any targeted option?", priority=1)
    finding = store.create_finding(
        question.id,
        claim="No known alteration in EGFR",
        evidence_class="documented",
        evidence_ref={"source": "CIViC", "civic_id": "123", "url": "https://civicdb.org/123"},
        assumptions=[],
    )
    event = store.append_event(
        case.id,
        event_type="ALTERATION_OBSERVED",
        payload={"gene": "EGFR", "variant": "T790M"},
        occurred_at=datetime.now(UTC),
    )

    updated = store.mark_superseded(
        finding.id, superseded_by=event.id, note="This assumed no known alteration in EGFR."
    )

    assert updated.status == "superseded"
    assert updated.id == finding.id  # same row, not deleted and recreated
    assert updated.superseded_note == "This assumed no known alteration in EGFR."
