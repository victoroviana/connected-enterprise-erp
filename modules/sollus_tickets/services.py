"""Business services for Sollus Tickets."""
from __future__ import annotations

import mimetypes
import re
import secrets
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from flask import current_app, render_template, request, url_for
from sqlalchemy import inspect, text
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from extensions import db
from modules.propostas.models import User

from .models import (
    SollusTicket,
    SollusTicketAttachment,
    SollusTicketCannedResponse,
    SollusTicketDepartment,
    SollusTicketDepartmentAccess,
    SollusTicketEvent,
    SollusTicketFieldValue,
    SollusTicketFormField,
    SollusTicketMailbox,
    SollusTicketPriority,
    SollusTicketQueue,
    SollusTicketRolePermission,
    SollusTicketSLA,
    SollusTicketStatus,
    SollusTicketSystemLog,
    SollusTicketTeam,
    SollusTicketTeamMember,
    SollusTicketThreadEntry,
    SollusTicketTopic,
)


DEFAULT_STATUSES = (
    ("open", "Aberto", "open", False, 10),
    ("in_progress", "Em andamento", "open", False, 20),
    ("waiting_user", "Aguardando cliente", "open", False, 30),
    ("resolved", "Resolvido", "closed", True, 90),
    ("closed", "Fechado", "closed", True, 100),
)

DEFAULT_PRIORITIES = (
    ("low", "Baixa", 1, "#94a3b8"),
    ("normal", "Normal", 2, "#0F7BC8"),
    ("high", "Alta", 3, "#e11d48"),
    ("emergency", "Emergencia", 4, "#111827"),
)

DEFAULT_ROLE_PERMISSIONS = {
    "admin": dict(can_view_all=True, can_assign=True, can_manage_admin=True, can_close=True, can_reopen=True, can_internal_note=True, can_transfer=True, can_delete=True, can_merge=True, can_link=True, can_manage_tasks=True, can_manage_queues=True, limit_access=False),
    "gestor": dict(can_view_all=True, can_assign=True, can_manage_admin=True, can_close=True, can_reopen=True, can_internal_note=True, can_transfer=True, can_delete=True, can_merge=True, can_link=True, can_manage_tasks=True, can_manage_queues=True, limit_access=False),
    "agent": dict(can_view_all=True, can_assign=True, can_manage_admin=False, can_close=True, can_reopen=True, can_internal_note=True, can_transfer=True, can_delete=False, can_merge=True, can_link=True, can_manage_tasks=True, can_manage_queues=False, limit_access=False),
    "usuario": dict(can_view_all=False, can_assign=False, can_manage_admin=False, can_close=False, can_reopen=True, can_internal_note=False, can_transfer=False, can_delete=False, can_merge=False, can_link=False, can_manage_tasks=False, can_manage_queues=False, limit_access=False),
}

_ALLOWED_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".pdf", ".txt", ".log", ".csv",
    ".doc", ".docx", ".xls", ".xlsx",
}


def slugify(value: str, fallback: str = "item") -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or fallback


