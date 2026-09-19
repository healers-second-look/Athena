"""Append-only event log for the diff-first study (issue #136).

Every measurable thing a reviewer does -- opening a finding, opening a source,
flagging, rating confidence, submitting a decision, chatting -- is one row
here. The protocol's outcomes (docs/research/diff-first-study-protocol.md
section 6) are computed later, offline, from this log plus the case set's
ground truth. Nothing is scored at write time and nothing about the case
ground truth is stored here.

`StudyEventStore` has no update or delete method, on purpose, the same way
`case/store.py` has none for `case_events`; `tests/study/test_events.py`
asserts the absence so a future change that adds one fails CI. Declared in its
own file rather than `case/models.py`, following `case/alerts.py`.

No PHI. Participant ids are pseudonymous and deliberately restricted to a
conservative character set (no `@`, no spaces) so an email address or a full
name cannot be pasted in by accident -- see POLICY.md section 5.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import JSON, TIMESTAMP, Index, Text, Uuid, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from secondlook.case.models import Base

ARMS: tuple[str, ...] = ("diff_first", "dashboard", "chat")

# A closed vocabulary: an unknown type is rejected rather than stored, so a
# typo in the client cannot silently create an outcome nobody analyses.
STUDY_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "case_opened",  # reviewer began a case in an arm
        "finding_opened",  # expanded/selected a finding
        "citation_opened",  # opened a finding's source
        "flag_set",  # marked a finding as invalid/unsupported
        "flag_cleared",
        "confidence_set",  # per-finding "this is valid" confidence, 0-100
        "chat_message_sent",  # arm C
        "chat_response_shown",  # arm C
        "page_hidden",  # tab left / window blurred
        "page_visible",
        "idle_period",  # > 60 s without input; payload carries the duration
        "decision_submitted",  # final management decision
        "tlx_submitted",  # raw NASA-TLX subscales
        "recall_submitted",  # "what changed?" recall probe
        "case_submitted",  # reviewer finished the case
    }
)

MAX_BATCH = 100
MAX_PAYLOAD_BYTES = 8192
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class InvalidStudyEvent(ValueError):
    """An event failed validation; nothing from its batch was written."""


class StudyEvent(Base):
    __tablename__ = "study_events"
    __table_args__ = (
        Index("ix_study_events_participant_case_ts", "participant_id", "case_id", "client_ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    case_id: Mapped[str] = mapped_column(Text, nullable=False)
    arm: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    client_ts: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    server_ts: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


@dataclass(frozen=True)
class NewStudyEvent:
    participant_id: str
    session_id: str
    case_id: str
    arm: str
    event_type: str
    client_ts: datetime
    payload: dict = field(default_factory=dict)


def validate_new_event(event: NewStudyEvent) -> None:
    for name in ("participant_id", "session_id", "case_id"):
        if not _ID.match(getattr(event, name)):
            raise InvalidStudyEvent(
                f"{name} must be 1-64 characters of letters, digits, '_' or '-' "
                "(pseudonymous ids only; no emails or names)"
            )
    if event.arm not in ARMS:
        raise InvalidStudyEvent(f"arm must be one of {list(ARMS)}, got {event.arm!r}")
    if event.event_type not in STUDY_EVENT_TYPES:
        raise InvalidStudyEvent(f"unknown event_type {event.event_type!r}")
    if event.client_ts.tzinfo is None:
        raise InvalidStudyEvent("client_ts must be timezone-aware")
    if not isinstance(event.payload, dict):
        raise InvalidStudyEvent("payload must be an object")
    # Length of the repr is a cheap, dependency-free size cap on an untrusted body.
    if len(repr(event.payload)) > MAX_PAYLOAD_BYTES:
        raise InvalidStudyEvent(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes")


class StudyEventStore:
    """Append and read study events. Deliberately no update/delete."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append_many(self, events: list[NewStudyEvent]) -> int:
        """Validate every event, then write all of them or none of them."""
        if not events:
            raise InvalidStudyEvent("no events supplied")
        if len(events) > MAX_BATCH:
            raise InvalidStudyEvent(f"at most {MAX_BATCH} events per batch")
        for event in events:
            validate_new_event(event)
        now = datetime.now(UTC)
        self._session.add_all(
            StudyEvent(
                participant_id=e.participant_id,
                session_id=e.session_id,
                case_id=e.case_id,
                arm=e.arm,
                event_type=e.event_type,
                payload=e.payload,
                client_ts=e.client_ts,
                server_ts=now,
            )
            for e in events
        )
        self._session.flush()
        return len(events)

    def list_events(
        self,
        *,
        participant_id: str | None = None,
        case_id: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[StudyEvent]:
        stmt = select(StudyEvent).order_by(StudyEvent.client_ts, StudyEvent.server_ts)
        if participant_id is not None:
            stmt = stmt.where(StudyEvent.participant_id == participant_id)
        if case_id is not None:
            stmt = stmt.where(StudyEvent.case_id == case_id)
        return list(self._session.scalars(stmt.limit(limit).offset(offset)))
