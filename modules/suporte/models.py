"""SQLAlchemy models referentes ao legado de suporte."""
from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import event, inspect, Index
from sqlalchemy.orm import object_session

from extensions import db


class AtendimentoSuporte(db.Model):
    __tablename__ = "atendimento_suporte"
    id = db.Column(db.Integer, primary_key=True)
    cliente = db.Column(db.String(255), nullable=False)
    data_entrada = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    data_atendimento = db.Column(db.DateTime)
    tipo_atendimento = db.Column(db.String(120))
    status = db.Column(db.String(32), nullable=False, default="Entrada")
    descricao = db.Column(db.Text)
    resumo_atendimento = db.Column(db.Text)
    os_entrada = db.Column(db.String(64), index=True)
    os_saida = db.Column(db.String(64))
    criado_por = db.Column(db.String(120))
    usuario_designado = db.Column(db.Integer, db.ForeignKey("users.id"))
    cnpj = db.Column("CNPJ", db.String(32))
    sistema = db.Column("SISTEMA", db.String(120))
    quantidade_pessoas = db.Column("QUANTIDADE_DE_PESSOAS", db.String(32))
    texto_mobile = db.Column("TEXTO_MOBILE", db.Text)
    email = db.Column(db.String(255))
    observacoes = db.Column(db.Text)
    observacoes_alerta = db.Column(db.Text)
    arq_entrada = db.Column(db.String(255))
    arq_saida = db.Column(db.String(255))
    meet_link = db.Column(db.String(512))
    meet_event_id = db.Column(db.String(255))
    meet_session_key = db.Column(db.String(64))
    meet_start = db.Column(db.DateTime)

    assigned_user = db.relationship(
        "User",
        foreign_keys=[usuario_designado],
        lazy="joined",
    )

    _STATUS_LABELS = {
        "Entrada": "Entrada",
        "Atencao": "Atenção",
        "Concluido": "Concluído",
    }

    def status_label(self) -> str:
        value = (self.status or "").strip() or "Entrada"
        return self._STATUS_LABELS.get(value, value.title())

    def to_dict(self) -> dict:
        """JSON payload utilizado nos formulários/modais."""
        return {
            "id": self.id,
            "cliente": self.cliente,
            "cnpj": self.cnpj,
            "data_entrada": _iso_or_str(self.data_entrada),
            "data_atendimento": _iso_or_str(self.data_atendimento),
            "tipo_atendimento": self.tipo_atendimento,
            "status": self.status,
            "descricao": self.descricao,
            "resumo_atendimento": self.resumo_atendimento,
            "os_entrada": self.os_entrada,
            "os_saida": self.os_saida,
            "criado_por": self.criado_por,
            "usuario_designado": self.usuario_designado,
            "sistema": self.sistema,
            "quantidade_pessoas": self.quantidade_pessoas,
            "texto_mobile": self.texto_mobile,
            "email": self.email,
            "observacoes": self.observacoes,
            "observacoes_alerta": self.observacoes_alerta,
            "arq_entrada": self.arq_entrada,
            "arq_saida": self.arq_saida,
            "meet_link": self.meet_link,
            "meet_event_id": self.meet_event_id,
            "meet_session_key": self.meet_session_key,
            "meet_start": _iso_or_str(self.meet_start),
            "status_label": self.status_label(),
            "assigned_user_name": (self.assigned_user.nome_completo if self.assigned_user else None),
            "assigned_user_unit": (self.assigned_user.unit_code if self.assigned_user else None),
            "assigned_user_email": (self.assigned_user.email if self.assigned_user else None),
        }


class AtendimentoSuporteLog(db.Model):
    __tablename__ = "atendimento_suporte_logs"

    id = db.Column(db.Integer, primary_key=True)
    atendimento_suporte_id = db.Column(db.Integer, db.ForeignKey("atendimento_suporte.id"), nullable=False)
    campo = db.Column(db.String(120), nullable=False)
    valor_antigo = db.Column(db.Text)
    valor_novo = db.Column(db.Text)
    modificado_por = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    atendimento = db.relationship("AtendimentoSuporte", backref="logs")