def ensure_sollus_ticket_tables() -> None:
    """Create all module tables and seed baseline values."""
    if current_app.config.get("TESTING") or db.engine.dialect.name == "sqlite":
        return
    from .models import (
        SollusTicketCollaborator,
        SollusTicketContact,
        SollusTicketImportRun,
        SollusTicketMailbox,
        SollusTicketProcessedEmail,
        SollusTicketDepartmentAccess,
        SollusTicketBanlist,
        SollusTicketFilterRule,
        SollusTicketEmailTemplateGroup,
        SollusTicketEmailTemplate,
        SollusTicketCustomQueueColumn,
        SollusTicketCustomQueueSort,
        SollusTicketRelation,
        SollusTicketLock,
        SollusTicketTask,
        SollusTicketTaskEntry,
        SollusTicketTeamMember,
        SollusEmailQueue
    )

    # 1. Sync Departments from platform
    from modules.propostas.models import Department
    for dept in Department.query.all():
        slug = dept.slug
        sollus_dept = SollusTicketDepartment.query.filter_by(slug=slug).first()
        if not sollus_dept:
            sollus_dept = SollusTicketDepartment(
                name=dept.name,
                slug=slug,
                is_active=True,
                auto_assign_enabled=True
            )
            db.session.add(sollus_dept)
    db.session.commit()

    # 2. Create tables
    models = [
        SollusTicketDepartment, SollusTicketTeam, SollusTicketQueue, SollusTicketSLA,
        SollusTicketTopic, SollusTicketStatus, SollusTicketPriority, SollusTicketRolePermission,
        SollusTicketContact, SollusTicket, SollusTicketThreadEntry, SollusTicketAttachment,
        SollusTicketCollaborator, SollusTicketFieldValue, SollusTicketEvent,
        SollusTicketCannedResponse, SollusTicketMailbox, SollusTicketProcessedEmail,
        SollusTicketDepartmentAccess, SollusTicketBanlist, SollusTicketFilterRule,
        SollusTicketEmailTemplateGroup, SollusTicketEmailTemplate, SollusTicketImportRun,
        SollusTicketFormField, SollusTicketCustomQueueColumn, SollusTicketCustomQueueSort,
        SollusTicketRelation, SollusTicketLock, SollusTicketSystemLog, SollusTicketTask,
        SollusTicketTaskEntry, SollusTicketTeamMember, SollusEmailQueue
    ]
    for model in models:
        model.__table__.create(db.engine, checkfirst=True)

    _ensure_ticket_columns()

    # 3. Baseline seeding
    changed = False
    if not SollusTicketStatus.query.first():
        for key, label, state, is_closed, sort in DEFAULT_STATUSES:
            db.session.add(SollusTicketStatus(key=key, label=label, state=state, is_closed=is_closed, sort_order=sort))
        changed = True
    
    if not SollusTicketPriority.query.first():
        for key, label, level, color in DEFAULT_PRIORITIES:
            db.session.add(SollusTicketPriority(key=key, label=label, level=level, color=color))
        changed = True
    else:
        # Garante que as prioridades existentes estejam em PT-BR
        pt_br_priority_labels = {
            "low": "Baixa",
            "normal": "Normal",
            "high": "Alta",
            "emergency": "Emergência"
        }
        for key, label in pt_br_priority_labels.items():
            row = SollusTicketPriority.query.filter_by(key=key).first()
            if row and row.label != label:
                row.label = label
                changed = True

    if not SollusTicketSLA.query.first():
        db.session.add(SollusTicketSLA(name="Padrao 48h", slug="padrao-48h", grace_period_hours=48))
        changed = True

    if not SollusTicketDepartment.query.first():
        db.session.add(
            SollusTicketDepartment(
                name="Suporte",
                slug="suporte",
                is_active=True,
                auto_assign_enabled=False,
            )
        )
        changed = True

    if not SollusTicketQueue.query.first():
        dept = SollusTicketDepartment.query.first()
        db.session.add(
            SollusTicketQueue(
                name="Fila Geral",
                slug="fila-geral",
                department_id=dept.id if dept else None,
                sort_order=10,
            )
        )
        changed = True

    for role, flags in DEFAULT_ROLE_PERMISSIONS.items():
        row = SollusTicketRolePermission.query.filter_by(role_key=role).first()
        if row:
            if _fill_missing_permission_flags(row, flags):
                changed = True
            continue
        db.session.add(SollusTicketRolePermission(role_key=role, **flags))
        changed = True

    if not SollusTicketEmailTemplateGroup.query.first():
        group = SollusTicketEmailTemplateGroup(name="Padrao", slug="padrao", is_active=True)
        db.session.add(group)
        db.session.flush()
        for event_key, subject, body in DEFAULT_EMAIL_TEMPLATES:
            db.session.add(
                SollusTicketEmailTemplate(
                    group_id=group.id,
                    event_key=event_key,
                    subject=subject,
                    body_html=body,
                    body_text=re.sub(r"<[^>]+>", "", body),
                )
            )
        changed = True

    if changed:
        db.session.commit()


DEFAULT_EMAIL_TEMPLATES = (
    ("created", "[Sollus Tickets {ticket_number}] Ticket criado - {ticket_subject}", "<p>Ticket <strong>{ticket_number}</strong> criado.</p><p>{body}</p><p><a href=\"{ticket_url}\">Abrir ticket</a></p>"),
    ("reply", "[Sollus Tickets {ticket_number}] Nova resposta - {ticket_subject}", "<p>Nova resposta no ticket <strong>{ticket_number}</strong>.</p><p>{body}</p><p><a href=\"{ticket_url}\">Abrir ticket</a></p>"),
    ("assign", "[Sollus Tickets {ticket_number}] Ticket atribuído - {ticket_subject}", "<p>Ticket <strong>{ticket_number}</strong> atribuído.</p><p><a href=\"{ticket_url}\">Abrir ticket</a></p>"),
    ("status", "[Sollus Tickets {ticket_number}] Status atualizado - {ticket_subject}", "<p>Status atualizado no ticket <strong>{ticket_number}</strong>.</p><p>{body}</p>"),
    ("closed", "[Sollus Tickets {ticket_number}] Ticket fechado - {ticket_subject}", "<p>Ticket <strong>{ticket_number}</strong> fechado.</p><p>{body}</p>"),
    ("reopened", "[Sollus Tickets {ticket_number}] Ticket reaberto - {ticket_subject}", "<p>Ticket <strong>{ticket_number}</strong> reaberto.</p><p>{body}</p>"),
    ("overdue", "[Sollus Tickets {ticket_number}] Ticket em atraso - {ticket_subject}", "<p>Ticket <strong>{ticket_number}</strong> está em atraso.</p>"),
)


def _fill_missing_permission_flags(row: SollusTicketRolePermission, flags: dict) -> bool:
    changed = False
    for field, value in flags.items():
        if getattr(row, field, None) is None:
            setattr(row, field, value)
            changed = True
    return changed


