"""Add completion timestamps to Kanban tasks

Revision ID: 20251102_kanban_archive
Revises: 20251101_issuer_branch
Create Date: 2025-11-02 09:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20251102_kanban_archive"
down_revision = "20251101_issuer_branch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("completed_at", sa.DateTime(), nullable=True))
    op.add_column("tasks", sa.Column("archived_at", sa.DateTime(), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE tasks SET completed_at = COALESCE(updated_at, created_at) "
        "WHERE status = 'done' AND completed_at IS NULL"
    ))


def downgrade() -> None:
    op.drop_column("tasks", "archived_at")
    op.drop_column("tasks", "completed_at")
