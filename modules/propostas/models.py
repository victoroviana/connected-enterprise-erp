
"""Database models for the proposals module and shared User entity."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Optional
import json
import unicodedata

from flask_login import UserMixin
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import synonym

from extensions import db


from modules.chamados.models import Ticket, TicketMessage
PERMISSION_DEFINITIONS: dict[str, dict[str, object]] = {
    # COMERCIAL
    "propostas": {"label": "Comercial", "default": True},
    "propostas_nova": {"label": "Comercial - Nova Proposta", "default": True},
    "propostas_historico": {"label": "Comercial - Histórico", "default": True},
    "comercial_agenda": {"label": "Comercial - Agenda dos Consultores", "default": True},
    "comercial_parceiros": {"label": "Comercial - Empresas Parceiras", "default": True},
    "propostas_parametros": {"label": "Comercial - Parâmetros", "default": False},
    
    # SOLLUS CRM
    "crm": {"label": "Sollus CRM", "default": True},
    "crm_funis": {"label": "Sollus CRM - Funis de Vendas", "default": True},
    "crm_empresas": {"label": "Sollus CRM - Empresas & Contatos", "default": True},
    "crm_leads": {"label": "Sollus CRM - Leads de Marketing", "default": True},
    "crm_metricas": {"label": "Sollus CRM - Métricas & Relatórios", "default": False},
    "crm_ver_todos": {"label": "Sollus CRM - Ver todas as negociações", "default": False},
    
    # ESTOQUE
    "estoque": {"label": "Estoque", "default": False},
    "estoque_pecas": {"label": "Estoque - Peças", "default": False},
    
    # SOLLUS TICKETS
    "chamados": {"label": "Sollus Tickets", "default": True},
    "chamados_novo": {"label": "Sollus Tickets - Novo Ticket", "default": True},
    "chamados_fechados": {"label": "Sollus Tickets - Tickets fechados", "default": False},
    "chamados_relatorios": {"label": "Sollus Tickets - Relatórios", "default": False},
    "chamados_autoassign": {"label": "Sollus Tickets - Auto-assign", "default": False},
    "chamados_admin": {"label": "Sollus Tickets - Administração", "default": False},
    
    # SOLLUSFLOW
    "central_conhecimento": {"label": "SollusFlow", "default": True},
    "central_conhecimento_quadro": {"label": "SollusFlow - Painel", "default": True},
    "central_conhecimento_historico": {"label": "SollusFlow - Histórico", "default": False},
    "central_conhecimento_config": {"label": "SollusFlow - Configurações & Alertas", "default": False},
    
    # ADMIN
    "admin": {"label": "Administração", "default": False},
    "usuarios_acesso": {"label": "Admin - Usuários", "default": False},
    "usuarios_gerenciar": {"label": "Admin - Usuários (gerenciar)", "default": False},
    "permissoes_gerenciar": {"label": "Admin - Permissões", "default": False},
    "admin_auditoria": {"label": "Admin - Auditoria", "default": False},
    "admin_aniversariantes": {"label": "Admin - Aniversariantes", "default": False},
    "admin_ferias": {"label": "Admin - Mapa de Férias", "default": False},
    "admin_galeria": {"label": "Admin - Galeria", "default": False},
    "admin_monitoramento": {"label": "Admin - Monitoramento de Atrasos", "default": False},

    # SUPORTE
    "admin_suporte": {"label": "Suporte", "default": False},
    "suporte_atendimentos": {"label": "Suporte - Atendimentos", "default": False},
    "suporte_agenda": {"label": "Suporte - Agenda técnica", "default": False},

    # ASSISTÊNCIA TÉCNICA
    "admin_assistencia": {"label": "Assistência técnica", "default": False},
    "assistencia_chamados": {"label": "Assistência - Chamados", "default": False},
    "assistencia_equipamentos": {"label": "Assistência - Controle de equipamentos", "default": False},
    "assistencia_atendimentos": {"label": "Assistência - Atendimentos", "default": False},
    "assistencia_propostas": {"label": "Assistência - Propostas", "default": False},
    "assistencia_orcamentos": {"label": "Assistência - Orçamentos", "default": False},
    "assistencia_atestados": {"label": "Assistência - Atestados", "default": False},
    "assistencia_agenda": {"label": "Assistência - Agenda técnica", "default": False},
    
    # TÉCNICA
    "admin_agenda_tecnica": {"label": "Técnica - Agenda técnica", "default": False},
    "tecnica_chamados": {"label": "Técnica - Chamados técnicos", "default": False},
    
    # FINANCEIRO
    "financeiro": {"label": "Financeiro", "default": False},
    "financeiro_contas": {"label": "Financeiro - Contas a receber", "default": False},
    "financeiro_cancelados": {"label": "Financeiro - Cancelados", "default": False},
    "financeiro_cota": {"label": "Financeiro - Cota mensal", "default": False},
    
    # CONTRATOS
    "contratos": {"label": "Contratos", "default": False},
    "contratos_cancelamentos": {"label": "Contratos - Cancelamentos", "default": False},
    "contratos_contas": {"label": "Contratos - Contas a receber", "default": False},
    "contratos_manutencoes": {"label": "Contratos - Manutenções", "default": False},
    
    # CRACHÁ
    "cracha": {"label": "Crachá", "default": False},
    "cracha_clientes": {"label": "Crachá - Clientes", "default": False},
    "cracha_modelos": {"label": "Crachá - Crachás", "default": False},
    "cracha_extratos": {"label": "Crachá - Extratos", "default": False},
    "cracha_recibos": {"label": "Crachá - Recibos", "default": False},
    "cracha_cortador": {"label": "Crachá - Cortador de Fotos", "default": False},
    "cracha_produtos": {"label": "Crachá - Produtos", "default": False},
    "cracha_fornecedores": {"label": "Crachá - Fornecedores", "default": False},
    "cracha_empresas": {"label": "Crachá - Empresas", "default": False},
}


def default_permissions() -> dict[str, bool]:
    """Return default permission flags for new users."""
    return {key: bool(value.get("default", False)) for key, value in PERMISSION_DEFINITIONS.items()}


def _normalize_enum_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = "".join(ch for ch in text if ch.isalnum())
    return text.lower()


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    permissions = db.Column(db.JSON, nullable=False, default=default_permissions)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Department {self.slug!r}>"

    def to_permissions(self) -> dict[str, bool]:
        base = default_permissions()
        if self.permissions:
            base.update(self.permissions)
        return base


user_departments = db.Table(
    "user_departments",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("department_id", db.Integer, db.ForeignKey("departments.id"), primary_key=True),
)



class RolePermission(db.Model):
    __tablename__ = "role_permissions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    label = db.Column(db.String(120), nullable=False)
    permissions = db.Column(db.JSON, nullable=False, default=default_permissions)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_permissions(self) -> dict[str, bool]:
        base = default_permissions()
        base.update(self.permissions or {})
        if base.get("usuarios_gerenciar"):
            base["usuarios_acesso"] = True
        return base
    @property
    def badge_label(self) -> str:
        if (self.name or '').lower() == 'usuario':
            return 'USUÁRIO'
        return (self.name or '').upper()



proposal_equipments = db.Table(
    "proposal_equipments",
    db.Column("proposal_id", db.Integer, db.ForeignKey("proposals.id"), primary_key=True),
    db.Column("equipment_id", db.Integer, db.ForeignKey("equipments.id"), primary_key=True),
)


class ParamCategory(Enum):
    PAGTO_EQUIP = "pagto_equip"
    PAGTO_SERVICO = "pagto_servico"
    PAGTO_CONTRATO = "pagto_contrato"
    PRAZO_ENTREGA = "prazo_entrega"
    FRETE = "frete"
    VALIDADE = "validade"
    GARANTIA_EQ = "garantia_eq"
    GARANTIA_SYS = "garantia_sys"


class ParamOption(db.Model):
    __tablename__ = "param_options"
    __table_args__ = (
        db.UniqueConstraint("category", "label", name="uq_param_options_category_label"),
    )

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(
        db.Enum(
            ParamCategory,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            name="paramcategory",
        ),
        nullable=False,
    )
    label = db.Column(db.String(120), nullable=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_by = db.relationship("User", backref="created_param_options")


class User(UserMixin, db.Model):
    """Unified user entity shared between proposals and chamados."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(64), unique=True)
    nome_completo = db.Column(db.String(128))
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    tipo = db.Column(db.String(20))
    role = db.Column(db.String(20), nullable=False, default="usuario")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    signature_path = db.Column(db.String(256))
    signature_text = db.Column(db.Text)
    avatar_path = db.Column(db.String(256))
    prox_num = db.Column(db.Integer, default=1)
    permissions = db.Column(db.JSON, nullable=False, default=default_permissions)
    phone = db.Column(db.String(32))
    phone_extra = db.Column(db.Text)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    unit_code = db.Column(db.String(32))
    ramal = db.Column(db.String(32))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    propostas = db.relationship(
        "Proposal",
        backref="usuario",
        lazy=True,
        foreign_keys="Proposal.usuario_id",
    )
    tickets = db.relationship(
        "Ticket",
        foreign_keys="Ticket.user_id",
        back_populates="user",
        lazy="dynamic",
    )
    assigned_tickets = db.relationship(
        "Ticket",
        foreign_keys="Ticket.assignee_id",
        back_populates="assignee",
        lazy="dynamic",
    )
    messages = db.relationship(
        "TicketMessage",
        foreign_keys="TicketMessage.author_id",
        back_populates="author",
        lazy="dynamic",
    )
    pedidos_responsavel = db.relationship(
        "SfPedido",
        foreign_keys="SfPedido.responsavel_id",
        back_populates="responsavel",
        lazy="dynamic",
    )
    pedidos_consultor = db.relationship(
        "SfPedido",
        foreign_keys="SfPedido.consultor_id",
        back_populates="consultor",
        lazy="dynamic",
    )
    department = db.relationship("Department", backref=db.backref("users", lazy="dynamic"))
    departments = db.relationship(
        "Department",
        secondary=user_departments,
        lazy="selectin",
        backref=db.backref("members", lazy="dynamic"),
    )

    @property
    def extra_phones(self) -> list[str]:
        if not self.phone_extra:
            return []
        try:
            data = json.loads(self.phone_extra)
        except (TypeError, ValueError):
            return []
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
        if isinstance(data, str) and data.strip():
            return [data.strip()]
        return []

    @extra_phones.setter
    def extra_phones(self, values):
        cleaned: list[str] = []
        if isinstance(values, (list, tuple, set)):
            cleaned = [str(item).strip() for item in values if str(item).strip()]
        elif isinstance(values, str) and values.strip():
            cleaned = [values.strip()]
        self.phone_extra = json.dumps(cleaned, ensure_ascii=False) if cleaned else None

    def all_contact_phones(self) -> list[str]:
        phones: list[str] = []
        if self.phone and self.phone.strip():
            phones.append(self.phone.strip())
        for item in self.extra_phones:
            if item not in phones:
                phones.append(item)
        return phones

    @property
    def department_names(self) -> list[str]:
        names: list[str] = []
        try:
            if self.departments:
                for dept in self.departments:
                    name = (dept.name or "").strip()
                    if name and name not in names:
                        names.append(name)
        except Exception:
            names = []
        if not names and self.department:
            name = (self.department.name or "").strip()
            if name:
                names.append(name)
        return names

    senha_hash = synonym("password_hash")

    @property
    def name(self) -> str:
        return self.nome_completo or self.usuario or self.email

    @name.setter
    def name(self, value: str) -> None:
        self.nome_completo = value

    @property
    def username(self) -> Optional[str]:
        return self.usuario or (self.email.split('@', 1)[0] if self.email else None)

    def get_id(self) -> str:  # type: ignore[override]
        return str(self.id)


