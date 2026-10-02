"""Add departments and user fields

Revision ID: 20251121_user_departments
Revises: 20251120_admin_tools
Create Date: 2025-11-19 15:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251121_user_departments"
down_revision = "20251120_admin_tools"
branch_labels = None
depends_on = None


MYSQL_TIMESTAMP = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "departments" not in existing:
        op.create_table(
            "departments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=MYSQL_TIMESTAMP),
        )

    user_cols = {col["name"] for col in inspector.get_columns("users")}
    if "department_id" not in user_cols:
        op.add_column("users", sa.Column("department_id", sa.Integer(), nullable=True))
    if "unit_code" not in user_cols:
        op.add_column("users", sa.Column("unit_code", sa.String(length=32), nullable=True))
    if "ramal" not in user_cols:
        op.add_column("users", sa.Column("ramal", sa.String(length=32), nullable=True))

    fk_names = {fk["name"] for fk in inspector.get_foreign_keys("users") if fk.get("referred_table") == "departments"}
    if "fk_users_department" not in fk_names:
        op.create_foreign_key(
            "fk_users_department",
            "users",
            "departments",
            ["department_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute("UPDATE users SET unit_code = 'sollus' WHERE unit_code IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    fk_names = [fk["name"] for fk in inspector.get_foreign_keys("users") if fk.get("referred_table") == "departments"]
    for fk_name in fk_names:
        op.drop_constraint(fk_name, "users", type_="foreignkey")

    user_cols = {col["name"] for col in inspector.get_columns("users")}
    if "ramal" in user_cols:
        op.drop_column("users", "ramal")
    if "unit_code" in user_cols:
        op.drop_column("users", "unit_code")
    if "department_id" in user_cols:
        op.drop_column("users", "department_id")

    if "departments" in inspector.get_table_names():
        op.drop_table("departments")
