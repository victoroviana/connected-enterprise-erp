"""Add atestados tables.

Revision ID: 20260203_atestados_tables
Revises: 20260202_add_support_meet_fields
Create Date: 2026-02-03 09:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260203_atestados_tables"
down_revision = "20260202_add_support_meet_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "arquivo" not in existing:
        op.create_table(
            "arquivo",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nome", sa.String(length=255), nullable=False),
            sa.Column("conteudo", sa.LargeBinary(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "email" not in existing:
        op.create_table(
            "email",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("endereco", sa.String(length=255), nullable=False),
            sa.Column("arquivo_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["arquivo_id"],
                ["arquivo.id"],
                name="fk_arquivo",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "log_envio" not in existing:
        op.create_table(
            "log_envio",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("arquivo_id", sa.Integer(), nullable=False),
            sa.Column("data_envio", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("mensagem", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(
                ["arquivo_id"],
                ["arquivo.id"],
                name="log_envio_ibfk_1",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "task" not in existing:
        op.create_table(
            "task",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("progress", sa.Integer(), nullable=True),
            sa.Column("total", sa.Integer(), nullable=True),
            sa.Column("current", sa.Integer(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("date_created", sa.DateTime(), nullable=True),
            sa.Column("date_modified", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "log_envio" in existing:
        op.drop_table("log_envio")
    if "email" in existing:
        op.drop_table("email")
    if "task" in existing:
        op.drop_table("task")
    if "arquivo" in existing:
        op.drop_table("arquivo")