def _ensure_ticket_columns() -> None:
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    if "sollus_tickets" not in tables:
        return
    existing = {column["name"] for column in inspector.get_columns("sollus_tickets")}
    column_defs = {
        "queue_id": "INTEGER",
        "team_id": "INTEGER",
        "sla_id": "INTEGER",
        "overdue_at": "DATETIME",
        "resolved_at": "DATETIME",
        "reopened_at": "DATETIME",
        "reopen_count": "INTEGER NOT NULL DEFAULT 0",
        "close_reason": "TEXT",
    }
    dialect = db.engine.dialect.name
    with db.engine.begin() as connection:
        for column, definition in column_defs.items():
            if column in existing:
                continue
            if dialect in {"mysql", "mariadb"}:
                statement = f"ALTER TABLE sollus_tickets ADD COLUMN {column} {definition}"
            else:
                statement = f"ALTER TABLE sollus_tickets ADD COLUMN {column} {definition}"
            try:
                connection.execute(text(statement))
            except Exception:
                    current_app.logger.exception("Nao foi possivel adicionar coluna %s em sollus_tickets.", column)

    if "sollus_ticket_departments" in tables:
        department_existing = {column["name"] for column in inspector.get_columns("sollus_ticket_departments")}
        if "email_template_group_id" not in department_existing:
            try:
                with db.engine.begin() as connection:
                    connection.execute(text("ALTER TABLE sollus_ticket_departments ADD COLUMN email_template_group_id INTEGER"))
            except Exception:
                current_app.logger.exception("Nao foi possivel adicionar coluna email_template_group_id em sollus_ticket_departments.")

    if "sollus_ticket_mailboxes" in tables:
        mailbox_existing = {column["name"] for column in inspector.get_columns("sollus_ticket_mailboxes")}
        mailbox_defs = {
            "fetch_frequency_minutes": "INTEGER NOT NULL DEFAULT 5",
            "fetch_max": "INTEGER NOT NULL DEFAULT 30",
            "postfetch": "VARCHAR(20) NOT NULL DEFAULT 'nothing'",
            "archive_folder": "VARCHAR(120)",
            "num_errors": "INTEGER NOT NULL DEFAULT 0",
        }
        with db.engine.begin() as connection:
            for column, definition in mailbox_defs.items():
                if column in mailbox_existing:
                    continue
                try:
                    connection.execute(text(f"ALTER TABLE sollus_ticket_mailboxes ADD COLUMN {column} {definition}"))
                except Exception:
                    current_app.logger.exception("Nao foi possivel adicionar coluna %s em sollus_ticket_mailboxes.", column)

    if "sollus_ticket_processed_emails" in tables:
        processed_existing = {column["name"] for column in inspector.get_columns("sollus_ticket_processed_emails")}
        if "source_uid" not in processed_existing:
            try:
                with db.engine.begin() as connection:
                    connection.execute(text("ALTER TABLE sollus_ticket_processed_emails ADD COLUMN source_uid VARCHAR(500)"))
            except Exception:
                current_app.logger.exception("Nao foi possivel adicionar coluna source_uid em sollus_ticket_processed_emails.")

    if "sollus_ticket_role_permissions" in tables:
        role_existing = {column["name"] for column in inspector.get_columns("sollus_ticket_role_permissions")}
        role_defs = {
            "can_transfer": "BOOLEAN NOT NULL DEFAULT 0",
            "can_delete": "BOOLEAN NOT NULL DEFAULT 0",
            "can_merge": "BOOLEAN NOT NULL DEFAULT 0",
            "can_link": "BOOLEAN NOT NULL DEFAULT 0",
            "can_manage_tasks": "BOOLEAN NOT NULL DEFAULT 0",
            "can_manage_queues": "BOOLEAN NOT NULL DEFAULT 0",
            "limit_access": "BOOLEAN NOT NULL DEFAULT 0",
        }
        with db.engine.begin() as connection:
            for column, definition in role_defs.items():
                if column in role_existing:
                    continue
                try:
                    connection.execute(text(f"ALTER TABLE sollus_ticket_role_permissions ADD COLUMN {column} {definition}"))
                except Exception:
                    current_app.logger.exception("Nao foi possivel adicionar coluna %s em sollus_ticket_role_permissions.", column)

    if "sollus_ticket_email_template_groups" in tables:
        group_existing = {column["name"] for column in inspector.get_columns("sollus_ticket_email_template_groups")}
        if "legacy_id" not in group_existing:
            try:
                with db.engine.begin() as connection:
                    connection.execute(text("ALTER TABLE sollus_ticket_email_template_groups ADD COLUMN legacy_id INTEGER"))
            except Exception:
                current_app.logger.exception("Nao foi possivel adicionar coluna legacy_id em sollus_ticket_email_template_groups.")

    if "sollus_ticket_thread_entries" in tables:
        entry_existing = {column["name"] for column in inspector.get_columns("sollus_ticket_thread_entries")}
        entry_defs = {
            "email_message_id": "VARCHAR(500)",
            "email_references": "TEXT",
            "mail_flags_json": "JSON",
        }
        with db.engine.begin() as connection:
            for column, definition in entry_defs.items():
                if column in entry_existing:
                    continue
                try:
                    connection.execute(text(f"ALTER TABLE sollus_ticket_thread_entries ADD COLUMN {column} {definition}"))
                except Exception:
                    current_app.logger.exception("Nao foi possivel adicionar coluna %s em sollus_ticket_thread_entries.", column)

    if "sollus_ticket_tasks" in tables:
        task_existing = {column["name"] for column in inspector.get_columns("sollus_ticket_tasks")}
        if "legacy_id" not in task_existing:
            try:
                with db.engine.begin() as connection:
                    connection.execute(text("ALTER TABLE sollus_ticket_tasks ADD COLUMN legacy_id INTEGER"))
            except Exception:
                current_app.logger.exception("Nao foi possivel adicionar coluna legacy_id em sollus_ticket_tasks.")