class Equipment(db.Model):
    __tablename__ = "equipments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128))
    fabricante = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text)
    _illustration_path = db.Column("illustration_path", db.String(256))
    unit_price = db.Column(db.Float)
    preco_locacao = db.Column(db.Float, nullable=True)
    quantity = db.Column(db.Integer)
    preco_anterior = db.Column(db.Float, nullable=True)
    preco_locacao_anterior = db.Column(db.Float, nullable=True)
    preco_alterado_em = db.Column(db.DateTime, nullable=True)
    preco_locacao_alterado_em = db.Column(db.DateTime, nullable=True)
    preco_alterado_por = db.Column(db.String(120), nullable=True)
    preco_locacao_alterado_por = db.Column(db.String(120), nullable=True)
    tipo_equipamento = db.Column(db.String(64), nullable=True, index=True)

    @staticmethod
    def _normalize_illustration_path(value):
        """Remove prefixos redundantes e normaliza separadores."""
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        path = PurePosixPath(text.replace("\\", "/").lstrip("/"))
        parts = [p for p in path.parts if p not in ("", ".", "..")]

        if parts and parts[0].lower() == "static":
            parts = parts[1:]
        if parts and parts[0].lower() == "images":
            parts = parts[1:]

        if not parts:
            return None

        return "/".join(parts)

    @hybrid_property
    def illustration_path(self):
        return self._normalize_illustration_path(self._illustration_path)

    @illustration_path.setter
    def illustration_path(self, value):
        self._illustration_path = self._normalize_illustration_path(value)

    @illustration_path.expression
    def illustration_path(cls):  # type: ignore[override]
        return cls._illustration_path




