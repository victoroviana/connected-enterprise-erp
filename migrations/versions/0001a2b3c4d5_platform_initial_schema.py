"""platform initial schema

Revision ID: 0001a2b3c4d5
Revises: 
Create Date: 2025-10-09 15:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0001a2b3c4d5"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario", sa.String(length=64), unique=True, nullable=True),
        sa.Column("nome_completo", sa.String(length=128), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("signature_path", sa.String(length=256), nullable=True),
        sa.Column("prox_num", sa.Integer(), nullable=True, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    param_category_enum = sa.Enum(
        "pagto_equip",
        "prazo_entrega",
        "frete",
        "validade",
        "garantia_eq",
        "garantia_sys",
        name="paramcategory",
    )
    param_category_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "param_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category", param_category_enum, nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("category", "label", name="uq_param_options_category_label"),
    )

    op.create_table(
        "equipments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("illustration_path", sa.String(length=256), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
    )

    servico_type_enum = sa.Enum("Ponto", "Acesso", name="services")
    servico_type_enum.create(op.get_bind(), checkfirst=True)

    modalidade_type_enum = sa.Enum("Aquisição", name="modalidades")
    modalidade_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company", sa.String(length=128), nullable=True),
        sa.Column("cnpj", sa.String(length=32), nullable=True),
        sa.Column("client_name", sa.String(length=128), nullable=True),
        sa.Column("email", sa.String(length=128), nullable=True),
        sa.Column("telefone", sa.String(length=32), nullable=True),
        sa.Column("pagamento", sa.String(length=256), nullable=True),
        sa.Column("prazo_entrega", sa.String(length=256), nullable=True),
        sa.Column("frete", sa.String(length=256), nullable=True),
        sa.Column("validade", sa.String(length=256), nullable=True),
        sa.Column("garantia", sa.String(length=256), nullable=True),
        sa.Column("garantia_sistema", sa.String(length=256), nullable=True),
        sa.Column("servico_type", servico_type_enum, nullable=False, server_default="Ponto"),
        sa.Column("modalidade_type", modalidade_type_enum, nullable=False, server_default="Aquisição"),
        sa.Column("enviar_email", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("email_corpo", sa.Text(), nullable=True),
        sa.Column("email_cc", sa.Text(), nullable=True),
        sa.Column("data_criacao", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(length=128), nullable=True),
        sa.Column("sistema_ativo", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("sistema_nome", sa.String(length=128), nullable=True),
        sa.Column("sistema_descricao", sa.Text(), nullable=True),
        sa.Column("sistema_imagem", sa.String(length=256), nullable=True),
        sa.Column("sistema_quantidade", sa.Integer(), nullable=True),
        sa.Column("sistema_preco_unitario", sa.Float(), nullable=True),
        sa.Column("sistema_preco_total", sa.Float(), nullable=True),
    )

    op.create_table(
        "proposal_equipments",
        sa.Column("proposal_id", sa.Integer(), sa.ForeignKey("proposals.id"), primary_key=True),
        sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("equipments.id"), primary_key=True),
    )

    op.create_table(
        "system_option_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_path", sa.String(length=256), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("key", name="uq_system_option_overrides_key"),
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=True, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=True, server_default="open"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )

    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("public", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("uploader_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("actor_name", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("ua", sa.String(length=255), nullable=True),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("before", sa.Text(), nullable=True),
        sa.Column("after", sa.Text(), nullable=True),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="todo"),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "task_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "subtasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("work_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "subtask_flow_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subtask_id", sa.Integer(), sa.ForeignKey("subtasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("shape", sa.String(length=20), nullable=False, server_default="rect"),
        sa.Column("color", sa.String(length=16), nullable=False, server_default="#e5e7eb"),
        sa.Column("x", sa.Integer(), nullable=False, server_default=sa.text("40")),
        sa.Column("y", sa.Integer(), nullable=False, server_default=sa.text("40")),
        sa.Column("w", sa.Integer(), nullable=False, server_default=sa.text("180")),
        sa.Column("h", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "subtask_flow_edges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subtask_id", sa.Integer(), sa.ForeignKey("subtasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_id", sa.Integer(), sa.ForeignKey("subtask_flow_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_id", sa.Integer(), sa.ForeignKey("subtask_flow_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("subtask_flow_edges")
    op.drop_table("subtask_flow_nodes")
    op.drop_table("subtasks")
    op.drop_table("task_logs")
    op.drop_table("tasks")
    op.drop_table("audit_logs")
    op.drop_table("attachments")
    op.drop_table("ticket_messages")
    op.drop_table("tickets")
    op.drop_table("system_option_overrides")
    op.drop_table("proposal_equipments")
    op.drop_table("proposals")
    op.drop_table("equipments")
    op.drop_table("param_options")
    op.drop_table("users")

    sa.Enum(name="modalidades").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="services").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="paramcategory").drop(op.get_bind(), checkfirst=True)
