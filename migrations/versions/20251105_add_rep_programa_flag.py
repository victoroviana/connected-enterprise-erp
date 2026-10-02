"""Add REP-P flag to proposals

Revision ID: 20251105_rep_programa
Revises: 20251102_kanban_archive
Create Date: 2025-11-05 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20251105_rep_programa"
down_revision = "20251102_kanban_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "proposals",
        sa.Column(
            "rep_categoria_programa",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )

    # Drop the server default to keep future inserts relying on application defaults
    op.alter_column(
        "proposals",
        "rep_categoria_programa",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("proposals", "rep_categoria_programa")
