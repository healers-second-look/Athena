"""Study event log for the diff-first evaluation (issue #136).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-19

Hand-written to match study/events.py exactly. Append-only by convention:
the store exposes no update or delete.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "study_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("participant_id", sa.Text, nullable=False),
        sa.Column("session_id", sa.Text, nullable=False),
        sa.Column("case_id", sa.Text, nullable=False),
        sa.Column("arm", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("client_ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("server_ts", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_study_events_participant_case_ts",
        "study_events",
        ["participant_id", "case_id", "client_ts"],
    )


def downgrade() -> None:
    op.drop_index("ix_study_events_participant_case_ts", table_name="study_events")
    op.drop_table("study_events")
