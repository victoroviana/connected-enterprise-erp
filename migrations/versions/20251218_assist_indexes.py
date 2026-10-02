"""Add indexes to tarefas for assistencia performance."""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20251218_assist_indexes"
down_revision = "20251210_locacao_meta"
branch_labels = None
depends_on = None


def _index_exists(inspector, table, name):
    try:
        indexes = inspector.get_indexes(table)
    except Exception:
        return False
    return any(idx.get("name") == name for idx in indexes)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = [
        ("ix_tarefas_status", "status"),
        ("ix_tarefas_departamento", "departamento_responsavel"),
        ("ix_tarefas_data_fim", "data_fim"),
    ]
    for name, column in indexes:
        if not _index_exists(inspector, "tarefas", name):
            op.create_index(name, "tarefas", [column])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for name in ("ix_tarefas_status", "ix_tarefas_departamento", "ix_tarefas_data_fim"):
        if _index_exists(inspector, "tarefas", name):
            op.drop_index(name, table_name="tarefas")
