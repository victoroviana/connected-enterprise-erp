
"""Database compatibility helpers."""
from __future__ import annotations

from contextlib import suppress
import os

from flask import current_app, has_app_context
from sqlalchemy import inspect, text, or_
from sqlalchemy.exc import OperationalError

from extensions import db

from modules.propostas.models import (
    AgendaEntry,
    Birthday,
    Department,
    PdfJob,
    RolePermission,
    User,
    VacationEntry,
    default_permissions,
    user_departments,
)

USER_COLUMNS: dict[str, str] = {
    "signature_path": "ALTER TABLE users ADD COLUMN signature_path VARCHAR(256)",
    "avatar_path": "ALTER TABLE users ADD COLUMN avatar_path VARCHAR(256)",
    "phone_extra": "ALTER TABLE users ADD COLUMN phone_extra TEXT",
}

LEGACY_PROPOSAL_COLUMNS: dict[str, str] = {
    "enviar_email": "ALTER TABLE proposals ADD COLUMN enviar_email BOOLEAN NOT NULL DEFAULT 0",
    "email_corpo": "ALTER TABLE proposals ADD COLUMN email_corpo TEXT NOT NULL DEFAULT ''",
    "email_cc": "ALTER TABLE proposals ADD COLUMN email_cc TEXT NOT NULL DEFAULT ''",
    "sistema_ativo": "ALTER TABLE proposals ADD COLUMN sistema_ativo BOOLEAN NOT NULL DEFAULT 0",
    "sistema_nome": "ALTER TABLE proposals ADD COLUMN sistema_nome VARCHAR(128)",
    "sistema_descricao": "ALTER TABLE proposals ADD COLUMN sistema_descricao TEXT",
    "sistema_imagem": "ALTER TABLE proposals ADD COLUMN sistema_imagem VARCHAR(256)",
    "sistema_quantidade": "ALTER TABLE proposals ADD COLUMN sistema_quantidade INTEGER",
    "sistema_preco_unitario": "ALTER TABLE proposals ADD COLUMN sistema_preco_unitario FLOAT",
    "sistema_preco_total": "ALTER TABLE proposals ADD COLUMN sistema_preco_total FLOAT",
    "locacao_valor_mensal": "ALTER TABLE proposals ADD COLUMN locacao_valor_mensal FLOAT",
    "locacao_vigencia": "ALTER TABLE proposals ADD COLUMN locacao_vigencia VARCHAR(128)",
    "locacao_qtd_pessoas": "ALTER TABLE proposals ADD COLUMN locacao_qtd_pessoas INTEGER",
    "locacao_qtd_cnpjs": "ALTER TABLE proposals ADD COLUMN locacao_qtd_cnpjs INTEGER",
    "locacao_qtd_equipamentos": "ALTER TABLE proposals ADD COLUMN locacao_qtd_equipamentos INTEGER",
    "locacao_modelo": "ALTER TABLE proposals ADD COLUMN locacao_modelo VARCHAR(32)",
    "observacao_comercial": "ALTER TABLE proposals ADD COLUMN observacao_comercial TEXT",
    "ambiente_incluir": "ALTER TABLE proposals ADD COLUMN ambiente_incluir BOOLEAN NOT NULL DEFAULT 0",
    "ambiente_fotos": "ALTER TABLE proposals ADD COLUMN ambiente_fotos JSON",
    "rep_tem_mobile": "ALTER TABLE proposals ADD COLUMN rep_tem_mobile BOOLEAN NOT NULL DEFAULT 0",
    "rep_qtd_mobile": "ALTER TABLE proposals ADD COLUMN rep_qtd_mobile INTEGER",
    "rep_mobile_valor_mensal": "ALTER TABLE proposals ADD COLUMN rep_mobile_valor_mensal FLOAT",
    "original_proposal_id": "ALTER TABLE proposals ADD COLUMN original_proposal_id INTEGER",
    "version_number": "ALTER TABLE proposals ADD COLUMN version_number INTEGER NOT NULL DEFAULT 1",
    "is_current": "ALTER TABLE proposals ADD COLUMN is_current BOOLEAN NOT NULL DEFAULT 1",
    "is_original": "ALTER TABLE proposals ADD COLUMN is_original BOOLEAN NOT NULL DEFAULT 1",
    "approved_at": "ALTER TABLE proposals ADD COLUMN approved_at DATETIME",
    "approved_by_id": "ALTER TABLE proposals ADD COLUMN approved_by_id INTEGER",
    "equipamentos_payload": "ALTER TABLE proposals ADD COLUMN equipamentos_payload JSON",
}


