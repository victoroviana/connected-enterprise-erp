"""Add system_option_states table."""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260210_system_option_states"
down_revision = "20260210_system_options"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "system_option_states" not in tables:
        op.create_table(
            "system_option_states",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("key", name="uq_system_option_states_key"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "system_option_states" in tables:
        op.drop_table("system_option_states")
