"""Repository layer over Postgres for the Case Memory Store.

`CaseStore` is the *only* code path allowed to read or write `case/models.py`
tables. Two things worth knowing before adding a method here:

1. **No `update_event` / `delete_event`.** This is the append-only invariant
   enforced *in code*, not just documented -- `case_events` has no mutation
   path at all through this class. `tests/case/test_store.py` asserts this
   directly (the class has no such attribute), so a future PR that adds one
   fails CI, not just review.
2. **This module does I/O.** Unlike `state.py` (pure) and `diff.py`
   (pure, subsystem D), `CaseStore` methods take a live SQLAlchemy
   `Session` -- injected by the caller, per the project's DI convention, so
   callers (and tests) control the engine/session lifecycle rather than
   this module reaching for a global connection.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from secondlook.case.models import EVENT_TYPES, Case, CaseEvent, Decision, Finding, Question
from secondlook.case.state import CaseState, RawEvent, fold_events


class CaseStore:
    """Thin repository over a SQLAlchemy `Session`. No business logic beyond
    append-only enforcement and event ordering -- diffing, question
    generation, and synthesis live in their own subsystems' modules.
    """

    def __init__(self, session: Session):
        self._session = session

    # -- Case ----------------------------------------------------------

    def create_case(
        self,
        *,
        label: str,
        cancer_type: str,
        age_years: int | None = None,
        primary_site: str | None = None,
        histology: str | None = None,
        doid: str | None = None,
    ) -> Case:
        case = Case(
            id=uuid.uuid4(),
            label=label,
            cancer_type=cancer_type,
            age_years=age_years,
            primary_site=primary_site,
            histology=histology,
            doid=doid,
            created_at=datetime.now(UTC),
        )
        self._session.add(case)
        self._session.flush()
        return case

    def get_case(self, case_id: uuid.UUID) -> Case | None:
        return self._session.get(Case, case_id)

    # -- Events (append-only) -------------------------------------------

    def append_event(
        self,
        case_id: uuid.UUID,
        *,
        event_type: str,
        payload: dict,
        occurred_at: datetime,
        source_document: str | None = None,
        recorded_by: str | None = None,
    ) -> CaseEvent:
        """Append one event. There is deliberately no corresponding
        `update_event`/`delete_event` -- see this module's docstring.
        """
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"Unknown event_type {event_type!r}; must be one of {sorted(EVENT_TYPES)}"
            )
        event = CaseEvent(
            id=uuid.uuid4(),
            case_id=case_id,
            event_type=event_type,
            payload=payload,
            occurred_at=occurred_at,
            recorded_at=datetime.now(UTC),
            source_document=source_document,
            recorded_by=recorded_by,
        )
        self._session.add(event)
        self._session.flush()
        return event

    def list_events(self, case_id: uuid.UUID) -> list[CaseEvent]:
        """Ordered by `occurred_at` ascending -- the order `state.fold_events`
        (and, downstream, `diff.compute_diff`) requires.
        """
        stmt = select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.occurred_at)
        return list(self._session.scalars(stmt))

    def derive_state(self, case_id: uuid.UUID) -> CaseState:
        """Fold this case's full event log into its current `CaseState`.

        To get the state *as of* a prior point in time (e.g. for
        `compute_diff(previous, current, ...)`), the caller filters the
        event list before folding -- `fold_events` itself takes whatever
        list it's given, which is what keeps it pure and reusable for both
        "current state" and "state as of event N" without a second
        implementation.
        """
        events = self.list_events(case_id)
        raw_events = [
            RawEvent(
                id=str(e.id), event_type=e.event_type, payload=e.payload, occurred_at=e.occurred_at
            )
            for e in events
        ]
        return fold_events(str(case_id), raw_events)

    # -- Questions --------------------------------------------------------

    def create_question(
        self,
        case_id: uuid.UUID,
        *,
        text: str,
        status: str = "open",
        priority: int,
        triggered_by: dict | None = None,
        suppressed_by: uuid.UUID | None = None,
    ) -> Question:
        question = Question(
            id=uuid.uuid4(),
            case_id=case_id,
            text=text,
            status=status,
            priority=priority,
            triggered_by=triggered_by,
            suppressed_by=suppressed_by,
            created_at=datetime.now(UTC),
        )
        self._session.add(question)
        self._session.flush()
        return question

    # -- Findings -----------------------------------------------------------

    def create_finding(
        self,
        question_id: uuid.UUID,
        *,
        claim: str,
        evidence_class: str,
        evidence_ref: dict,
        assumptions: list,
        evidence_level: str | None = None,
        status: str = "active",
    ) -> Finding:
        finding = Finding(
            id=uuid.uuid4(),
            question_id=question_id,
            claim=claim,
            evidence_class=evidence_class,
            evidence_ref=evidence_ref,
            evidence_level=evidence_level,
            assumptions=assumptions,
            status=status,
            created_at=datetime.now(UTC),
        )
        self._session.add(finding)
        self._session.flush()
        return finding

    def mark_superseded(
        self, finding_id: uuid.UUID, *, superseded_by: uuid.UUID, note: str
    ) -> Finding:
        """Marks a finding superseded. Never deletes -- the historical record
        is the point (IMPLEMENTATION_PLAN.md SS4.2).
        """
        finding = self._session.get(Finding, finding_id)
        if finding is None:
            raise ValueError(f"No finding with id {finding_id}")
        finding.status = "superseded"
        finding.superseded_by = superseded_by
        finding.superseded_note = note
        self._session.flush()
        return finding

    # -- Decisions ----------------------------------------------------------

    def create_decision(
        self,
        finding_id: uuid.UUID,
        *,
        action: str,
        reason: str,
        decided_by: str,
    ) -> Decision:
        decision = Decision(
            id=uuid.uuid4(),
            finding_id=finding_id,
            action=action,
            reason=reason,
            decided_by=decided_by,
            decided_at=datetime.now(UTC),
        )
        self._session.add(decision)
        self._session.flush()
        return decision
