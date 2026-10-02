"""Add locacao meta fields to proposals."""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20251210_locacao_meta"
down_revision = "20251202_1800"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("proposals")}
    with op.batch_alter_table("proposals") as batch:
        if "locacao_valor_mensal" not in cols:
            batch.add_column(sa.Column("locacao_valor_mensal", sa.Float(), nullable=True))
        if "locacao_vigencia" not in cols:
            batch.add_column(sa.Column("locacao_vigencia", sa.String(length=128), nullable=True))
        if "locacao_qtd_pessoas" not in cols:
            batch.add_column(sa.Column("locacao_qtd_pessoas", sa.Integer(), nullable=True))
        if "locacao_qtd_cnpjs" not in cols:
            batch.add_column(sa.Column("locacao_qtd_cnpjs", sa.Integer(), nullable=True))
        if "locacao_qtd_equipamentos" not in cols:
            batch.add_column(sa.Column("locacao_qtd_equipamentos", sa.Integer(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("proposals")}
    with op.batch_alter_table("proposals") as batch:
        if "locacao_qtd_equipamentos" in cols:
            batch.drop_column("locacao_qtd_equipamentos")
        if "locacao_qtd_cnpjs" in cols:
            batch.drop_column("locacao_qtd_cnpjs")
        if "locacao_qtd_pessoas" in cols:
            batch.drop_column("locacao_qtd_pessoas")
        if "locacao_vigencia" in cols:
            batch.drop_column("locacao_vigencia")
        if "locacao_valor_mensal" in cols:
            batch.drop_column("locacao_valor_mensal")
