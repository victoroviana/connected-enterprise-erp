"""Create suporte and chamados tables

Revision ID: 20251201_support_tables
Revises: 20251122_department_permissions
Create Date: 2025-11-28 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251201_support_tables"
down_revision = "20251122_department_permissions"
branch_labels = None
depends_on = None


CHAMADO_TABLES = [
    "chamados_rj",
    "chamados_sp",
    "chamados_pr",
    "chamados_es",
    "chamados_cp",
    "chamados_coldrio",
    "chamados_ae",
]


def _chamado_columns():
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data", sa.Date(), nullable=True),
        sa.Column("cliente", sa.String(length=255), nullable=False),
        sa.Column("bairro", sa.String(length=255), nullable=True),
        sa.Column("ordem_servico", sa.String(length=255), nullable=False),
        sa.Column("numero_manutencao", sa.Integer(), nullable=True),
        sa.Column("tecnico", sa.String(length=255), nullable=True),
        sa.Column("retorno", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("tipo_atendimento", sa.String(length=64), nullable=True),
        sa.Column("hora_entrada", sa.Time(), nullable=True),
        sa.Column("hora_saida", sa.Time(), nullable=True),
        sa.Column("quem_atendeu", sa.String(length=255), nullable=True),
        sa.Column("data_os_criada", sa.DateTime(), nullable=True),
        sa.Column("data_os_tecnico", sa.DateTime(), nullable=True),
        sa.Column("contrato", sa.String(length=32), nullable=True),
        sa.Column("cnpj", sa.String(length=32), nullable=True),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("criado_por", sa.String(length=255), nullable=True),
        sa.Column("email_responsavel", sa.String(length=255), nullable=True),
        sa.Column("data_modificacao", sa.DateTime(), nullable=True),
        sa.Column("novo_cliente", sa.String(length=32), nullable=True),
        sa.Column("numero_proposta", sa.Integer(), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "empresa" not in existing:
        op.create_table(
            "empresa",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("cliente", sa.String(length=255), nullable=False),
            sa.Column("cnpj", sa.String(length=32), nullable=True),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("observacoes_alerta", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("cnpj", name="uq_empresa_cnpj"),
        )

    if "atendimento_suporte" not in existing:
        op.create_table(
            "atendimento_suporte",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("cliente", sa.String(length=255), nullable=False),
            sa.Column("data_entrada", sa.DateTime(), nullable=False),
            sa.Column("data_atendimento", sa.DateTime(), nullable=True),
            sa.Column("tipo_atendimento", sa.String(length=120), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'Entrada'")),
            sa.Column("descricao", sa.Text(), nullable=True),
            sa.Column("resumo_atendimento", sa.Text(), nullable=True),
            sa.Column("os_entrada", sa.String(length=64), nullable=True),
            sa.Column("arq_entrada", sa.String(length=255), nullable=True),
            sa.Column("os_saida", sa.String(length=64), nullable=True),
            sa.Column("arq_saida", sa.String(length=255), nullable=True),
            sa.Column("usuario_designado", sa.Integer(), nullable=True),
            sa.Column("criado_por", sa.String(length=120), nullable=True),
            sa.Column("CNPJ", sa.String(length=32), nullable=True),
            sa.Column("SISTEMA", sa.String(length=120), nullable=True),
            sa.Column("QUANTIDADE_DE_PESSOAS", sa.String(length=32), nullable=True),
            sa.Column("TEXTO_MOBILE", sa.Text(), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("observacoes_alerta", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["usuario_designado"], ["users.id"], name="fk_support_user"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_atendimento_suporte_os_entrada",
            "atendimento_suporte",
            ["os_entrada"],
            unique=False,
        )

    if "atendimento_suporte_logs" not in existing:
        op.create_table(
            "atendimento_suporte_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("atendimento_suporte_id", sa.Integer(), nullable=False),
            sa.Column("campo", sa.String(length=120), nullable=False),
            sa.Column("valor_antigo", sa.Text(), nullable=True),
            sa.Column("valor_novo", sa.Text(), nullable=True),
            sa.Column("modificado_por", sa.String(length=120), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(
                ["atendimento_suporte_id"],
                ["atendimento_suporte.id"],
                name="fk_support_logs_entry",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "ultimo_atendimento" not in existing:
        op.create_table(
            "ultimo_atendimento",
            sa.Column("tecnico_id", sa.Integer(), nullable=False),
            sa.Column("ultimo_atendimento", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tecnico_id"], ["users.id"], name="fk_support_last_user", ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("tecnico_id"),
        )

    for table_name in CHAMADO_TABLES:
        if table_name not in existing:
            op.create_table(table_name, *_chamado_columns())


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    for table_name in reversed(CHAMADO_TABLES):
        if table_name in existing:
            op.drop_table(table_name)
    if "ultimo_atendimento" in existing:
        op.drop_table("ultimo_atendimento")
    if "atendimento_suporte_logs" in existing:
        op.drop_table("atendimento_suporte_logs")
    if "atendimento_suporte" in existing:
        op.drop_index("ix_atendimento_suporte_os_entrada", table_name="atendimento_suporte")
        op.drop_table("atendimento_suporte")
    if "empresa" in existing:
        op.drop_table("empresa")