def agents_query(department_id: int | None = None) -> list[User]:
    """
    Retorna usuários ativos que são membros de pelo menos uma equipe ativa
    no Sollus Tickets. Apenas esses usuários aparecem no select de atribuição.
    Se department_id for fornecido, filtra apenas os usuários que possuem
    acesso a esse departamento.
    """
    active_team_ids = (
        db.session.query(SollusTicketTeam.id)
        .filter(SollusTicketTeam.is_active.is_(True))
    )
    user_ids_in_teams = (
        db.session.query(SollusTicketTeamMember.user_id)
        .filter(SollusTicketTeamMember.team_id.in_(active_team_ids))
        .distinct()
    )
    q = User.query.filter(User.is_active.is_(True), User.id.in_(user_ids_in_teams))
    if department_id is not None:
        dept_user_ids = (
            db.session.query(SollusTicketDepartmentAccess.user_id)
            .filter(SollusTicketDepartmentAccess.department_id == department_id)
        )
        q = q.filter(User.id.in_(dept_user_ids))
    return q.order_by(User.nome_completo.asc(), User.email.asc()).all()


def permission_for_user(user: User) -> SollusTicketRolePermission:
    role_key = (getattr(user, "role", None) or getattr(user, "tipo", None) or "usuario").lower()
    perm = SollusTicketRolePermission.query.filter_by(role_key=role_key).first()
    if perm:
        return perm
    flags = DEFAULT_ROLE_PERMISSIONS.get(role_key, DEFAULT_ROLE_PERMISSIONS["usuario"])
    return SollusTicketRolePermission(role_key=role_key, **flags)


def ticket_visible_query(user: User):
    from .models import SollusTicketDepartmentAccess

    role = (getattr(user, "role", None) or "").lower()
    tipo = (getattr(user, "tipo", None) or "").lower()

    is_admin = role == "admin" or tipo == "admin"
    is_gestor = role == "gestor" or tipo == "gestor"

    # Sempre exclui tickets marcados como deletados do painel
    query = SollusTicket.query.filter(SollusTicket.status_key != "deleted")

    if is_admin:
        # Administrador vê tudo
        return query

    if not is_gestor:
        # Usuários comuns (não admin e não gestor) só veem os do próprio nome
        return query.filter(SollusTicket.assignee_id == user.id)

    # Gestores veem os tickets de seu departamento, times, atribuídos a si ou solicitados por si
    team_ids = [
        row.team_id
        for row in SollusTicketTeamMember.query.filter_by(user_id=user.id).all()
    ]
    department_ids = [
        row.department_id
        for row in SollusTicketDepartmentAccess.query.filter_by(user_id=user.id).all()
    ]

    # Também inclui o departamento principal do usuário (mapeado pelo slug para SollusTicketDepartment)
    if getattr(user, "department_id", None):
        from modules.propostas.models import Department
        dept = Department.query.get(user.department_id)
        if dept:
            from .models import SollusTicketDepartment
            ticket_dept = SollusTicketDepartment.query.filter_by(slug=dept.slug).first()
            if ticket_dept and ticket_dept.id not in department_ids:
                department_ids.append(ticket_dept.id)

    filters = [SollusTicket.requester_id == user.id, SollusTicket.assignee_id == user.id]
    if team_ids:
        filters.append(SollusTicket.team_id.in_(team_ids))
    if department_ids:
        filters.append(SollusTicket.department_id.in_(department_ids))
    return query.filter(or_(*filters))


def next_ticket_number() -> str:
    from extensions import db
    nums = db.session.query(SollusTicket.number).all()
    max_val = 0
    for (num,) in nums:
        if num and num.strip().isdigit():
            try:
                val = int(num.strip())
                if val > max_val:
                    max_val = val
            except ValueError:
                pass
    seq = max_val + 1
    # Fallback to start at 1000 if no numeric tickets exist
    if seq < 1000 and max_val == 0:
        seq = 1000
    return f"{seq:06d}"


def add_event(ticket: SollusTicket, action: str, message: str, actor_id: int | None = None, before=None, after=None) -> None:
    db.session.add(
        SollusTicketEvent(
            ticket_id=ticket.id,
            actor_user_id=actor_id,
            action=action,
            message=message,
            before_value=str(before) if before is not None else None,
            after_value=str(after) if after is not None else None,
        )
    )