def ensure_proposal_email_columns() -> None:
    """Ensure legacy databases have the proposal columns required by the app."""

    engine = db.engine
    inspector = inspect(engine)

    if "proposals" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("proposals")}

    missing_columns = [
        (name, statement)
        for name, statement in LEGACY_PROPOSAL_COLUMNS.items()
        if name not in existing_columns
    ]

    if not missing_columns:
        return

    with engine.begin() as connection:
        for _, statement in missing_columns:
            with suppress(OperationalError):
                connection.execute(text(statement))

    refreshed_columns = {
        column_info["name"]
        for column_info in inspect(engine).get_columns("proposals")
    }
    created = [
        name
        for name, _ in missing_columns
        if name in refreshed_columns
    ]

    if created and has_app_context():
        current_app.logger.info(
            "Garantidas colunas na tabela proposals: %s",
            ", ".join(sorted(created)),
        )

def ensure_user_signature_column() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("users")}
    missing = [statement for name, statement in USER_COLUMNS.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        for statement in missing:
            with suppress(OperationalError):
                connection.execute(text(statement))




def ensure_role_permissions() -> None:
    """Create default role permission entries if missing."""
    RolePermission.__table__.create(bind=db.engine, checkfirst=True)

    base_permissions = default_permissions()
    consultor_permissions = {key: False for key in base_permissions}
    consultor_permissions["propostas"] = True

    defaults = [
        {
            "name": "admin",
            "label": "Administrador",
            "permissions": {
                "propostas": True,
                "chamados": True,
                "central_conhecimento": True,
                "admin": True,
                "usuarios_acesso": True,
                "usuarios_gerenciar": True,
                "permissoes_gerenciar": True,
            },
        },
        {
            "name": "gestor",
            "label": "Gestor",
            "permissions": {
                "propostas": True,
                "chamados": True,
                "central_conhecimento": True,
                "admin": False,
                "usuarios_acesso": True,
                "usuarios_gerenciar": True,
                "permissoes_gerenciar": False,
            },
        },
        {
            "name": "consultor",
            "label": "Consultor",
            "permissions": consultor_permissions,
        },
        {
            "name": "usuario",
            "label": "Usuário",
            "permissions": {
                "propostas": True,
                "chamados": False,
                "central_conhecimento": False,
                "admin": False,
                "usuarios_acesso": False,
                "usuarios_gerenciar": False,
                "permissoes_gerenciar": False,
            },
        },
        {
            "name": "rh",
            "label": "RH",
            "permissions": {
                "propostas": True,
                "chamados": False,
                "central_conhecimento": False,
                "admin": False,
                "usuarios_acesso": False,
                "usuarios_gerenciar": False,
                "permissoes_gerenciar": False,
                "admin_ferias": True,
                "admin_galeria": True,
            },
        },
    ]

    changed = False
    for entry in defaults:
        role = RolePermission.query.filter_by(name=entry["name"]).first()
        if not role:
            role = RolePermission(**entry)
            db.session.add(role)
            changed = True
    if changed:
        db.session.commit()

    rh_role = RolePermission.query.filter_by(name="rh").first()
    if rh_role:
        perms = dict(rh_role.permissions or {})
        updated = False
        if not perms.get("admin_ferias"):
            perms["admin_ferias"] = True
            updated = True
        if not perms.get("admin_galeria"):
            perms["admin_galeria"] = True
            updated = True
        if updated:
            rh_role.permissions = perms
            db.session.commit()

    consultor_role = RolePermission.query.filter_by(name="consultor").first()
    if consultor_role:
        perms = dict(consultor_role.permissions or {})
        updated = False
        for key, value in consultor_permissions.items():
            if perms.get(key) != value:
                perms[key] = value
                updated = True
        if updated:
            consultor_role.permissions = perms
            db.session.commit()

        with suppress(Exception):
            users = User.query.filter(User.tipo == "consultor").all()
            changed_users = False
            for user in users:
                if user.permissions != consultor_permissions:
                    user.permissions = consultor_permissions
                    changed_users = True
            if changed_users:
                db.session.commit()


def ensure_user_permissions_column() -> None:
    """Guarantee the permissions JSON column exists and is populated."""
    engine = db.engine
    inspector = inspect(engine)

    if "users" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("users")}
    if "permissions" in existing:
        return

    dialect = engine.dialect.name
    if dialect == "sqlite":
        column_sql = "ALTER TABLE users ADD COLUMN permissions JSON"
    elif dialect in {"mysql", "mariadb"}:
        column_sql = "ALTER TABLE users ADD COLUMN permissions JSON"
    elif dialect == "postgresql":
        column_sql = "ALTER TABLE users ADD COLUMN permissions JSON"
    else:
        column_sql = "ALTER TABLE users ADD COLUMN permissions JSON"

    with engine.begin() as connection:
        with suppress(OperationalError):
            connection.execute(text(column_sql))

    try:
        from modules.propostas.models import User, default_permissions  # type: ignore circular import
    except Exception:
        return

    try:
        defaults = default_permissions()
    except Exception:
        defaults = {
            "propostas": True,
            "chamados": True,
            "central_conhecimento": True,
            "admin": False,
        }

    session = db.session
    with suppress(Exception):
        users = session.query(User).all()
        changed = False
        for user in users:
            perms = dict(user.permissions or {})
            updated = False
            for key, value in defaults.items():
                if key not in perms:
                    perms[key] = value
                    updated = True
            if updated or not user.permissions:
                user.permissions = perms
                changed = True
        if changed:
            session.commit()