class UltimoAtendimento(db.Model):
    __tablename__ = "ultimo_atendimento"
    tecnico_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    ultimo_atendimento = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Empresa(db.Model):
    __tablename__ = "empresa"
    id = db.Column(db.Integer, primary_key=True)
    cliente = db.Column(db.String(255), nullable=False)
    cnpj = db.Column(db.String(32), unique=True)
    observacoes = db.Column(db.Text)
    observacoes_alerta = db.Column(db.Text)


class AssistenciaTarefa(db.Model):
    __tablename__ = "tarefas"
    __table_args__ = (
        Index("ix_tarefas_status", "status"),
        Index("ix_tarefas_departamento", "departamento_responsavel"),
        Index("ix_tarefas_data_fim", "data_fim"),
    )

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    data_criacao = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    data_fim = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    departamento_responsavel = db.Column(db.String(255), nullable=False)
    usuario_designado = db.Column(db.String(255))
    descricao = db.Column(db.Text)
    status = db.Column(db.String(32), nullable=False, default="Entrada")
    notificacao = db.Column(db.String(8), default="nao")
    data_modificacao = db.Column(db.DateTime)
    unidade = db.Column(db.String(64), nullable=False)
    OS = db.Column(db.String(25), nullable=False)
    data_envio = db.Column(db.Date)
    data_retorno = db.Column(db.Date)
    cnpj = db.Column(db.String(20))
    cep = db.Column(db.String(12))
    bairro = db.Column(db.String(120))
    tipo_entrada = db.Column(db.String(16))
    tipo_atendimento = db.Column(db.String(120))
    ORCAMENTO = db.Column(db.String(500))
    CONTRATO = db.Column(db.String(50))
    criado_por = db.Column(db.String(50))
    atualizacoes = db.Column(db.Text)
    resposta = db.Column(db.String(255))

    anexos = db.relationship(
        "AssistenciaAnexo",
        back_populates="tarefa",
        cascade="all, delete-orphan",
        lazy="select",
    )
    logs = db.relationship(
        "AssistenciaTarefaLog",
        back_populates="tarefa",
        cascade="all, delete-orphan",
        lazy="select",
    )

    _STATUS_LABELS = {
        "Entrada": "Entrada",
        "em progresso": "Em progresso",
        "aguardando": "Aguardando",
        "fabrica": "Fábrica",
        "concluído": "Concluído",
        "devolucao_sem_reparo": "Devolucao sem reparo",
        "descarte": "Descarte",
    }

    def status_label(self) -> str:
        value = (self.status or "").strip()
        return self._STATUS_LABELS.get(value, value.title() if value else "Entrada")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "nome": self.nome,
            "data_criacao": _iso_or_str(self.data_criacao),
            "data_fim": _iso_or_str(self.data_fim),
            "departamento_responsavel": self.departamento_responsavel,
            "usuario_designado": self.usuario_designado,
            "descricao": self.descricao,
            "status": self.status,
            "notificacao": self.notificacao,
            "data_modificacao": _iso_or_str(self.data_modificacao),
            "unidade": self.unidade,
            "os": self.OS,
            "data_envio": _iso_or_str(self.data_envio),
            "data_retorno": _iso_or_str(self.data_retorno),
            "cnpj": self.cnpj,
            "cep": self.cep,
            "bairro": self.bairro,
            "tipo_entrada": self.tipo_entrada,
            "tipo_atendimento": self.tipo_atendimento,
            "orcamento": self.ORCAMENTO,
            "contrato": self.CONTRATO,
            "criado_por": self.criado_por,
            "atualizacoes": self.atualizacoes,
            "resposta": self.resposta,
        }


@event.listens_for(AssistenciaTarefa.status, "set")
def on_status_set(target, value, oldvalue, initiator):
    if value == "retorno":
        target.departamento_responsavel = "ASSISTENCIA TECNICA"


