"""add issuer company code and user phone

Revision ID: 20250215_issuer
Revises: 0001a2b3c4d5_platform_initial_schema
Create Date: 2025-02-15 12:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250215_issuer'
down_revision = '0001a2b3c4d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('phone', sa.String(length=32), nullable=True))
    op.add_column('proposals', sa.Column('client_document_type', sa.String(length=16), nullable=True))
    op.add_column('proposals', sa.Column('issuer_company_code', sa.String(length=32), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text("UPDATE proposals SET client_document_type = 'cnpj' WHERE client_document_type IS NULL"))


def downgrade() -> None:
    op.drop_column('proposals', 'issuer_company_code')
    op.drop_column('proposals', 'client_document_type')
    op.drop_column('users', 'phone')
