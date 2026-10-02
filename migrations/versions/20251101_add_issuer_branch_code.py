"""Add issuer branch code to proposals

Revision ID: 20251101_issuer_branch
Revises: 20250215_issuer
Create Date: 2025-11-01 10:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20251101_issuer_branch"
down_revision = "20250215_issuer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("proposals", sa.Column("issuer_branch_code", sa.String(length=64), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text("UPDATE proposals SET issuer_branch_code = 'rj_bangu' WHERE issuer_branch_code IS NULL"))


def downgrade() -> None:
    op.drop_column("proposals", "issuer_branch_code")