class Part(db.Model):
    __tablename__ = "parts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128))
    fabricante = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text)
    _illustration_path = db.Column("illustration_path", db.String(256))
    unit_price = db.Column(db.Float)
    quantity = db.Column(db.Integer)

    @staticmethod
    def _normalize_illustration_path(value):
        """Remove prefixos redundantes e normaliza separadores."""
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        path = PurePosixPath(text.replace("\\", "/").lstrip("/"))
        parts = [p for p in path.parts if p not in ("", ".", "..")]

        if parts and parts[0].lower() == "static":
            parts = parts[1:]
        if parts and parts[0].lower() == "images":
            parts = parts[1:]

        if not parts:
            return None

        return "/".join(parts)

    @hybrid_property
    def illustration_path(self):
        return self._normalize_illustration_path(self._illustration_path)

    @illustration_path.setter
    def illustration_path(self, value):
        self._illustration_path = self._normalize_illustration_path(value)

    @illustration_path.expression
    def illustration_path(cls):  # type: ignore[override]
        return cls._illustration_path

class ServicoType(Enum):
    PONTO = 'PONTO'
    ACESSO = 'ACESSO'

    @classmethod
    def _missing_(cls, value):  # type: ignore[override]
        normalized = _normalize_enum_text(value)
        if "ponto" in normalized:
            return cls.PONTO
        if "acesso" in normalized:
            return cls.ACESSO
        return None

    @property
    def label(self) -> str:
        return 'Ponto' if self is ServicoType.PONTO else 'Acesso'

    def __str__(self) -> str:
        return self.label


