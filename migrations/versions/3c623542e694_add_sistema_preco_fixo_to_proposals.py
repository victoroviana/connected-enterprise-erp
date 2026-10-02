"""Add sistema_preco_fixo to proposals

Revision ID: 3c623542e694
Revises: 20260210_system_option_states
Create Date: 2026-03-26 16:44:28.699530

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3c623542e694'
down_revision = '20260210_system_option_states'
branch_labels = None
depends_on = None

def upgrade():
    # Only add the column to proposals, ignore everything else
    with op.batch_alter_table('proposals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sistema_preco_fixo', sa.Boolean(), nullable=False, server_default=sa.text('0')))

def downgrade():
    with op.batch_alter_table('proposals', schema=None) as batch_op:
        batch_op.drop_column('sistema_preco_fixo')