def ensure_user_departments_table() -> None:
    """Criar tabela user_departments e migrar departamentos existentes."""
    try:
        user_departments.create(bind=db.engine, checkfirst=True)
    except Exception:
        return

    with suppress(Exception):
        users = User.query.filter(User.department_id.isnot(None)).all()
        changed = False
        for user in users:
            if not user.department_id:
                continue
            dept = Department.query.get(user.department_id)
            if not dept:
                continue
            if dept not in (user.departments or []):
                user.departments.append(dept)
                changed = True
        if changed:
            db.session.commit()


def ensure_pdf_jobs_table() -> None:
    """Garantir a existência da tabela de jobs de PDF."""
    PdfJob.__table__.create(bind=db.engine, checkfirst=True)



def ensure_rh_department() -> None:
    """Garantir que o departamento RH exista com permissoes de galeria e ferias."""
    Department.__table__.create(bind=db.engine, checkfirst=True)

    dept = Department.query.filter_by(slug="rh").first()
    base_permissions = default_permissions()
    base_permissions["admin_galeria"] = True
    base_permissions["admin_ferias"] = True

    if not dept:
        dept = Department(name="RH", slug="rh", permissions=base_permissions)
        db.session.add(dept)
        db.session.commit()
        return

    perms = dept.to_permissions()
    updated = False
    if not perms.get("admin_galeria"):
        perms["admin_galeria"] = True
        updated = True
    if not perms.get("admin_ferias"):
        perms["admin_ferias"] = True
        updated = True
    if updated:
        dept.permissions = perms
        db.session.commit()