class ModalidadeType(Enum):
    AQUISICAO = 'AQUISICAO'
    LOCACAO = 'LOCACAO'

    @classmethod
    def _missing_(cls, value):  # type: ignore[override]
        normalized = _normalize_enum_text(value)
        if "aquisicao" in normalized:
            return cls.AQUISICAO
        if "locacao" in normalized:
            return cls.LOCACAO
        return None

    @property
    def label(self) -> str:
        return 'Aquisição' if self is ModalidadeType.AQUISICAO else 'Locação'

    def __str__(self) -> str:
        return self.label


class Proposal(db.Model):
    __tablename__ = "proposals"

    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(128))
    cnpj = db.Column(db.String(32))
    client_name = db.Column(db.String(128))
    email = db.Column(db.String(128))
    telefone = db.Column(db.String(32))
    observacao_comercial = db.Column(db.Text)
    ambiente_incluir = db.Column(db.Boolean, default=False, nullable=False)
    ambiente_fotos = db.Column(db.JSON)
    client_document_type = db.Column(db.String(16))

    issuer_company_code = db.Column(db.String(32))

    pagamento = db.Column(db.String(256))
    pagamento_servico = db.Column(db.String(256))
    pagamento_contrato = db.Column(db.String(256))
    prazo_entrega = db.Column(db.String(256))
    frete = db.Column(db.String(256))
    validade = db.Column(db.String(256))
    garantia = db.Column(db.String(256))
    garantia_sistema = db.Column(db.String(256))

    servico_type = db.Column(db.Enum(ServicoType), nullable=False, default=ServicoType.PONTO)
    modalidade_type = db.Column(db.Enum(ModalidadeType), nullable=False, default=ModalidadeType.AQUISICAO)

    enviar_email = db.Column(db.Boolean, default=False)
    email_corpo = db.Column(db.Text)
    email_cc = db.Column(db.Text)

    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    usuario_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    filename = db.Column(db.String(128))

    sistema_ativo = db.Column(db.Boolean, default=False)
    sistema_nome = db.Column(db.String(128))
    sistema_descricao = db.Column(db.Text)
    sistema_imagem = db.Column(db.String(256))
    sistema_quantidade = db.Column(db.Integer)
    sistema_preco_unitario = db.Column(db.Float)
    sistema_preco_total = db.Column(db.Float)
    sistema_preco_fixo = db.Column(db.Boolean, default=False, nullable=False)
    locacao_valor_mensal = db.Column(db.Float)
    locacao_vigencia = db.Column(db.String(128))
    locacao_qtd_pessoas = db.Column(db.Integer)
    locacao_qtd_cnpjs = db.Column(db.Integer)
    locacao_qtd_equipamentos = db.Column(db.Integer)
    locacao_modelo = db.Column(db.String(32), default="sintetico")
    rep_categoria_programa = db.Column(db.Boolean, default=False, nullable=False)
    rep_tem_mobile = db.Column(db.Boolean, default=False, nullable=False)
    rep_qtd_mobile = db.Column(db.Integer)
    rep_mobile_valor_mensal = db.Column(db.Float)
    original_proposal_id = db.Column(db.Integer, db.ForeignKey("proposals.id"))
    version_number = db.Column(db.Integer, default=1, nullable=False)
    is_current = db.Column(db.Boolean, default=True, nullable=False)
    is_original = db.Column(db.Boolean, default=True, nullable=False)
    approved_at = db.Column(db.DateTime)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    equipamentos_payload = db.Column(db.JSON)

    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    created_by_id = synonym("usuario_id")
    created_by = synonym("usuario")

    equipamentos = db.relationship(
        "Equipment",
        secondary=proposal_equipments,
        backref="propostas",
        lazy="dynamic",
    )