def _base_url() -> str:
    try:
        return (current_app.config.get("MAIL_BASE_URL") or request.url_root).rstrip("/")
    except RuntimeError:
        return (current_app.config.get("MAIL_BASE_URL") or "").rstrip("/")


def ticket_recipients(ticket: SollusTicket, include_requester: bool = True, include_assignee: bool = True, cc: bool = True) -> list[str]:
    recipients: list[str] = []
    if include_requester:
        if ticket.contact and ticket.contact.email:
            recipients.append(ticket.contact.email)
        elif ticket.requester and ticket.requester.email:
            recipients.append(ticket.requester.email)
    if include_assignee and ticket.assignee and ticket.assignee.email:
        recipients.append(ticket.assignee.email)
    if cc:
        for collab in ticket.collaborators:
            if collab.contact and collab.contact.email:
                recipients.append(collab.contact.email)
    seen = set()
    cleaned = []
    for email in recipients:
        normalized = (email or "").strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            cleaned.append(email)
    return cleaned


def _is_internal_user_email(email: str) -> bool:
    """Verifica se o e-mail pertence a um usuário interno ativo no sistema."""
    try:
        email_clean = (email or "").strip().lower()
        return bool(User.query.filter(
            db.func.lower(User.email) == email_clean,
            User.is_active.is_(True)
        ).first())
    except Exception:
        return False


def notify_ticket(ticket: SollusTicket, event: str, body: str = "", entry: SollusTicketThreadEntry | None = None) -> None:
    """Dispara notificação por e-mail para todos os destinatários do ticket.

    Destinatários internos (agentes/staff) recebem o e-mail completo com link.
    Destinatários externos (clientes) recebem o e-mail sem o link 'Abrir ticket',
    garantindo que o conteúdo da resposta seja legível mesmo fora do portal.
    """
    try:
        from modules.chamados.mailer import enviar_email
    except Exception:
        return
    try:
        from .advanced import build_message_id, render_email_template
        subject, html, text_body = render_email_template(ticket, event, body)
        if not subject:
            return
        message_id = build_message_id(ticket, entry.id if entry else None)
        if entry and not entry.email_message_id:
            entry.email_message_id = message_id.strip("<>").lower()
            db.session.commit()
        headers = {
            "Message-ID": message_id,
            "X-Sollus-Ticket": str(ticket.number or ticket.id),
            "Auto-Submitted": "auto-generated" if event != "created" else "no",
        }
        refs = entry.email_references if entry and entry.email_references else None
        if refs:
            headers["References"] = refs
    except Exception:
        labels = {
            "created": "Ticket criado",
            "reply": "Nova resposta",
            "assign": "Ticket atribuído",
            "status": "Status atualizado",
            "closed": "Ticket fechado",
            "reopened": "Ticket reaberto",
            "overdue": "Ticket em atraso",
        }
        subject = f"[Sollus Tickets {ticket.number or ticket.id}] {labels.get(event, 'Atualização')} - {ticket.subject}"
        link = f"{_base_url()}{url_for('sollus_tickets.detail', ticket_id=ticket.id)}" if _base_url() else ""
        html = render_template("sollus_tickets/email.html", ticket=ticket, title=labels.get(event, "Atualização"), body=body, link=link)
        text_body = body
        headers = None
    sender = _ticket_sender_email(ticket)
    attachments = entry.attachments if entry else None

    # Para SLA/overdue, todos os destinatários são internos
    if event == "overdue":
        recipients = []
        if ticket.assignee and ticket.assignee.email:
            recipients.append(ticket.assignee.email)
        if ticket.department:
            from .models import SollusTicketDepartmentAccess
            managers = (
                SollusTicketDepartmentAccess.query
                .filter_by(department_id=ticket.department_id, is_manager=True)
                .all()
            )
            for ma in managers:
                if ma.user and ma.user.email and ma.user.email not in recipients:
                    recipients.append(ma.user.email)
        if recipients:
            enviar_email(recipients, subject, html, text_body, headers=headers, sender=sender, reply_to=sender, attachments=attachments)
        return

    # Para outros eventos, separa internos x externos e envia versões diferentes
    all_recipients = ticket_recipients(ticket)
    internal_recipients = [e for e in all_recipients if _is_internal_user_email(e)]
    external_recipients = [e for e in all_recipients if not _is_internal_user_email(e)]

    # Prepara versão sem link para clientes externos
    try:
        from .ticket_mailer import _strip_external_ticket_links
        ext_html, ext_text = _strip_external_ticket_links(html, text_body)
    except Exception:
        ext_html, ext_text = html, text_body

    if internal_recipients:
        enviar_email(internal_recipients, subject, html, text_body, headers=headers, sender=sender, reply_to=sender, attachments=attachments)
    if external_recipients:
        enviar_email(external_recipients, subject, ext_html, ext_text, headers=headers, sender=sender, reply_to=sender, attachments=attachments)