def ensure_cracha_department() -> None:
    """Garantir que o departamento Crachá exista."""
    Department.__table__.create(bind=db.engine, checkfirst=True)
    dept = Department.query.filter_by(slug="cracha").first()
    base_perms = default_permissions()
    base_perms["cracha"] = True
    if not dept:
        dept = Department(name="Crachá", slug="cracha", permissions=base_perms)
        db.session.add(dept)
        db.session.commit()
        return

    perms = dept.to_permissions()
    if not perms.get("cracha"):
        perms["cracha"] = True
        dept.permissions = perms
        db.session.commit()


def ensure_admin_tools_tables() -> None:
    """Criar tabelas auxiliares utilizadas no painel de administração."""

    if os.getenv("SKIP_ADMIN_TABLE_ENSURE"):
        return

    created: list[str] = []
    for model in (Birthday, VacationEntry, AgendaEntry):
        try:
            model.__table__.create(bind=db.engine, checkfirst=True)
        except Exception:
            continue
        else:
            created.append(model.__tablename__)

    if created and has_app_context():
        current_app.logger.info(
            "Tabelas administrativas garantidas: %s",
            ", ".join(sorted(set(created))),
        )


def ensure_assistencia_orcamentos_table() -> None:
    """Garantir tabelas de orcamentos da assistencia tecnica."""
    try:
        from modules.suporte.models import AssistenciaEquipamentoProposta, AssistenciaOrcamento, OrcamentoStatus  # type: ignore
    except Exception:
        return

    for model in (AssistenciaOrcamento, OrcamentoStatus, AssistenciaEquipamentoProposta):
        try:
            model.__table__.create(bind=db.engine, checkfirst=True)
        except Exception:
            continue


def ensure_central_conhecimento_task_columns() -> None:
    """Garantir colunas extras do Central de Conhecimento na tabela tasks."""
    engine = db.engine
    inspector = inspect(engine)
    try:
        from modules.chamados.models import CentralConhecimentoColumn  # type: ignore
    except Exception:
        CentralConhecimentoColumn = None
    if "tasks" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("tasks")}
    statements = []
    if "scope_key" not in existing:
        statements.append("ALTER TABLE tasks ADD COLUMN scope_key VARCHAR(64)")
    if "visibility" not in existing:
        statements.append("ALTER TABLE tasks ADD COLUMN visibility VARCHAR(16) NOT NULL DEFAULT 'public'")
    if "author_id" not in existing:
        statements.append("ALTER TABLE tasks ADD COLUMN author_id INTEGER")
    if "column_id" not in existing:
        statements.append("ALTER TABLE tasks ADD COLUMN column_id INTEGER")

    if statements:
        with engine.begin() as connection:
            for statement in statements:
                with suppress(OperationalError):
                    connection.execute(text(statement))

    if CentralConhecimentoColumn is not None:
        with suppress(Exception):
            CentralConhecimentoColumn.__table__.create(bind=db.engine, checkfirst=True)

    refreshed = {column["name"] for column in inspect(engine).get_columns("tasks")}
    with engine.begin() as connection:
        if "scope_key" in refreshed:
            with suppress(OperationalError):
                connection.execute(
                    text("UPDATE tasks SET scope_key = 'chamados' WHERE scope_key IS NULL OR scope_key = ''")
                )
        if "visibility" in refreshed:
            with suppress(OperationalError):
                connection.execute(
                    text("UPDATE tasks SET visibility = 'public' WHERE visibility IS NULL OR visibility = ''")
                )
        if "author_id" in refreshed:
            with suppress(OperationalError):
                connection.execute(
                    text("UPDATE tasks SET author_id = assignee_id WHERE author_id IS NULL AND assignee_id IS NOT NULL")
                )


def ensure_central_conhecimento_comment_tables() -> None:
    """Ensure tables used for Central de Conhecimento task comments exist."""
    try:
        from modules.chamados.models import TaskComment, TaskCommentAttachment  # type: ignore
    except Exception:
        return
    try:
        TaskComment.__table__.create(bind=db.engine, checkfirst=True)
        TaskCommentAttachment.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        return

def ensure_parts_table() -> None:
    """Garantir a existência da tabela de peças para orçamentos."""
    try:
        from modules.propostas.models import Part
        Part.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        pass
