"""Add system_options catalog table."""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260210_system_options"
down_revision = "20260203_atestados_tables"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "system_options" not in tables:
        op.create_table(
            "system_options",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("label", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("image_path", sa.String(length=256), nullable=True),
            sa.Column("default_quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("unit_price", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("key", name="uq_system_options_key"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "system_options" in tables:
        op.drop_table("system_options")
