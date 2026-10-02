"""Add admin tools tables

Revision ID: 20251120_admin_tools
Revises: 20251105_rep_programa
Create Date: 2025-11-19 14:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20251120_admin_tools"
down_revision = "20251105_rep_programa"
branch_labels = None
depends_on = None


mysql_now = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "aniversariantes" not in existing:
        op.create_table(
            "aniversariantes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nome", sa.String(length=255), nullable=False),
            sa.Column("data_nascimento", sa.Date(), nullable=False),
        )

    if "ferias" not in existing:
        op.create_table(
            "ferias",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("usuario_id", sa.String(length=255), nullable=False),
            sa.Column("data_inicial", sa.Date(), nullable=False),
            sa.Column("data_final", sa.Date(), nullable=False),
            sa.Column("referente_ano", sa.Integer(), nullable=False),
            sa.Column("unidade", sa.String(length=64), nullable=False),
        )

    if "agenda" not in existing:
        op.create_table(
            "agenda",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("unidade", sa.String(length=64), nullable=False),
            sa.Column("data_atendimento", sa.Date(), nullable=False),
            sa.Column("periodo", sa.String(length=20), nullable=False),
            sa.Column("obs", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=mysql_now),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=mysql_now),
        )


def downgrade() -> None:
    op.drop_table("agenda")
    op.drop_table("ferias")
    op.drop_table("aniversariantes")