def _ticket_sender_email(ticket: SollusTicket) -> str | None:
    if ticket.department_id:
        mailbox = (
            SollusTicketMailbox.query
            .filter_by(department_id=ticket.department_id, enabled=True)
            .order_by(SollusTicketMailbox.id.asc())
            .first()
        )
        if mailbox and mailbox.email:
            return mailbox.email
    if ticket.department and ticket.department.email:
        return ticket.department.email
    return None


def create_ticket(
    *,
    subject: str,
    body: str,
    requester_id: int | None = None,
    contact_id: int | None = None,
    department_id: int | None,
    topic_id: int | None,
    priority_key: str,
    queue_id: int | None = None,
    team_id: int | None = None,
    sla_id: int | None = None,
    field_values: dict[int, str] | None = None,
    source: str = "web",
    notify: bool = True,
) -> SollusTicket:
    sla = SollusTicketSLA.query.get(sla_id) if sla_id else SollusTicketSLA.query.filter_by(is_active=True).first()
    due_at = datetime.utcnow() + timedelta(hours=sla.grace_period_hours) if sla else None
    ticket = SollusTicket(
        number=next_ticket_number(),
        subject=subject,
        requester_id=requester_id,
        department_id=department_id,
        topic_id=topic_id,
        queue_id=queue_id,
        team_id=team_id,
        sla_id=sla.id if sla else None,
        contact_id=contact_id,
        due_at=due_at,
        priority_key=priority_key,
        source=source,
        status_key="open",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        last_message_at=datetime.utcnow(),
    )
    db.session.add(ticket)
    db.session.flush()
    entry = SollusTicketThreadEntry(
            ticket_id=ticket.id,
            author_user_id=requester_id,
            contact_id=contact_id,
            type="message",
            visibility="public",
            title=subject,
            body=body,
    )
    db.session.add(entry)
    for field_id, value in (field_values or {}).items():
        db.session.add(SollusTicketFieldValue(ticket_id=ticket.id, field_id=field_id, value=value))
    add_event(ticket, "created", "Ticket criado.", requester_id, after={"status": "open", "source": source})
    auto_assign_ticket(ticket, actor_id=requester_id)
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket",
        action="create",
        entity_id=ticket.id,
        after={"status": "open", "source": source, "subject": subject},
        message=f"Ticket {ticket.number or ticket.id} criado."
    )
    db.session.commit()
    if notify:
        notify_ticket(ticket, "created", body, entry)
    return ticket


def add_thread_entry(
    ticket: SollusTicket,
    *,
    body: str,
    actor_id: int | None,
    contact_id: int | None = None,
    entry_type: str = "reply",
    visibility: str = "public",
    notify: bool = True,
) -> SollusTicketThreadEntry:
    entry = SollusTicketThreadEntry(
        ticket_id=ticket.id,
        author_user_id=actor_id,
        contact_id=contact_id,
        type=entry_type,
        visibility=visibility,
        body=body,
    )
    # Se a resposta for do cliente, reinicia o SLA
    if contact_id is not None or actor_id is None:
        sla = ticket.sla or SollusTicketSLA.query.filter_by(is_active=True).first()
        if sla:
            ticket.due_at = datetime.utcnow() + timedelta(hours=sla.grace_period_hours)
            ticket.overdue_at = None

    ticket.last_message_at = datetime.utcnow()
    ticket.updated_at = datetime.utcnow()
    db.session.add(entry)
    add_event(ticket, entry_type, "Nova interacao registrada.", actor_id)
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket",
        action="reply",
        entity_id=ticket.id,
        message=f"Nova interacao ({entry_type}, {visibility}) registrada no ticket {ticket.number or ticket.id}."
    )
    db.session.commit()
    if visibility == "public" and notify:
        notify_ticket(ticket, "reply", body, entry)
    return entry


def update_status(ticket: SollusTicket, status_key: str, actor_id: int | None, reason: str | None = None) -> None:
    before = ticket.status_key
    # Guard: se o status nao mudou, nao dispara evento nem notificacao (evita spam de e-mail por cliques duplos)
    if before == status_key:
        return
    if before in {"closed", "resolved"} and status_key not in {"closed", "resolved"}:
        ticket.reopened_at = datetime.utcnow()
        ticket.reopen_count = (ticket.reopen_count or 0) + 1
        ticket.closed_at = None
        action = "reopened"
    elif status_key in {"closed", "resolved"}:
        action = "closed"
    else:
        action = "status"
    ticket.status_key = status_key
    ticket.updated_at = datetime.utcnow()
    if status_key == "resolved":
        ticket.resolved_at = datetime.utcnow()
    if status_key in {"closed", "resolved"}:
        ticket.closed_at = datetime.utcnow()
        ticket.close_reason = reason
    actor_name = "Sistema"
    if actor_id:
        from modules.propostas.models import User
        usr = User.query.get(actor_id)
        if usr:
            actor_name = usr.nome_completo or usr.name or usr.email
    add_event(ticket, action, f"Status alterado de {before} para {status_key} por {actor_name}.", actor_id, before, {"status": status_key, "reason": reason})
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket",
        action="status",
        entity_id=ticket.id,
        before=before,
        after=status_key,
        message=f"Status do ticket {ticket.number or ticket.id} alterado de {before} para {status_key}."
    )
    db.session.commit()
    notify_ticket(ticket, action, reason or "")


