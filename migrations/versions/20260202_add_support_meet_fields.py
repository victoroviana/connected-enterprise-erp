"""Add meet fields to atendimento_suporte.

Revision ID: 20260202_add_support_meet_fields
Revises: 20251218_assist_indexes
Create Date: 2026-02-02 09:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260202_add_support_meet_fields"
down_revision = "20251218_assist_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("atendimento_suporte") as batch_op:
        batch_op.add_column(sa.Column("meet_link", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("meet_event_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("meet_session_key", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("meet_start", sa.DateTime(), nullable=True))
        batch_op.create_index(
            "ix_atendimento_suporte_meet_session_key",
            ["meet_session_key"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("atendimento_suporte") as batch_op:
        batch_op.drop_index("ix_atendimento_suporte_meet_session_key")
        batch_op.drop_column("meet_start")
        batch_op.drop_column("meet_session_key")
        batch_op.drop_column("meet_event_id")
        batch_op.drop_column("meet_link")
