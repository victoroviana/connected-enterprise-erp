
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


from modules.chamados.models import Ticket, TicketMessage, Task
PERMISSION_DEFINITIONS: dict[str, dict[str, object]] = {
    "propostas": {"label": "Comercial", "default": True},
    "estoque": {"label": "Estoque", "default": False},
    "chamados": {"label": "Sollus Tickets", "default": True},
    "central_conhecimento": {"label": "Central de Conhecimento", "default": True},
    "admin": {"label": "Administração", "default": False},
    "usuarios_acesso": {"label": "Usuários", "default": False},
    "usuarios_gerenciar": {"label": "Usuários (gerenciar)", "default": False},
    "permissoes_gerenciar": {"label": "Permissões", "default": False},
    "admin_aniversariantes": {"label": "Aniversariantes", "default": False},
    "admin_ferias": {"label": "Mapa de Férias", "default": False},
    "admin_agenda_tecnica": {"label": "Agenda técnica", "default": False},
    "admin_suporte": {"label": "Suporte", "default": False},
    "admin_assistencia": {"label": "Assistência técnica", "default": False},
    "admin_galeria": {"label": "Galeria", "default": False},
    "financeiro": {"label": "Financeiro", "default": False},
    "financeiro_contas": {"label": "Financeiro - Contas a receber", "default": False},
    "financeiro_cancelados": {"label": "Financeiro - Cancelados", "default": False},
    "financeiro_cota": {"label": "Financeiro - Cota mensal", "default": False},
    "contratos": {"label": "Contratos", "default": False},
    "cracha": {"label": "Crachá", "default": False},
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
    tasks = db.relationship(
        "Task",
        foreign_keys="Task.assignee_id",
        back_populates="assignee",
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




class Birthday(db.Model):
    """Armazena aniversariantes do painel administrativo."""

    __tablename__ = "aniversariantes"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    data_nascimento = db.Column(db.Date, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - auxlio debug
        return f"<Birthday {self.nome!r}>"

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "nome": self.nome,
            "data_nascimento": self.data_nascimento.isoformat(),
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
