"""SQLAlchemy models for the Case Memory Store.

Schema exactly per `IMPLEMENTATION_PLAN.md` SS2.2. Five tables:
`cases`, `case_events`, `questions`, `findings`, `decisions`.

Two invariants enforced here, not just documented:

1. **No PHI.** `Case` carries no name, date of birth, or MRN -- see
   `POLICY.md` SS5.4. `NO_PHI_COLUMN_PATTERN` below is what
   `tests/case/test_models.py` checks every column name against; a PR that
   adds a disallowed column fails CI, not just code review.
2. **`case_events` is append-only.** The Postgres `CHECK (true)` constraint
   on `CaseEvent` is a documentation placeholder, not real enforcement --
   the actual enforcement is `store.py`'s repository layer, which exposes
   no update/delete path for events at all.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# No-PHI enforcement
#
# Matches a disallowed-PHI column name pattern -- see POLICY.md SS5.4 and
# SS5.5. This is intentionally conservative (over-matches rather than
# under-matches): a false positive here means a legitimate column needs a
# more specific name, which is a cheap cost next to the alternative.
# ---------------------------------------------------------------------------
NO_PHI_COLUMN_PATTERN = re.compile(
    r"(^|_)(name|first_name|last_name|full_name|dob|date_of_birth|"
    r"mrn|ssn|social_security|patient_id|address|phone|email|"
    r"insurance|nhs_number|passport)(_|$)",
    re.IGNORECASE,
)

# The five-type event taxonomy -- IMPLEMENTATION_PLAN.md SS2.3. Resist
# adding a sixth: every additional type multiplies the diff engine's test
# surface (see that module's own docstring once it exists).
EVENT_TYPES: frozenset[str] = frozenset(
    {
        "ALTERATION_OBSERVED",
        "BIOMARKER_MEASURED",
        "TREATMENT_LINE",
        "DISEASE_ASSESSMENT",
        "CLINICAL_QUESTION",
    }
)

QUESTION_STATUSES: frozenset[str] = frozenset({"open", "answered", "suppressed", "rejected"})
EVIDENCE_CLASSES: frozenset[str] = frozenset({"documented", "computed", "regulatory", "contextual"})
FINDING_STATUSES: frozenset[str] = frozenset({"active", "superseded"})
DECISION_ACTIONS: frozenset[str] = frozenset({"investigating", "deferred", "rejected"})


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Case(Base):
    """A case. No PHI: no name, no DOB, no MRN -- see POLICY.md SS5.4."""

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = _uuid_pk()
    label: Mapped[str] = mapped_column(Text, nullable=False)
    age_years: Mapped[int | None] = mapped_column(nullable=True)  # P0, per patient-schema-mvp.md
    cancer_type: Mapped[str] = mapped_column(Text, nullable=False)  # P0
    primary_site: Mapped[str | None] = mapped_column(Text, nullable=True)
    histology: Mapped[str | None] = mapped_column(Text, nullable=True)
    doid: Mapped[str | None] = mapped_column(String(64), nullable=True)  # joins to FalkorDB Disease
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    events: Mapped[list[CaseEvent]] = relationship(
        back_populates="case", order_by="CaseEvent.occurred_at"
    )
    questions: Mapped[list[Question]] = relationship(back_populates="case")


class CaseEvent(Base):
    """Append-only. The source of truth. Never updated or deleted.

    `store.py` is the only code path allowed to write these, and it exposes
    no update/delete method -- `no_update` below documents the intent at
    the schema level, matching IMPLEMENTATION_PLAN.md SS2.2 exactly (the
    DB-level CHECK is a placeholder there too; this is a known, accepted
    gap until a trigger-based enforcement is worth the operational cost).
    """

    __tablename__ = "case_events"
    __table_args__ = (
        CheckConstraint("true", name="no_update"),
        Index("ix_case_events_case_id_occurred_at", "case_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )  # clinical date -- when it happened
    recorded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )  # system date -- when we learned it
    source_document: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    case: Mapped[Case] = relationship(back_populates="events")


class Question(Base):
    """A research question. Deduped against prior questions (case/memory.py, once it exists)."""

    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # QUESTION_STATUSES
    priority: Mapped[int] = mapped_column(nullable=False)
    triggered_by: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # the Change that generated it
    suppressed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    case: Mapped[Case] = relationship(back_populates="questions")
    findings: Mapped[list[Finding]] = relationship(back_populates="question")


class Finding(Base):
    """A cited finding answering a question. Joins to the FalkorDB graph via evidence_ref."""

    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_class: Mapped[str] = mapped_column(Text, nullable=False)  # EVIDENCE_CLASSES
    evidence_ref: Mapped[dict] = mapped_column(
        JSONB, nullable=False
    )  # {source, civic_id|pmid|nct_id, url}
    evidence_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    assumptions: Mapped[list] = mapped_column(
        JSONB, nullable=False
    )  # list[Assumption] -- see case/diff.py
    status: Mapped[str] = mapped_column(Text, nullable=False)  # FINDING_STATUSES
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("case_events.id"), nullable=True
    )
    superseded_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    question: Mapped[Question] = relationship(back_populates="findings")
    decisions: Mapped[list[Decision]] = relationship(back_populates="finding")


class Decision(Base):
    """The clinician's review. This is what makes it a loop, not a one-shot query."""

    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("findings.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # DECISION_ACTIONS
    reason: Mapped[str] = mapped_column(Text, nullable=False)  # required, even for "investigating"
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    finding: Mapped[Finding] = relationship(back_populates="decisions")


ALL_MODELS: tuple[type[Base], ...] = (Case, CaseEvent, Question, Finding, Decision)