class PdfJob(db.Model):
    __tablename__ = "pdf_jobs"

    id = db.Column(db.String(32), primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposals.id'), nullable=True)
    action = db.Column(db.String(32), nullable=False)
    download_name = db.Column(db.String(256), nullable=False)
    status = db.Column(db.String(32), nullable=False, default='queued')
    error = db.Column(db.Text)
    file_path = db.Column(db.String(512))
    file_size = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    generated_at = db.Column(db.DateTime)
    payload = db.Column(db.JSON, default=dict)

    owner = db.relationship('User', backref=db.backref('pdf_jobs', lazy='dynamic'))
    proposal = db.relationship('Proposal', backref=db.backref('pdf_jobs', lazy='dynamic'))

class SystemOptionCatalog(db.Model):
    __tablename__ = "system_options"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    label = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    image_path = db.Column(db.String(256))
    default_quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Float, nullable=False, default=0.0)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemOptionState(db.Model):
    __tablename__ = "system_option_states"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemOptionOverride(db.Model):
    __tablename__ = "system_option_overrides"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.Text)
    image_path = db.Column(db.String(256))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SoftwarePlan(db.Model):
    """Catálogo de Sistemas, Softwares, Licenças SaaS, Planos Recorrentes e Adicionais."""
    __tablename__ = "software_plans"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    codigo = db.Column(db.String(50), nullable=True)
    fabricante = db.Column(db.String(100), nullable=False, default="Outros", index=True)
    categoria = db.Column(db.String(50), nullable=False, default="Ponto", index=True)  # Ponto, Acesso, Gestão / Armários, Outros
    tipo_item = db.Column(db.String(50), nullable=False, default="Plano Principal")  # Plano Principal, Adicional de Funcionários, Adicional de Equipamento, Módulo Extra, Hospedagem / Nuvem, Aplicativo Mobile
    faixa_funcionarios = db.Column(db.String(100), nullable=True)
    qtd_funcionarios_max = db.Column(db.Integer, nullable=True)
    qtd_equipamentos = db.Column(db.Integer, nullable=True, default=1)
    qtd_cnpjs = db.Column(db.Integer, nullable=True, default=1)
    suporte_incluso = db.Column(db.String(80), nullable=True)  # Com suporte, Sem suporte, 90 dias
    vigencia = db.Column(db.String(50), nullable=True, default="12 meses")
    valor_mensal = db.Column(db.Float, nullable=False, default=0.0)
    valor_implantacao = db.Column(db.Float, nullable=True)
    preco_anterior = db.Column(db.Float, nullable=True)
    preco_alterado_em = db.Column(db.DateTime, nullable=True)
    preco_alterado_por = db.Column(db.String(120), nullable=True)
    description = db.Column(db.Text, nullable=True)
    illustration_path = db.Column(db.String(256), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "codigo": self.codigo or "",
            "fabricante": self.fabricante,
            "categoria": self.categoria,
            "tipo_item": self.tipo_item,
            "faixa_funcionarios": self.faixa_funcionarios or "",
            "qtd_funcionarios_max": self.qtd_funcionarios_max,
            "qtd_equipamentos": self.qtd_equipamentos or 1,
            "qtd_cnpjs": self.qtd_cnpjs or 1,
            "suporte_incluso": self.suporte_incluso or "",
            "vigencia": self.vigencia or "",
            "valor_mensal": self.valor_mensal,
            "valor_mensal_formatado": f"R$ {self.valor_mensal:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "valor_implantacao": self.valor_implantacao,
            "valor_implantacao_formatado": f"R$ {self.valor_implantacao:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if self.valor_implantacao else None,
            "preco_anterior": self.preco_anterior,
            "preco_anterior_formatado": f"R$ {self.preco_anterior:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if self.preco_anterior else None,
            "description": self.description or "",
            "illustration_path": self.illustration_path or "",
            "is_active": self.is_active,
        }





