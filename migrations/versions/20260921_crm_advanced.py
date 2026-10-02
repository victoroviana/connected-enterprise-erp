"""Add CRM Advanced models, automations, roulette, webhooks, and forecast columns

Revision ID: 20260921_crm_advanced
Revises: 20260901_sollusflow
Create Date: 2026-09-21 11:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = "20260921_crm_advanced"
down_revision = "20260901_sollusflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_tables = set(inspector.get_table_names())

    # 1. crm_motivos_perda
    if "crm_motivos_perda" not in existing_tables:
        op.create_table(
            "crm_motivos_perda",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nome", sa.String(120), nullable=False),
            sa.Column("categoria", sa.String(64), server_default="outros", nullable=False),
            sa.Column("ativo", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("ordem", sa.Integer(), server_default="0", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_crm_motivos_perda_categoria", "crm_motivos_perda", ["categoria"])
        op.create_index("ix_crm_motivos_perda_ativo", "crm_motivos_perda", ["ativo"])

    # 2. crm_regras_automacao
    if "crm_regras_automacao" not in existing_tables:
        op.create_table(
            "crm_regras_automacao",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("funil_id", sa.String(64), sa.ForeignKey("crm_funis.id", ondelete="CASCADE"), nullable=True),
            sa.Column("etapa_id", sa.String(64), sa.ForeignKey("crm_etapas.id", ondelete="CASCADE"), nullable=True),
            sa.Column("evento", sa.String(64), server_default="etapa_entrada", nullable=False),
            sa.Column("acao_tipo", sa.String(64), server_default="criar_tarefa", nullable=False),
            sa.Column("tarefa_titulo", sa.String(255), nullable=True),
            sa.Column("tarefa_tipo", sa.String(64), server_default="whatsapp", nullable=False),
            sa.Column("prazo_horas", sa.Integer(), server_default="24", nullable=False),
            sa.Column("ativo", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_crm_regras_automacao_funil_id", "crm_regras_automacao", ["funil_id"])
        op.create_index("ix_crm_regras_automacao_etapa_id", "crm_regras_automacao", ["etapa_id"])
        op.create_index("ix_crm_regras_automacao_evento", "crm_regras_automacao", ["evento"])
        op.create_index("ix_crm_regras_automacao_ativo", "crm_regras_automacao", ["ativo"])

    # 3. crm_roleta_consultores
    if "crm_roleta_consultores" not in existing_tables:
        op.create_table(
            "crm_roleta_consultores",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("consultor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("total_distribuido", sa.Integer(), server_default="0", nullable=False),
            sa.Column("ultimo_recebimento", sa.DateTime(), nullable=True),
            sa.Column("ativo", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("consultor_id", name="uq_crm_roleta_consultor_id"),
        )
        op.create_index("ix_crm_roleta_consultores_consultor_id", "crm_roleta_consultores", ["consultor_id"])
        op.create_index("ix_crm_roleta_consultores_ativo", "crm_roleta_consultores", ["ativo"])

    # 4. crm_webhooks
    if "crm_webhooks" not in existing_tables:
        op.create_table(
            "crm_webhooks",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nome", sa.String(120), nullable=False),
            sa.Column("tipo", sa.String(32), server_default="outbound", nullable=False),
            sa.Column("url", sa.String(500), nullable=True),
            sa.Column("eventos", sa.String(255), nullable=True),
            sa.Column("token_hash", sa.String(128), nullable=True),
            sa.Column("ativo", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("secret_key", sa.String(128), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_crm_webhooks_token_hash", "crm_webhooks", ["token_hash"])
        op.create_index("ix_crm_webhooks_ativo", "crm_webhooks", ["ativo"])

    # 5. crm_webhook_logs
    if "crm_webhook_logs" not in existing_tables:
        op.create_table(
            "crm_webhook_logs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("webhook_id", sa.Integer(), sa.ForeignKey("crm_webhooks.id", ondelete="CASCADE"), nullable=True),
            sa.Column("evento", sa.String(64), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("request_payload", sa.Text(), nullable=True),
            sa.Column("response_body", sa.Text(), nullable=True),
            sa.Column("sucesso", sa.Boolean(), server_default="0", nullable=False),
            sa.Column("tempo_ms", sa.Integer(), server_default="0", nullable=False),
            sa.Column("criado_em", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_crm_webhook_logs_webhook_id", "crm_webhook_logs", ["webhook_id"])
        op.create_index("ix_crm_webhook_logs_evento", "crm_webhook_logs", ["evento"])
        op.create_index("ix_crm_webhook_logs_sucesso", "crm_webhook_logs", ["sucesso"])
        op.create_index("ix_crm_webhook_logs_criado_em", "crm_webhook_logs", ["criado_em"])

    # 6. crm_templates_mensagens
    if "crm_templates_mensagens" not in existing_tables:
        op.create_table(
            "crm_templates_mensagens",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nome", sa.String(120), nullable=False),
            sa.Column("conteudo", sa.Text(), nullable=False),
            sa.Column("ativo", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("criado_por_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_crm_templates_mensagens_ativo", "crm_templates_mensagens", ["ativo"])

    # 7. Add columns to crm_negociacoes
    if "crm_negociacoes" in existing_tables:
        neg_cols = {col["name"] for col in inspector.get_columns("crm_negociacoes")}
        if "data_estimada_fechamento" not in neg_cols:
            op.add_column("crm_negociacoes", sa.Column("data_estimada_fechamento", sa.Date(), nullable=True))
            op.create_index("ix_crm_negociacoes_data_estimada_fechamento", "crm_negociacoes", ["data_estimada_fechamento"])
        if "motivo_perda_id" not in neg_cols:
            op.add_column("crm_negociacoes", sa.Column("motivo_perda_id", sa.Integer(), sa.ForeignKey("crm_motivos_perda.id", ondelete="SET NULL"), nullable=True))
            op.create_index("ix_crm_negociacoes_motivo_perda_id", "crm_negociacoes", ["motivo_perda_id"])
        if "motivo_perda_categoria" not in neg_cols:
            op.add_column("crm_negociacoes", sa.Column("motivo_perda_categoria", sa.String(64), nullable=True))
            op.create_index("ix_crm_negociacoes_motivo_perda_categoria", "crm_negociacoes", ["motivo_perda_categoria"])
        if "probabilidade" not in neg_cols:
            op.add_column("crm_negociacoes", sa.Column("probabilidade", sa.Float(), nullable=True))

    # 8. Add columns to crm_etapas
    if "crm_etapas" in existing_tables:
        etapa_cols = {col["name"] for col in inspector.get_columns("crm_etapas")}
        if "probabilidade" not in etapa_cols:
            op.add_column("crm_etapas", sa.Column("probabilidade", sa.Float(), server_default="10.0", nullable=False))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_tables = set(inspector.get_table_names())

    if "crm_etapas" in existing_tables:
        etapa_cols = {col["name"] for col in inspector.get_columns("crm_etapas")}
        if "probabilidade" in etapa_cols:
            op.drop_column("crm_etapas", "probabilidade")

    if "crm_negociacoes" in existing_tables:
        neg_cols = {col["name"] for col in inspector.get_columns("crm_negociacoes")}
        for col in ["probabilidade", "motivo_perda_categoria", "motivo_perda_id", "data_estimada_fechamento"]:
            if col in neg_cols:
                op.drop_column("crm_negociacoes", col)

    for tbl in [
        "crm_templates_mensagens",
        "crm_webhook_logs",
        "crm_webhooks",
        "crm_roleta_consultores",
        "crm_regras_automacao",
        "crm_motivos_perda",
    ]:
        if tbl in existing_tables:
            op.drop_table(tbl)
