"""In-memory store stand-in for query-layer tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FakeCase:
    id: uuid.UUID
    label: str
    cancer_type: str
    age_years: int | None = None
    primary_site: str | None = None
    histology: str | None = None
    stage: str | None = None
    doid: str | None = None


@dataclass
class FakeEvent:
    id: uuid.UUID
    event_type: str
    payload: dict
    occurred_at: datetime
    recorded_at: datetime
    source_document: str | None = None


@dataclass
class FakeQuestion:
    id: uuid.UUID
    text: str
    status: str
    priority: int
    created_at: datetime
    triggered_by: dict | None = None


@dataclass
class FakeFindingRow:
    id: uuid.UUID
    question_id: uuid.UUID
    claim: str
    evidence_class: str
    evidence_ref: dict
    assumptions: list
    evidence_level: str | None = None
    status: str = "active"


@dataclass
class FakeStore:
    case: FakeCase | None = None
    events: list[FakeEvent] = field(default_factory=list)
    questions: list[FakeQuestion] = field(default_factory=list)
    findings: tuple = ()
    finding_rows: list[FakeFindingRow] = field(default_factory=list)

    def get_case(self, case_id):
        if self.case is not None and self.case.id == case_id:
            return self.case
        return None

    def list_events(self, case_id):
        del case_id
        return sorted(self.events, key=lambda e: e.occurred_at)

    def list_questions(self, case_id):
        del case_id
        return sorted(self.questions, key=lambda q: q.created_at)

    def list_active_findings(self, case_id):
        del case_id
        return self.findings

    def derive_state(self, case_id):
        from secondlook.query.fold import fold_store_events

        return fold_store_events(case_id, self.list_events(case_id))

    def create_question(
        self,
        case_id,
        *,
        text,
        status="open",
        priority,
        triggered_by=None,
        suppressed_by=None,
    ):
        del case_id, suppressed_by
        question = FakeQuestion(
            id=uuid.uuid4(),
            text=text,
            status=status,
            priority=priority,
            created_at=datetime.now(),
            triggered_by=triggered_by,
        )
        self.questions.append(question)
        return question

    def create_finding(
        self,
        question_id,
        *,
        claim,
        evidence_class,
        evidence_ref,
        assumptions,
        evidence_level=None,
        status="active",
    ):
        from secondlook.case.store import serialize_assumptions

        row = FakeFindingRow(
            id=uuid.uuid4(),
            question_id=question_id,
            claim=claim,
            evidence_class=evidence_class,
            evidence_ref=evidence_ref,
            assumptions=serialize_assumptions(assumptions),
            evidence_level=evidence_level,
            status=status,
        )
        self.finding_rows.append(row)
        return row

    def get_finding(self, finding_id):
        for row in self.finding_rows:
            if row.id == finding_id:
                return row
        return None


class FakeGraph:
    def __init__(self, responses: list[list[tuple]] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[tuple[str, dict]] = []

    def query(self, cypher: str, params: dict | None = None):
        self.calls.append((cypher, params or {}))
        rows = self._responses.pop(0) if self._responses else []

        class _Result:
            def __init__(self, result_set):
                self.result_set = result_set

        return _Result(rows)