class Birthday(db.Model):
    """Armazena aniversariantes do painel administrativo."""

    __tablename__ = "aniversariantes"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    data_nascimento = db.Column(db.Date, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - auxlio debug
        return f"<Birthday {self.nome!r}>"

    @property
    def dia(self) -> int | None:
        return self.data_nascimento.day if self.data_nascimento else None

    @property
    def mes(self) -> int | None:
        return self.data_nascimento.month if self.data_nascimento else None

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "nome": self.nome,
            "data_nascimento": self.data_nascimento.isoformat() if self.data_nascimento else None,
        }


class VacationEntry(db.Model):
    """Mapa de férias anuais dos colaboradores."""

    __tablename__ = "ferias"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.String(255), nullable=False)
    data_inicial = db.Column(db.Date, nullable=False)
    data_final = db.Column(db.Date, nullable=False)
    referente_ano = db.Column(db.Integer, nullable=False)
    unidade = db.Column(db.String(64), nullable=False)

    @property
    def duration_days(self) -> int:
        return (self.data_final - self.data_inicial).days + 1 if self.data_final and self.data_inicial else 0


class AgendaEntry(db.Model):
    """Programação de agenda externa dos técnicos."""

    __tablename__ = "agenda"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    unidade = db.Column(db.String(64), nullable=False)
    data_atendimento = db.Column(db.Date, nullable=False)
    periodo = db.Column(db.String(20), nullable=False)
    obs = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tecnico = db.relationship("User", backref=db.backref("agenda_entries", lazy="dynamic"))

    def to_event_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "usuario_id": self.usuario_id,
            "tecnico": self.tecnico.nome_completo if self.tecnico else None,
            "unidade": self.unidade,
            "periodo": self.periodo,
            "obs": self.obs or "",
            "data_atendimento": self.data_atendimento.isoformat(),
        }