class AssistenciaOrcamento(db.Model):
    __tablename__ = "assistencia_orcamentos"

    id = db.Column(db.Integer, primary_key=True)
    tarefa_id = db.Column(db.Integer, db.ForeignKey("tarefas.id"), nullable=True)
    tipo = db.Column(db.String(32), nullable=False)
    itens = db.Column(db.JSON, nullable=False, default=list)
    total = db.Column(db.Float, nullable=False, default=0.0)
    snapshot = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.String(120))

    tarefa = db.relationship(
        "AssistenciaTarefa",
        backref=db.backref("orcamentos", lazy="dynamic"),
    )


class AssistenciaEquipamentoProposta(db.Model):
    __tablename__ = "assistencia_equipamento_propostas"

    id = db.Column(db.Integer, primary_key=True)
    modalidade = db.Column(db.String(16), nullable=False)
    cliente = db.Column(db.String(255), nullable=False)
    cnpj = db.Column(db.String(32))
    contato = db.Column(db.String(120))
    email = db.Column(db.String(255))
    telefone = db.Column(db.String(64))
    validade = db.Column(db.String(64), nullable=False, default="20 dias")
    prazo_entrega = db.Column(db.String(120))
    condicoes_pagamento = db.Column(db.String(255))
    observacoes = db.Column(db.Text)
    itens = db.Column(db.JSON, nullable=False, default=list)
    total = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.String(120))


class OrcamentoStatus(db.Model):
    __tablename__ = "orcamentos_status"

    id = db.Column(db.Integer, primary_key=True)
    data_envio = db.Column("Data_envio", db.Date)
    tipo_visita = db.Column("Tipo_visita", db.String(32))
    equipamento = db.Column("Equipamento", db.String(255))
    cliente = db.Column("Cliente", db.String(255))
    numero_proposta = db.Column("Numero_proposta", db.String(255))
    valor = db.Column("Valor", db.Numeric(10, 2))
    status = db.Column("Status", db.String(24))
    data_aprovacao = db.Column("Data_aprovacao", db.Date)
    data_atendimento = db.Column("Data_atendimento", db.Date)
    ordem_servico = db.Column("Ordem_servico", db.String(255))
    nf_data = db.Column("NF_data", db.String(255))
    outras_informacoes = db.Column("Outras_informacoes", db.Text)
    ultima_cobranca = db.Column("ultima_cobranca", db.Date)
    unidade = db.Column("unidade", db.String(64), nullable=False)
    responsavel = db.Column("responsavel", db.String(255), nullable=False)
    fabrica = db.Column("Fabrica", db.String(15), nullable=False, default="")


class AssistenciaTarefaLog(db.Model):
    __tablename__ = "tarefas_logs"

    id = db.Column(db.Integer, primary_key=True)
    tarefa_id = db.Column(db.Integer, db.ForeignKey("tarefas.id"), nullable=False)
    campo = db.Column(db.String(255), nullable=False)
    valor_antigo = db.Column(db.Text)
    valor_novo = db.Column(db.Text)
    modificado_por = db.Column(db.String(255))
    data_modificacao = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    tarefa = db.relationship("AssistenciaTarefa", back_populates="logs")


class AssistenciaAnexo(db.Model):
    __tablename__ = "anexos"

    id = db.Column(db.Integer, primary_key=True)
    id_tarefa = db.Column(db.Integer, db.ForeignKey("tarefas.id"), nullable=False)
    nome_arquivo = db.Column(db.String(255))
    url_arquivo = db.Column(db.Text)

    tarefa = db.relationship("AssistenciaTarefa", back_populates="anexos")


