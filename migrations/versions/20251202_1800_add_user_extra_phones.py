"""add phone extra column"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251202_1800'
down_revision = '20251201_support_tables'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("users")}
    if 'phone_extra' not in cols:
        op.add_column('users', sa.Column('phone_extra', sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("users")}
    if 'phone_extra' in cols:
        op.drop_column('users', 'phone_extra')
