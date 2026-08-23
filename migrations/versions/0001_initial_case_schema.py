"""Initial Case Memory Store schema

Revision ID: 0001
Revises:
Create Date: 2026-08-23

Hand-written to match IMPLEMENTATION_PLAN.md SS2.2 exactly, and
case/models.py, which is the source of truth this migration mirrors.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("age_years", sa.Integer, nullable=True),
        sa.Column("cancer_type", sa.Text, nullable=False),
        sa.Column("primary_site", sa.Text, nullable=True),
        sa.Column("histology", sa.Text, nullable=True),
        sa.Column("doid", sa.String(64), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )

    op.create_table(
        "case_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cases.id"), nullable=False
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("source_document", sa.Text, nullable=True),
        sa.Column("recorded_by", sa.Text, nullable=True),
        sa.CheckConstraint("true", name="no_update"),
    )
    op.create_index("ix_case_events_case_id_occurred_at", "case_events", ["case_id", "occurred_at"])

    op.create_table(
        "questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cases.id"), nullable=False
        ),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("triggered_by", postgresql.JSONB, nullable=True),
        sa.Column(
            "suppressed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )

    op.create_table(
        "findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id"),
            nullable=False,
        ),
        sa.Column("claim", sa.Text, nullable=False),
        sa.Column("evidence_class", sa.Text, nullable=False),
        sa.Column("evidence_ref", postgresql.JSONB, nullable=False),
        sa.Column("evidence_level", sa.Text, nullable=True),
        sa.Column("assumptions", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "superseded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_events.id"),
            nullable=True,
        ),
        sa.Column("superseded_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )

    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("findings.id"),
            nullable=False,
        ),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("decided_by", sa.Text, nullable=False),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("decisions")
    op.drop_table("findings")
    op.drop_table("questions")
    op.drop_index("ix_case_events_case_id_occurred_at", table_name="case_events")
    op.drop_table("case_events")
    op.drop_table("cases")
