"""Add permissions column to departments

Revision ID: 20251122_department_permissions
Revises: 20251121_user_departments
Create Date: 2025-11-19 17:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251122_department_permissions"
down_revision = "20251121_user_departments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("departments")}
    if "permissions" not in cols:
        op.add_column(
            "departments",
            sa.Column("permissions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )
        op.execute("UPDATE departments SET permissions = '{}' WHERE permissions IS NULL")
        op.alter_column("departments", "permissions", server_default=None)


def downgrade() -> None:
    op.drop_column("departments", "permissions")