class CommercialAgendaEntry(db.Model):
    """Programação de agenda dos consultores comerciais."""

    __tablename__ = "agenda_comercial"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    tipo_compromisso = db.Column(db.String(32), nullable=False, default="visita")  # visita, demonstracao, reuniao_interna, atividade_externa, ferias, disponivel, outro
    cliente = db.Column(db.String(150))
    local = db.Column(db.String(150))
    data_inicio = db.Column(db.Date, nullable=False, index=True)
    data_fim = db.Column(db.Date)
    periodo = db.Column(db.String(32), nullable=False, default="Dia todo")  # Manhã, Tarde, Dia todo ou horário customizado
    status = db.Column(db.String(20), nullable=False, default="agendado")  # agendado, realizado, cancelado
    observacoes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    consultor = db.relationship("User", backref=db.backref("commercial_agenda_entries", lazy="dynamic"))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "usuario_id": self.usuario_id,
            "consultor_nome": self.consultor.nome_completo if self.consultor else f"Usuário {self.usuario_id}",
            "tipo_compromisso": self.tipo_compromisso,
            "cliente": self.cliente or "",
            "local": self.local or "",
            "data_inicio": self.data_inicio.isoformat() if self.data_inicio else None,
            "data_fim": self.data_fim.isoformat() if self.data_fim else None,
            "periodo": self.periodo or "Dia todo",
            "status": self.status,
            "observacoes": self.observacoes or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EmpresaParceira(db.Model):
    """Cadastro de empresas parceiras / terceirizadas de instalação e manutenção."""

    __tablename__ = "empresas_parceiras"

    id = db.Column(db.Integer, primary_key=True)
    razao_social = db.Column(db.String(150), nullable=False)
    nome_fantasia = db.Column(db.String(150))
    cnpj = db.Column(db.String(20))
    responsavel = db.Column(db.String(100))
    telefone = db.Column(db.String(40))
    whatsapp = db.Column(db.String(40))
    email = db.Column(db.String(120))
    estado = db.Column(db.String(2), nullable=False, index=True)
    cidade = db.Column(db.String(100), nullable=False, index=True)
    regiao_atendimento = db.Column(db.Text)
    especialidades = db.Column(db.Text)  # Ex: Catracas, Relógio de Ponto, Henry, Control iD
    status = db.Column(db.String(20), nullable=False, default="ativo")  # ativo, em_homologacao, inativo
    avaliacao_media = db.Column(db.Float, default=0.0)
    total_atendimentos = db.Column(db.Integer, default=0)
    observacoes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    servicos = db.relationship(
        "ParceiroServicoHistorico",
        backref="parceiro",
        cascade="all, delete-orphan",
        order_by="desc(ParceiroServicoHistorico.data_servico)",
        lazy="dynamic",
    )

    def recalcular_avaliacao(self):
        notas = [s.avaliacao_nota for s in self.servicos.all() if s.avaliacao_nota is not None]
        if notas:
            self.avaliacao_media = round(sum(notas) / len(notas), 1)
            self.total_atendimentos = len(notas)
        else:
            self.avaliacao_media = 0.0
            self.total_atendimentos = 0


class ParceiroServicoHistorico(db.Model):
    """Histórico de serviços e instalações executados por empresas parceiras para a Sollus."""

    __tablename__ = "parceiros_servicos_historico"

    id = db.Column(db.Integer, primary_key=True)
    parceiro_id = db.Column(
        db.Integer,
        db.ForeignKey("empresas_parceiras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cliente_nome = db.Column(db.String(150), nullable=False)
    cliente_cidade = db.Column(db.String(100))
    cliente_uf = db.Column(db.String(2))
    data_servico = db.Column(db.Date, nullable=False, index=True)
    tipo_servico = db.Column(db.String(100), nullable=False)  # Instalação, Manutenção, Treinamento, Troca de Peças
    equipamento_modelo = db.Column(db.String(100))
    os_codigo = db.Column(db.String(50))
    tecnico_parceiro = db.Column(db.String(100))
    valor_servico = db.Column(db.Numeric(10, 2))
    avaliacao_nota = db.Column(db.Integer)  # 1 a 5 estrelas
    avaliacao_parecer = db.Column(db.Text)
    usuario_registro_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    usuario_registro = db.relationship("User", foreign_keys=[usuario_registro_id])

