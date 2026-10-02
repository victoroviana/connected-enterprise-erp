"""SQLAlchemy models for the chamados module — SollusFlow."""
from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal

from extensions import db


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default="medium")
    status = db.Column(db.String(20), default="open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    user = db.relationship("User", foreign_keys=[user_id], back_populates="tickets")
    assignee = db.relationship("User", foreign_keys=[assignee_id], back_populates="assigned_tickets")
    attachments = db.relationship(
        "Attachment",
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    messages = db.relationship(
        "TicketMessage",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketMessage.created_at",
        passive_deletes=True,
    )


class TicketMessage(db.Model):
    __tablename__ = "ticket_messages"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    public = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ticket = db.relationship("Ticket", back_populates="messages")
    author = db.relationship("User", back_populates="messages", foreign_keys=[author_id])


class Attachment(db.Model):
    __tablename__ = "attachments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    original_name = db.Column(db.String(255))
    filename = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(120))
    size = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploader_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    ticket = db.relationship("Ticket", back_populates="attachments")


try:  # Prefer canonical audit model when available
    from modules.audit.models import AuditLog  # type: ignore
except Exception:  # pragma: no cover - legacy fallback
    class AuditLog(db.Model):
        __tablename__ = "audit_logs"
        __audit_exclude__ = True

        id = db.Column(db.Integer, primary_key=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        actor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
        actor_email = db.Column(db.String(255))
        actor_name = db.Column(db.String(255))
        ip = db.Column(db.String(64))
        ua = db.Column(db.String(255))
        entity_type = db.Column(db.String(80), nullable=False)
        entity_id = db.Column(db.Integer)
        action = db.Column(db.String(40), nullable=False)
        message = db.Column(db.Text)
        before = db.Column(db.Text)
        after = db.Column(db.Text)


# ===========================================================================
# SollusFlow — Gestao de Pedidos & Processos
# ===========================================================================

# As 16 fases do processo comercial e pós-venda
SF_FASES = {
    1:  {"label": "Recebimento da Solicitacao",          "icon": "fa-inbox"},
    2:  {"label": "Conferencia de Documentos & CNPJ",    "icon": "fa-magnifying-glass"},
    3:  {"label": "Cadastro no Base ERP",                "icon": "fa-database"},
    4:  {"label": "Reserva de Equipamento",              "icon": "fa-boxes-stacked"},
    5:  {"label": "Geracao do Pedido / Contrato",        "icon": "fa-file-contract"},
    6:  {"label": "Pagamento de Entrada",                "icon": "fa-money-bill-wave"},
    7:  {"label": "Compra do Equipamento",               "icon": "fa-cart-shopping"},
    8:  {"label": "Envio do Pedido / Contrato",          "icon": "fa-paper-plane"},
    9:  {"label": "Envio do Formulario de Instalacao",   "icon": "fa-clipboard-list"},
    10: {"label": "Agendamento de Instalacao",           "icon": "fa-calendar-check"},
    11: {"label": "Faturamento & O.S",                   "icon": "fa-receipt"},
    12: {"label": "Envio de Dados de Acesso",            "icon": "fa-key"},
    13: {"label": "E-mail de Boas-vindas",               "icon": "fa-envelope-open-text"},
    14: {"label": "Agendamento de Treinamento",          "icon": "fa-chalkboard-user"},
    15: {"label": "Aguardando Resposta do Cliente",      "icon": "fa-user-clock"},
    16: {"label": "Pós-Venda",                           "icon": "fa-headset"},
}


class SfPedido(db.Model):
    """Card principal de pedido/cliente no SollusFlow."""
    __tablename__ = "sf_pedidos"

    id = db.Column(db.Integer, primary_key=True)
    numero_pedido = db.Column(db.String(50), nullable=True)
    cliente_nome = db.Column(db.String(200), nullable=False)
    cliente_cnpj = db.Column(db.String(20), nullable=True)
    tipo_pessoa = db.Column(db.String(10), nullable=False, default="pj")  # pj | pf
    tipo = db.Column(db.String(20), nullable=False, default="venda")  # venda | contrato
    valor = db.Column(db.Numeric(14, 2), nullable=True)
    consultor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    fase_atual = db.Column(db.Integer, nullable=False, default=1)
    prioridade = db.Column(db.String(20), nullable=False, default="normal")  # baixa | normal | alta | urgente
    data_entrada = db.Column(db.Date, nullable=True)
    data_prevista = db.Column(db.Date, nullable=True)
    data_treinamento = db.Column(db.Date, nullable=True)
    data_ultimo_pos_venda = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="ativo")  # ativo | concluido | cancelado
    descricao = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    consultor = db.relationship("User", foreign_keys=[consultor_id])
    responsavel = db.relationship("User", foreign_keys=[responsavel_id])
    historico = db.relationship(
        "SfFaseHistorico",
        back_populates="pedido",
        cascade="all, delete-orphan",
        order_by="SfFaseHistorico.created_at",
    )
    checklist = db.relationship(
        "SfChecklist",
        back_populates="pedido",
        cascade="all, delete-orphan",
        order_by="SfChecklist.posicao",
    )
    observacoes = db.relationship(
        "SfObservacao",
        back_populates="pedido",
        cascade="all, delete-orphan",
        order_by="SfObservacao.created_at",
    )

    @property
    def fase_label(self):
        return SF_FASES.get(self.fase_atual, {}).get("label", f"Fase {self.fase_atual}")

    @property
    def checklist_da_fase(self):
        return [c for c in self.checklist if c.fase == self.fase_atual]

    @property
    def progresso_fase(self):
        items = self.checklist_da_fase
        if not items:
            return None
        done = sum(1 for i in items if i.concluido)
        return {"done": done, "total": len(items)}

    def as_dict(self):
        prog = self.progresso_fase
        return {
            "id": self.id,
            "numero_pedido": self.numero_pedido,
            "cliente_nome": self.cliente_nome,
            "cliente_cnpj": self.cliente_cnpj,
            "tipo_pessoa": self.tipo_pessoa or ("pf" if (self.cliente_cnpj and len(self.cliente_cnpj.replace(".", "").replace("-", "").replace("/", "").strip()) == 11) else "pj"),
            "tipo": self.tipo,
            "valor": float(self.valor) if self.valor is not None else None,
            "consultor_id": self.consultor_id,
            "consultor_nome": (self.consultor.nome_completo or self.consultor.email) if self.consultor else None,
            "responsavel_id": self.responsavel_id,
            "responsavel_nome": (self.responsavel.nome_completo or self.responsavel.email) if self.responsavel else None,
            "fase_atual": self.fase_atual,
            "fase_label": self.fase_label,
            "prioridade": self.prioridade,
            "data_entrada": self.data_entrada.isoformat() if self.data_entrada else None,
            "data_prevista": self.data_prevista.isoformat() if self.data_prevista else None,
            "data_treinamento": self.data_treinamento.isoformat() if self.data_treinamento else None,
            "data_ultimo_pos_venda": self.data_ultimo_pos_venda.isoformat() if self.data_ultimo_pos_venda else None,
            "status": self.status,
            "descricao": self.descricao,
            "progresso": prog,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SfFaseHistorico(db.Model):
    """Log de mudanca de fase de um pedido."""
    __tablename__ = "sf_fase_historico"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("sf_pedidos.id", ondelete="CASCADE"), nullable=False)
    fase_de = db.Column(db.Integer, nullable=True)
    fase_para = db.Column(db.Integer, nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    transferido_para_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    observacao = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    pedido = db.relationship("SfPedido", back_populates="historico")
    usuario = db.relationship("User", foreign_keys=[usuario_id])
    transferido_para = db.relationship("User", foreign_keys=[transferido_para_id])

    def as_dict(self):
        return {
            "id": self.id,
            "pedido_id": self.pedido_id,
            "fase_de": self.fase_de,
            "fase_para": self.fase_para,
            "fase_de_label": SF_FASES.get(self.fase_de, {}).get("label", "") if self.fase_de else None,
            "fase_para_label": SF_FASES.get(self.fase_para, {}).get("label", ""),
            "usuario_id": self.usuario_id,
            "usuario_nome": (self.usuario.nome_completo or self.usuario.email) if self.usuario else None,
            "transferido_para_id": self.transferido_para_id,
            "transferido_para_nome": (self.transferido_para.nome_completo or self.transferido_para.email) if self.transferido_para else None,
            "observacao": self.observacao,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SfChecklist(db.Model):
    """Item de checklist por fase de um pedido."""
    __tablename__ = "sf_checklist"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("sf_pedidos.id", ondelete="CASCADE"), nullable=False)
    fase = db.Column(db.Integer, nullable=False)
    titulo = db.Column(db.String(300), nullable=False)
    concluido = db.Column(db.Boolean, nullable=False, default=False)
    concluido_por_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    criado_por_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    concluido_at = db.Column(db.DateTime, nullable=True)
    posicao = db.Column(db.Integer, nullable=False, default=0)
    data_lembrete = db.Column(db.Date, nullable=True)
    alerta_5d_enviado = db.Column(db.Boolean, nullable=False, default=False)
    alerta_3d_enviado = db.Column(db.Boolean, nullable=False, default=False)
    alerta_0d_enviado = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    pedido = db.relationship("SfPedido", back_populates="checklist")
    concluido_por = db.relationship("User", foreign_keys=[concluido_por_id])
    criado_por = db.relationship("User", foreign_keys=[criado_por_id])
    responsavel = db.relationship("User", foreign_keys=[responsavel_id])

    @property
    def dias_restantes(self) -> int | None:
        if not self.data_lembrete:
            return None
        return (self.data_lembrete - date.today()).days

    def as_dict(self):
        hoje = date.today()
        dias = (self.data_lembrete - hoje).days if self.data_lembrete else None
        return {
            "id": self.id,
            "pedido_id": self.pedido_id,
            "fase": self.fase,
            "titulo": self.titulo,
            "concluido": self.concluido,
            "concluido_por_id": self.concluido_por_id,
            "concluido_por_nome": (self.concluido_por.nome_completo or self.concluido_por.email) if self.concluido_por else None,
            "concluido_at": self.concluido_at.isoformat() if self.concluido_at else None,
            "criado_por_id": self.criado_por_id,
            "criado_por_nome": (self.criado_por.nome_completo or self.criado_por.email) if self.criado_por else None,
            "responsavel_id": self.responsavel_id,
            "responsavel_nome": (self.responsavel.nome_completo or self.responsavel.email) if self.responsavel else None,
            "posicao": self.posicao,
            "data_lembrete": self.data_lembrete.isoformat() if self.data_lembrete else None,
            "dias_restantes": dias,
            "alerta_5d_enviado": bool(self.alerta_5d_enviado),
            "alerta_3d_enviado": bool(self.alerta_3d_enviado),
            "alerta_0d_enviado": bool(self.alerta_0d_enviado),
        }


class SfObservacao(db.Model):
    """Comentario/observacao compartilhado em um pedido."""
    __tablename__ = "sf_observacoes"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("sf_pedidos.id", ondelete="CASCADE"), nullable=False)
    autor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    corpo = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    pedido = db.relationship("SfPedido", back_populates="observacoes")
    autor = db.relationship("User", foreign_keys=[autor_id])

    def as_dict(self):
        return {
            "id": self.id,
            "pedido_id": self.pedido_id,
            "autor_id": self.autor_id,
            "autor_nome": (self.autor.nome_completo or self.autor.email) if self.autor else "Sistema",
            "corpo": self.corpo,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SfConfig(db.Model):
    """Configurações globais chave-valor do SollusFlow (ex: ordem das colunas)."""
    __tablename__ = "sf_config"

    chave = db.Column(db.String(100), primary_key=True)
    valor = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def as_dict(self):
        return {
            "chave": self.chave,
            "valor": self.valor,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# Aliases de compatibilidade para integrações (ex.: Sollus CRM)
SFPedido = SfPedido
SFFaseHistorico = SfFaseHistorico
SFChecklist = SfChecklist
SFObservacao = SfObservacao