def assign_ticket(ticket: SollusTicket, assignee_id: int | None, actor_id: int | None, automatic: bool = False) -> None:
    before = ticket.assignee_id
    ticket.assignee_id = assignee_id
    if assignee_id and ticket.status_key == "open":
        ticket.status_key = "in_progress"
    ticket.updated_at = datetime.utcnow()
    actor_name = "Sistema"
    if actor_id:
        from modules.propostas.models import User
        actor_user = User.query.get(actor_id)
        if actor_user:
            actor_name = actor_user.nome_completo or actor_user.name or actor_user.email
            
    if assignee_id:
        from modules.propostas.models import User
        usr = User.query.get(assignee_id)
        name = (usr.nome_completo or usr.name or usr.email) if usr else f"#{assignee_id}"
        msg = f"Ticket atribuído para {name} por {actor_name}."
    else:
        msg = f"Ticket desatribuído por {actor_name}."
    add_event(ticket, "assign", msg, actor_id, before, assignee_id)
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket",
        action="assign",
        entity_id=ticket.id,
        before=before,
        after=assignee_id,
        message=f"Ticket {ticket.number or ticket.id} atribuído ao usuário #{assignee_id}."
    )
    db.session.commit()
    notify_ticket(ticket, "assign")


def auto_assign_ticket(ticket: SollusTicket, actor_id: int | None = None) -> None:
    department = ticket.department
    if not department or not department.auto_assign_enabled or ticket.assignee_id:
        return
    if ticket.team_id:
        member_ids = [row.user_id for row in SollusTicketTeamMember.query.filter_by(team_id=ticket.team_id).all()]
        agents = User.query.filter(User.id.in_(member_ids), User.is_active.is_(True)).order_by(User.nome_completo.asc()).all() if member_ids else []
    else:
        from models import Department
        # Find core Department matching the ticket's SollusTicketDepartment slug
        core_dept = Department.query.filter_by(slug=department.slug).first()
        if core_dept:
            active_team_ids = (
                db.session.query(SollusTicketTeam.id)
                .filter(SollusTicketTeam.is_active.is_(True))
                .subquery()
            )
            user_ids_in_teams = (
                db.session.query(SollusTicketTeamMember.user_id)
                .filter(SollusTicketTeamMember.team_id.in_(active_team_ids))
                .distinct()
                .subquery()
            )
            agents = (
                User.query
                .filter(
                    User.is_active.is_(True),
                    User.id.in_(user_ids_in_teams),
                    User.department_id == core_dept.id
                )
                .order_by(User.nome_completo.asc(), User.email.asc())
                .all()
            )
        else:
            agents = []

        if not agents:
            agents = agents_query()

    if not agents:
        return

    start_index = -1
    if department.last_assigned_user_id:
        for idx, agent in enumerate(agents):
            if agent.id == department.last_assigned_user_id:
                start_index = idx
                break
    assignee = agents[(start_index + 1) % len(agents)]
    ticket.assignee_id = assignee.id
    ticket.status_key = "in_progress"
    department.last_assigned_user_id = assignee.id
    add_event(ticket, "auto_assign", f"Atribuído automaticamente para {assignee.name or assignee.email}.", actor_id)


def status_map() -> dict[str, SollusTicketStatus]:
    return {row.key: row for row in SollusTicketStatus.query.order_by(SollusTicketStatus.sort_order).all()}


def priority_map() -> dict[str, SollusTicketPriority]:
    return {row.key: row for row in SollusTicketPriority.query.order_by(SollusTicketPriority.level).all()}


def normalize_osticket_status(value: str | None, closed: bool = False) -> str:
    key = slugify(value or "")
    if closed or key in {"closed", "resolved", "archived"}:
        return "closed" if key != "resolved" else "resolved"
    if key in {"open", "aberto"}:
        return "open"
    return key or "open"


def normalize_osticket_priority(value: str | None) -> str:
    key = slugify(value or "")
    if key in {"low", "baixa"}:
        return "low"
    if key in {"high", "alta"}:
        return "high"
    if key in {"emergency", "emergencia", "urgent", "urgente"}:
        return "emergency"
    return "normal"


def bulk_add_events(ticket: SollusTicket, actions: Iterable[tuple[str, str, datetime | None]]) -> None:
    for action, message, created_at in actions:
        db.session.add(
            SollusTicketEvent(
                ticket_id=ticket.id,
                action=action,
                message=message,
                created_at=created_at or datetime.utcnow(),
            )
        )


