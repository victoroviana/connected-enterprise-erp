"""Create SollusFlow tables and drop legacy Central de Conhecimento tables

Revision ID: 20260901_sollusflow
Revises: 3c623542e694_add_sistema_preco_fixo_to_proposals
Create Date: 2026-09-01 17:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260901_sollusflow"
down_revision = "3c623542e694"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop legacy Central de Conhecimento tables (order matters for FKs)
    for tbl in [
        "subtask_flow_edges", "subtask_flow_nodes", "subtasks",
        "task_comment_attachments", "task_comments", "task_logs",
        "tasks", "central_conhecimento_columns",
    ]:
        try:
            op.drop_table(tbl)
        except Exception:
            pass

    # sf_pedidos — card principal (pedido/cliente)
    op.create_table(
        "sf_pedidos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("numero_pedido", sa.String(50), nullable=True),
        sa.Column("cliente_nome", sa.String(200), nullable=False),
        sa.Column("cliente_cnpj", sa.String(20), nullable=True),
        sa.Column("tipo", sa.String(20), nullable=False, server_default="venda"),
        sa.Column("valor", sa.Numeric(14, 2), nullable=True),
        sa.Column("consultor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("responsavel_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fase_atual", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prioridade", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("data_entrada", sa.Date(), nullable=True),
        sa.Column("data_prevista", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ativo"),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # sf_fase_historico — log de mudanca de fase
    op.create_table(
        "sf_fase_historico",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pedido_id", sa.Integer(), sa.ForeignKey("sf_pedidos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fase_de", sa.Integer(), nullable=True),
        sa.Column("fase_para", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("transferido_para_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("observacao", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # sf_checklist — itens de checklist por fase
    op.create_table(
        "sf_checklist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pedido_id", sa.Integer(), sa.ForeignKey("sf_pedidos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fase", sa.Integer(), nullable=False),
        sa.Column("titulo", sa.String(300), nullable=False),
        sa.Column("concluido", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("concluido_por_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("concluido_at", sa.DateTime(), nullable=True),
        sa.Column("posicao", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # sf_observacoes — comentarios compartilhados
    op.create_table(
        "sf_observacoes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pedido_id", sa.Integer(), sa.ForeignKey("sf_pedidos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("autor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("corpo", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("sf_observacoes")
    op.drop_table("sf_checklist")
    op.drop_table("sf_fase_historico")
    op.drop_table("sf_pedidos")

