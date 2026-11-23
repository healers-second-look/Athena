"""Study enrollment: invites, participants, consent records.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-23

Hand-written to match study/enrollment.py.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "study_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code_hash", sa.Text, nullable=False, unique=True),
        sa.Column("reviewer_index", sa.Integer, nullable=False, unique=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("participant_id", sa.Text, nullable=True),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_study_invites_code_hash", "study_invites", ["code_hash"], unique=True)

    op.create_table(
        "study_participants",
        sa.Column("participant_id", sa.Text, primary_key=True),
        sa.Column("reviewer_index", sa.Integer, nullable=False, unique=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("phone", sa.Text, nullable=True),
        sa.Column("registration_number", sa.Text, nullable=False),
        sa.Column("specialty", sa.Text, nullable=False),
        sa.Column("years_in_oncology", sa.Integer, nullable=False),
        sa.Column("institution", sa.Text, nullable=False),
        sa.Column("has_uptodate", sa.Boolean, nullable=False),
        sa.Column("has_nccn", sa.Boolean, nullable=False),
        sa.Column("ai_familiarity", sa.Integer, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_table(
        "study_consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("invite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("participant_id", sa.Text, nullable=True),
        sa.Column("consent_version", sa.Text, nullable=False),
        sa.Column("text_sha256", sa.Text, nullable=False),
        sa.Column("signed_name", sa.Text, nullable=False),
        sa.Column("answers", postgresql.JSONB, nullable=False),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ip", sa.Text, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("study_consents")
    op.drop_table("study_participants")
    op.drop_index("ix_study_invites_code_hash", table_name="study_invites")
    op.drop_table("study_invites")