class AtestadoArquivo(db.Model):
    __tablename__ = "arquivo"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    conteudo = db.Column(db.LargeBinary(length=16777215), nullable=False)

    emails = db.relationship(
        "AtestadoEmail",
        back_populates="arquivo",
        cascade="all, delete-orphan",
        lazy="select",
    )
    logs_envio = db.relationship(
        "AtestadoLogEnvio",
        back_populates="arquivo",
        cascade="all, delete-orphan",
        lazy="select",
    )


class AtestadoEmail(db.Model):
    __tablename__ = "email"

    id = db.Column(db.Integer, primary_key=True)
    endereco = db.Column(db.String(255), nullable=False)
    arquivo_id = db.Column(db.Integer, db.ForeignKey("arquivo.id"), nullable=False)

    arquivo = db.relationship("AtestadoArquivo", back_populates="emails")


class AtestadoLogEnvio(db.Model):
    __tablename__ = "log_envio"

    id = db.Column(db.Integer, primary_key=True)
    arquivo_id = db.Column(db.Integer, db.ForeignKey("arquivo.id"), nullable=False)
    data_envio = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20))
    mensagem = db.Column(db.Text)

    arquivo = db.relationship("AtestadoArquivo", back_populates="logs_envio")


class AtestadoTask(db.Model):
    __tablename__ = "task"

    id = db.Column(db.String(36), primary_key=True)
    status = db.Column(db.String(20))
    progress = db.Column(db.Integer)
    total = db.Column(db.Integer)
    current = db.Column(db.Integer)
    error = db.Column(db.Text)
    date_created = db.Column(db.DateTime, default=datetime.now)
    date_modified = db.Column(db.DateTime, onupdate=datetime.now)


def _iso_or_str(value):
    """Safely render a datetime/date/string to ISO for JSON payloads."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, str):
        txt = value.strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
            try:
                return datetime.strptime(txt, fmt).isoformat()
            except Exception:
                continue
        return txt or None
    if isinstance(value, date):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


@event.listens_for(AssistenciaTarefa, "before_update")
def _assistencia_before_update(mapper, connection, target: AssistenciaTarefa):
    """Emula triggers do legado: registra diffs e atualiza data_modificacao."""
    target.data_modificacao = datetime.utcnow()
    session = object_session(target)
    if session is None:
        return
    inspector = inspect(target)
    fields = [
        "nome",
        "cnpj",
        "unidade",
        "departamento_responsavel",
        "usuario_designado",
        "tipo_entrada",
        "tipo_atendimento",
        "cep",
        "bairro",
        "CONTRATO",
        "ORCAMENTO",
        "OS",
        "data_criacao",
        "data_fim",
        "data_envio",
        "data_retorno",
        "status",
        "descricao",
        "notificacao",
        "resposta",
    ]
    actor = getattr(target, "_actor", None) or "trigger"
    for field in fields:
        hist = inspector.attrs[field].history
        if not hist.has_changes():
            continue
        old = hist.deleted[0] if hist.deleted else None
        new = hist.added[0] if hist.added else getattr(target, field)
        if str(old) == str(new):
            continue
        log = AssistenciaTarefaLog(
            tarefa_id=target.id,
            campo=field,
            valor_antigo=str(old) if old is not None else None,
            valor_novo=str(new) if new is not None else None,
            modificado_por=actor,
            data_modificacao=datetime.utcnow(),
        )
        session.add(log)


class OrcamentoTemplate(db.Model):
    __tablename__ = "orcamento_templates"

    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(64), unique=True, nullable=False)
    label = db.Column(db.String(120), nullable=False)
    table_title = db.Column(db.String(120), nullable=False)
    items = db.Column(db.JSON, nullable=False, default=list)
    condicoes = db.Column(db.JSON, nullable=False, default=list)
    observacao = db.Column(db.Text)
    aceite = db.Column(db.JSON, nullable=False, default=list)
    ativo = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "chave": self.chave,
            "label": self.label,
            "table_title": self.table_title,
            "items": self.items,
            "condicoes": self.condicoes,
            "observacao": self.observacao,
            "aceite": self.aceite,
            "ativo": self.ativo,
        }