def save_ticket_attachment(ticket: SollusTicket, file_storage, *, entry: SollusTicketThreadEntry | None = None, uploader_id: int | None = None) -> SollusTicketAttachment | None:
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None
    original_name = file_storage.filename or ""
    filename = secure_filename(original_name)
    if not filename:
        return None
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise ValueError(f"Extensao nao permitida: {ext}")
    max_mb = int(current_app.config.get("MAX_CONTENT_MB", 20))
    stream = getattr(file_storage, "stream", None)
    size = 0
    if stream:
        pos = stream.tell()
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(pos)
    if size and size > max_mb * 1024 * 1024:
        raise ValueError(f"Arquivo excede {max_mb}MB.")
    stored = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(8)}{ext}"
    folder = Path(current_app.config.get("UPLOADS_DIR", "uploads")) / "sollus_tickets" / str(ticket.id)
    folder.mkdir(parents=True, exist_ok=True)
    file_storage.save(folder / stored)
    attachment = SollusTicketAttachment(
        ticket_id=ticket.id,
        entry_id=entry.id if entry else None,
        original_name=original_name,
        stored_name=stored,
        content_type=getattr(file_storage, "mimetype", None) or mimetypes.guess_type(filename)[0],
        size=size,
        storage_path=f"sollus_tickets/{ticket.id}/{stored}",
        uploaded_by_id=uploader_id,
    )
    db.session.add(attachment)
    add_event(ticket, "attachment", f"Anexo enviado: {original_name}", uploader_id)
    ticket.updated_at = datetime.utcnow()
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket",
        action="upload_attachment",
        entity_id=ticket.id,
        after={"filename": original_name},
        message=f"Anexo {original_name} adicionado ao ticket {ticket.number or ticket.id}."
    )
    db.session.commit()
    return attachment


def save_ticket_attachment_bytes(
    ticket: SollusTicket,
    *,
    filename: str,
    data: bytes,
    content_type: str | None = None,
    entry: SollusTicketThreadEntry | None = None,
    uploader_id: int | None = None,
) -> SollusTicketAttachment | None:
    original_name = filename or ""
    safe_name = secure_filename(original_name)
    if not safe_name or not data:
        return None
    ext = Path(safe_name).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise ValueError(f"Extensao nao permitida: {ext}")
    max_mb = int(current_app.config.get("MAX_CONTENT_MB", 20))
    if len(data) > max_mb * 1024 * 1024:
        raise ValueError(f"Arquivo excede {max_mb}MB.")
    stored = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(8)}{ext}"
    folder = Path(current_app.config.get("UPLOADS_DIR", "uploads")) / "sollus_tickets" / str(ticket.id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / stored).write_bytes(data)
    attachment = SollusTicketAttachment(
        ticket_id=ticket.id,
        entry_id=entry.id if entry else None,
        original_name=original_name,
        stored_name=stored,
        content_type=content_type or mimetypes.guess_type(safe_name)[0],
        size=len(data),
        storage_path=f"sollus_tickets/{ticket.id}/{stored}",
        uploaded_by_id=uploader_id,
    )
    db.session.add(attachment)
    add_event(ticket, "attachment", f"Anexo recebido por e-mail: {original_name}", uploader_id)
    ticket.updated_at = datetime.utcnow()
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket",
        action="upload_attachment",
        entity_id=ticket.id,
        after={"filename": original_name},
        message=f"Anexo {original_name} recebido por e-mail no ticket {ticket.number or ticket.id}."
    )
    db.session.commit()
    return attachment


def update_sla_overdue() -> int:
    now = datetime.utcnow()
    try:
        # Subquery: IDs de tickets que já receberam ao menos uma resposta de agente
        # (author_user_id preenchido = agente interno; contact_id nulo = não é o cliente)
        replied_query = (
            db.session.query(SollusTicketThreadEntry.ticket_id)
            .filter(
                SollusTicketThreadEntry.author_user_id.isnot(None),
                SollusTicketThreadEntry.contact_id.is_(None),
            )
            .distinct()
        )

        tickets = (
            SollusTicket.query
            .filter(SollusTicket.due_at.isnot(None))
            .filter(SollusTicket.overdue_at.is_(None))
            .filter(~SollusTicket.status_key.in_(("closed", "resolved", "deleted")))
            .filter(SollusTicket.due_at < now)
            # Não enviar alerta se o ticket já foi respondido por um agente
            .filter(~SollusTicket.id.in_(replied_query))
            .all()
        )
        for ticket in tickets:
            ticket.overdue_at = now
            add_event(ticket, "overdue", "Ticket marcado como atrasado pelo SLA.", None)
            # Nota: notify_ticket("overdue") não é chamado aqui para evitar duplicidade.
            # O job run_sla_alerts() (ticket_mailer.py) já dispara os alertas de SLA
            # com controle de frequência (máximo 2x por dia).
        if tickets:
            db.session.commit()
        return len(tickets)
    except Exception as e:
        db.session.rollback()
        log_system_event("SLA Check Error", str(e), level="error", source="cron")
        raise


def log_system_event(title: str, message: str | None = None, level: str = "info", source: str = "system") -> SollusTicketSystemLog:
    from flask import request
    ip = None
    try:
        ip = request.remote_addr
    except RuntimeError:
        pass
    
    log = SollusTicketSystemLog(
        title=title[:255],
        message=message,
        level=level,
        source=source,
        ip_address=ip
    )
    db.session.add(log)
    db.session.commit()
    return log
