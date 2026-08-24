"""Advanced osTicket-like behaviors for Sollus Tickets."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import Message
from email.utils import parseaddr

from flask import current_app, render_template, request, url_for
from sqlalchemy import and_, func, or_

from extensions import db
from modules.propostas.models import User

from .models import (
    SollusTicket,
    SollusTicketAttachment,
    SollusTicketBanlist,
    SollusTicketCollaborator,
    SollusTicketDepartmentAccess,
    SollusTicketEmailTemplate,
    SollusTicketEmailTemplateGroup,
    SollusTicketEvent,
    SollusTicketFilterRule,
    SollusTicketLock,
    SollusTicketPriority,
    SollusTicketRelation,
    SollusTicketRolePermission,
    SollusTicketTask,
    SollusTicketTaskEntry,
    SollusTicketTeamMember,
)


@dataclass
class RuleResult:
    rejected: bool = False
    reject_reason: str = ""
    priority_key: str | None = None
    department_id: int | None = None
    topic_id: int | None = None
    queue_id: int | None = None
    team_id: int | None = None
    sla_id: int | None = None
    assignee_id: int | None = None
    matched_rules: list[str] | None = None


def user_role_key(user: User) -> str:
    return (getattr(user, "role", None) or getattr(user, "tipo", None) or "usuario").lower()


def permission_for(user: User) -> SollusTicketRolePermission:
    role_key = user_role_key(user)
    perm = SollusTicketRolePermission.query.filter_by(role_key=role_key).first()
    if perm:
        return perm
    return SollusTicketRolePermission(role_key=role_key)


def department_access_ids(user: User) -> set[int]:
    return {
        row.department_id
        for row in SollusTicketDepartmentAccess.query.filter_by(user_id=user.id).all()
    }


def can_view_ticket(user: User, ticket: SollusTicket) -> bool:
    perm = permission_for(user)
    if perm.can_view_all or perm.can_manage_admin:
        return True
    if ticket.requester_id == user.id or ticket.assignee_id == user.id:
        return True
    if ticket.department_id and ticket.department_id in department_access_ids(user):
        return True
    if ticket.team_id:
        return bool(SollusTicketTeamMember.query.filter_by(team_id=ticket.team_id, user_id=user.id).first())
    return False


def can_manage_department(user: User, department_id: int | None) -> bool:
    perm = permission_for(user)
    if perm.can_manage_admin:
        return True
    if not department_id:
        return False
    access = SollusTicketDepartmentAccess.query.filter_by(user_id=user.id, department_id=department_id).first()
    return bool(access and access.is_manager)


def is_banned_email(email_addr: str) -> SollusTicketBanlist | None:
    email_addr = (email_addr or "").strip().lower()
    if not email_addr:
        return None
    domain = email_addr.split("@", 1)[-1] if "@" in email_addr else ""
    return (
        SollusTicketBanlist.query.filter_by(is_active=True)
        .filter(
            or_(
                and_(SollusTicketBanlist.kind == "email", func.lower(SollusTicketBanlist.value) == email_addr),
                and_(SollusTicketBanlist.kind == "domain", func.lower(SollusTicketBanlist.value) == domain),
            )
        )
        .first()
    )


def infer_priority_from_headers(msg: Message) -> str | None:
    header = "\n".join(f"{key}: {value}" for key, value in msg.items())
    if re.search(r"(x-priority|importance|priority):\s*(1|2|high|urgent)", header, re.I):
        return "high"
    if re.search(r"(x-priority|importance|priority):\s*(5|6|low)", header, re.I):
        return "low"
    return None


def mail_flags(msg: Message) -> dict[str, bool]:
    header = "\n".join(f"{key}: {value}" for key, value in msg.items())
    auto_submitted = str(msg.get("Auto-Submitted") or "").lower()
    precedence = str(msg.get("Precedence") or "").lower()
    subject = str(msg.get("Subject") or "")
    return {
        "bounce": bool(re.search(r"(mailer-daemon|postmaster|delivery status notification|undeliver)", header + "\n" + subject, re.I)),
        "auto_reply": auto_submitted not in {"", "no"} or "auto" in precedence or bool(msg.get("X-Autoreply")),
        "spam": bool(re.search(r"(x-spam-flag:\s*yes|x-spam-status:\s*yes)", header, re.I)),
        "viral": bool(re.search(r"(virus|malware|infected)", header, re.I)),
    }


def apply_filter_rules(*, sender: str, subject: str, body: str, headers: str, defaults: dict | None = None) -> RuleResult:
    result = RuleResult(matched_rules=[])
    defaults = defaults or {}
    for key, value in defaults.items():
        if hasattr(result, key):
            setattr(result, key, value)
    banned = is_banned_email(sender)
    if banned:
        result.rejected = True
        result.reject_reason = banned.reason or "Remetente bloqueado."
        return result
    haystack = {
        "sender_contains": sender or "",
        "subject_contains": subject or "",
        "body_contains": body or "",
        "header_contains": headers or "",
    }
    rules = SollusTicketFilterRule.query.filter_by(is_active=True).order_by(SollusTicketFilterRule.sort_order, SollusTicketFilterRule.id).all()
    for rule in rules:
        checks = []
        for attr, value in haystack.items():
            needle = (getattr(rule, attr) or "").strip()
            if not needle:
                continue
            
            target_value = (value or "").lower()
            needle_lower = needle.lower()
            
            if needle_lower.startswith("regex:"):
                pattern = needle[6:].strip()
                try:
                    checks.append(bool(re.search(pattern, target_value, re.I)))
                except Exception:
                    checks.append(False)
            elif needle_lower.startswith("equal:"):
                checks.append(needle[6:].strip().lower() == target_value)
            elif needle_lower.startswith("starts:"):
                checks.append(target_value.startswith(needle[7:].strip().lower()))
            elif needle_lower.startswith("ends:"):
                checks.append(target_value.endswith(needle[5:].strip().lower()))
            else:
                # Default: contains
                checks.append(needle_lower in target_value)
                
        if not checks:
            continue
        matched = all(checks) if rule.match_all else any(checks)
        if not matched:
            continue
        result.matched_rules.append(rule.name)
        if rule.reject_ticket:
            result.rejected = True
            result.reject_reason = f"Bloqueado pela regra: {rule.name}"
            return result
        for source, target in (
            ("set_priority_key", "priority_key"),
            ("set_department_id", "department_id"),
            ("set_topic_id", "topic_id"),
            ("set_queue_id", "queue_id"),
            ("set_team_id", "team_id"),
            ("set_sla_id", "sla_id"),
            ("assign_user_id", "assignee_id"),
        ):
            value = getattr(rule, source, None)
            if value:
                setattr(result, target, value)
        if rule.stop_processing:
            break
    return result


def acquire_ticket_lock(ticket: SollusTicket, user: User, purpose: str = "edit", minutes: int = 15) -> tuple[bool, SollusTicketLock]:
    now = datetime.utcnow()
    lock = SollusTicketLock.query.filter_by(ticket_id=ticket.id).first()
    if lock and lock.expires_at > now and lock.user_id != user.id:
        return False, lock
    if not lock:
        lock = SollusTicketLock(ticket_id=ticket.id, user_id=user.id, purpose=purpose, expires_at=now + timedelta(minutes=minutes))
        db.session.add(lock)
    else:
        lock.user_id = user.id
        lock.purpose = purpose
        lock.expires_at = now + timedelta(minutes=minutes)
        lock.updated_at = now
    db.session.commit()
    return True, lock


def release_ticket_lock(ticket: SollusTicket, user: User | None = None) -> None:
    query = SollusTicketLock.query.filter_by(ticket_id=ticket.id)
    if user:
        query = query.filter_by(user_id=user.id)
    query.delete()
    db.session.commit()


def transfer_ticket(ticket: SollusTicket, *, actor_id: int | None, department_id: int | None = None, team_id: int | None = None, queue_id: int | None = None, assignee_id: int | None = None, reason: str = "") -> None:
    before = {
        "department_id": ticket.department_id,
        "team_id": ticket.team_id,
        "queue_id": ticket.queue_id,
        "assignee_id": ticket.assignee_id,
    }
    if department_id is not None:
        ticket.department_id = department_id
    if team_id is not None:
        ticket.team_id = team_id
    if queue_id is not None:
        ticket.queue_id = queue_id
    ticket.assignee_id = assignee_id
    ticket.updated_at = datetime.utcnow()
    actor_name = "Sistema"
    if actor_id:
        from modules.propostas.models import User
        actor_user = User.query.get(actor_id)
        if actor_user:
            actor_name = actor_user.nome_completo or actor_user.name or actor_user.email
            
    desc = []
    if department_id and department_id != before["department_id"]:
        from .models import SollusTicketDepartment
        dept = SollusTicketDepartment.query.get(department_id)
        if dept:
            desc.append(f"Departamento: {dept.name}")
    if assignee_id != before["assignee_id"]:
        if assignee_id:
            from modules.propostas.models import User
            usr = User.query.get(assignee_id)
            if usr:
                desc.append(f"Atendente: {usr.nome_completo or usr.name or usr.email}")
        else:
            desc.append("Atendente: Nenhum")
            
    msg_parts = [f"Ticket transferido por {actor_name}"]
    if desc:
        msg_parts.append(" (" + ", ".join(desc) + ")")
    if reason:
        msg_parts.append(f". Motivo: {reason}")
    else:
        msg_parts.append(".")
    msg = "".join(msg_parts)
    
    _event(ticket, "transfer", msg, actor_id, before, {
        "department_id": ticket.department_id,
        "team_id": ticket.team_id,
        "queue_id": ticket.queue_id,
        "assignee_id": ticket.assignee_id,
    })
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket",
        action="transfer",
        entity_id=ticket.id,
        before=before,
        after={
            "department_id": ticket.department_id,
            "team_id": ticket.team_id,
            "queue_id": ticket.queue_id,
            "assignee_id": ticket.assignee_id,
        },
        message=f"Ticket {ticket.number or ticket.id} transferido."
    )
    db.session.commit()


def link_tickets(source: SollusTicket, target: SollusTicket, relation_type: str, actor_id: int | None) -> None:
    if source.id == target.id:
        raise ValueError("Nao e possivel relacionar o ticket com ele mesmo.")
    relation_type = relation_type if relation_type in {"linked", "parent", "child", "merged"} else "linked"
    exists = SollusTicketRelation.query.filter_by(source_ticket_id=source.id, target_ticket_id=target.id, relation_type=relation_type).first()
    if not exists:
        db.session.add(SollusTicketRelation(source_ticket_id=source.id, target_ticket_id=target.id, relation_type=relation_type, created_by_id=actor_id))
    _event(source, relation_type, f"Ticket relacionado a {target.number or target.id}.", actor_id)
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket",
        action="link",
        entity_id=source.id,
        after={"target_ticket_id": target.id, "relation_type": relation_type},
        message=f"Ticket {source.number or source.id} relacionado ao ticket {target.number or target.id} ({relation_type})."
    )
    db.session.commit()


def merge_ticket(source: SollusTicket, target: SollusTicket, actor_id: int | None) -> None:
    link_tickets(source, target, "merged", actor_id)
    copied_collaborators = 0
    copied_attachments = 0
    target_contact_ids = {collab.contact_id for collab in target.collaborators}
    for collab in source.collaborators:
        if collab.contact_id in target_contact_ids:
            continue
        db.session.add(SollusTicketCollaborator(ticket_id=target.id, contact_id=collab.contact_id))
        target_contact_ids.add(collab.contact_id)
        copied_collaborators += 1
    for attachment in source.attachments:
        exists = (
            SollusTicketAttachment.query
            .filter_by(ticket_id=target.id, storage_path=attachment.storage_path)
            .first()
        )
        if exists:
            continue
        db.session.add(
            SollusTicketAttachment(
                legacy_attachment_id=None,
                ticket_id=target.id,
                entry_id=None,
                original_name=attachment.original_name,
                stored_name=attachment.stored_name,
                content_type=attachment.content_type,
                size=attachment.size,
                storage_path=attachment.storage_path,
                uploaded_by_id=attachment.uploaded_by_id,
            )
        )
        copied_attachments += 1
    source.status_key = "closed"
    source.closed_at = datetime.utcnow()
    source.close_reason = f"Mesclado ao ticket {target.number or target.id}."
    source.updated_at = datetime.utcnow()
    _event(source, "merge", source.close_reason, actor_id)
    _event(
        target,
        "merge",
        f"Ticket {source.number or source.id} mesclado aqui. "
        f"Colaboradores copiados: {copied_collaborators}; anexos referenciados: {copied_attachments}.",
        actor_id,
        after={"source_ticket_id": source.id, "collaborators": copied_collaborators, "attachments": copied_attachments},
    )
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket",
        action="merge",
        entity_id=target.id,
        after={"merged_ticket_id": source.id},
        message=f"Ticket {source.number or source.id} mesclado no ticket {target.number or target.id}."
    )
    db.session.commit()


def next_task_number() -> str:
    year = datetime.utcnow().year
    prefix = f"TK-{year}-"
    last = SollusTicketTask.query.filter(SollusTicketTask.number.like(f"{prefix}%")).order_by(SollusTicketTask.id.desc()).first()
    seq = 1
    if last and last.number:
        try:
            seq = int(last.number.rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = (last.id or 0) + 1
    return f"{prefix}{seq:05d}"


def create_task(ticket: SollusTicket, *, title: str, body: str = "", actor_id: int | None = None, assignee_id: int | None = None, department_id: int | None = None, team_id: int | None = None, due_at=None, priority_key: str = "normal") -> SollusTicketTask:
    task = SollusTicketTask(
        ticket_id=ticket.id,
        number=next_task_number(),
        title=title,
        body=body,
        assignee_id=assignee_id,
        department_id=department_id or ticket.department_id,
        team_id=team_id or ticket.team_id,
        due_at=due_at,
        priority_key=priority_key,
        created_by_id=actor_id,
    )
    db.session.add(task)
    _event(ticket, "task_create", f"Tarefa criada: {title}", actor_id)
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket_task",
        action="create",
        entity_id=task.id,
        after={"ticket_id": ticket.id, "title": title},
        message=f"Tarefa {task.number or task.id} criada para o ticket {ticket.number or ticket.id}."
    )
    db.session.commit()
    return task


def add_task_entry(task: SollusTicketTask, body: str, actor_id: int | None = None, entry_type: str = "note") -> SollusTicketTaskEntry:
    entry = SollusTicketTaskEntry(task_id=task.id, actor_user_id=actor_id, body=body, type=entry_type)
    task.updated_at = datetime.utcnow()
    db.session.add(entry)
    _event(task.ticket, "task_activity", f"Atualizacao na tarefa {task.number or task.id}.", actor_id)
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket_task",
        action="activity",
        entity_id=task.id,
        message=f"Atualizacao na tarefa {task.number or task.id} do ticket {task.ticket_id}."
    )
    db.session.commit()
    return entry


def close_task(task: SollusTicketTask, actor_id: int | None = None) -> None:
    task.status_key = "closed"
    task.closed_at = datetime.utcnow()
    task.updated_at = datetime.utcnow()
    _event(task.ticket, "task_close", f"Tarefa fechada: {task.number or task.id}.", actor_id)
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket_task",
        action="close",
        entity_id=task.id,
        message=f"Tarefa {task.number or task.id} fechada."
    )
    db.session.commit()


def render_email_template(ticket: SollusTicket, event: str, body: str = "") -> tuple[str, str, str]:
    template_query = (
        SollusTicketEmailTemplate.query.join(SollusTicketEmailTemplateGroup)
        .filter(SollusTicketEmailTemplate.event_key == event)
        .filter(SollusTicketEmailTemplate.is_active.is_(True))
        .filter(SollusTicketEmailTemplateGroup.is_active.is_(True))
    )
    template = None
    group_id = ticket.department.email_template_group_id if ticket.department else None
    if group_id:
        template = template_query.filter(SollusTicketEmailTemplate.group_id == group_id).first()
    if not template and ticket.department:
        dept_slug = _normalize_template_key(ticket.department.name or ticket.department.slug)
        template = (
            template_query
            .filter(or_(
                func.lower(SollusTicketEmailTemplateGroup.slug) == dept_slug,
                func.lower(SollusTicketEmailTemplateGroup.name) == dept_slug,
            ))
            .first()
        )
    if not template:
        template = template_query.first()
    context = _template_context(ticket, body)
    if template:
        if template.suppress_autoreply:
            return "", "", ""
        return _format_template(template.subject, context), _format_template(template.body_html, context), _format_template(template.body_text or "", context)
    subject = f"[Sollus Tickets {ticket.number or ticket.id}] {event} - {ticket.subject}"
    link = context.get("ticket_url") or ""
    html = render_template("sollus_tickets/email.html", ticket=ticket, title=event, body=body, link=link)
    return subject, html, body


def _normalize_template_key(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    return re.sub(r"[^a-z0-9-]+", "", text)


def build_message_id(ticket: SollusTicket, entry_id: int | None = None, recipient_type: str = "U") -> str:
    secret = current_app.config.get("SECRET_KEY") or "sollus-ticket"
    token = f"{ticket.id}:{entry_id or 0}:{recipient_type}:{secrets.token_hex(4)}"
    sig = hmac.new(str(secret).encode(), token.encode(), hashlib.sha1).hexdigest()[:12]
    domain = current_app.config.get("MAIL_MESSAGE_ID_DOMAIN") or "sollus.local"
    return f"<ST-{ticket.id}-{entry_id or 0}-{recipient_type}-{sig}@{domain}>"


def decode_message_id(value: str) -> dict | None:
    text = (value or "").strip().strip("<>")
    match = re.match(r"ST-(\d+)-(\d+)-([A-Z?])-([a-f0-9]+)@", text, re.I)
    if not match:
        return None
    return {"ticket_id": int(match.group(1)), "entry_id": int(match.group(2)), "recipient_type": match.group(3)}


def advanced_report(start=None, end=None) -> dict:
    query = SollusTicket.query
    if start:
        query = query.filter(SollusTicket.created_at >= start)
    if end:
        query = query.filter(SollusTicket.created_at <= end)
    
    total = query.with_entities(func.count(SollusTicket.id)).scalar() or 0
    closed = query.filter(SollusTicket.closed_at.isnot(None)).with_entities(func.count(SollusTicket.id)).scalar() or 0
    
    # Avoid N+1 problem by NOT loading ticket.entries. We'll skip avg_first_response for now to keep it lightning fast.
    # We can get resolution minutes roughly by doing a fast DB query if needed, but for now we'll approximate or leave None
    avg_first_response_minutes = None
    avg_resolution_minutes = None
    
    by_department_query = db.session.query(SollusTicket.department_id, func.count(SollusTicket.id))
    by_agent_query = db.session.query(SollusTicket.assignee_id, func.count(SollusTicket.id))
    if start:
        by_department_query = by_department_query.filter(SollusTicket.created_at >= start)
        by_agent_query = by_agent_query.filter(SollusTicket.created_at >= start)
    if end:
        by_department_query = by_department_query.filter(SollusTicket.created_at <= end)
        by_agent_query = by_agent_query.filter(SollusTicket.created_at <= end)
        
    sla_breached = query.filter(SollusTicket.overdue_at.isnot(None)).with_entities(func.count(SollusTicket.id)).scalar() or 0
    sla_closed_late = query.filter(SollusTicket.closed_at.isnot(None), SollusTicket.due_at.isnot(None), SollusTicket.closed_at > SollusTicket.due_at).with_entities(func.count(SollusTicket.id)).scalar() or 0
    
    return {
        "total": total,
        "closed": closed,
        "open": total - closed,
        "avg_first_response_minutes": avg_first_response_minutes,
        "avg_resolution_minutes": avg_resolution_minutes,
        "by_department": by_department_query.group_by(SollusTicket.department_id).all(),
        "by_agent": by_agent_query.group_by(SollusTicket.assignee_id).all(),
        "overdue": sla_breached,
        "sla_closed_late": sla_closed_late,
        "sla_within": max(closed - sla_closed_late, 0),
    }


def _template_context(ticket: SollusTicket, body: str) -> dict:
    try:
        base = (current_app.config.get("MAIL_BASE_URL") or request.url_root).rstrip("/")
        ticket_url = f"{base}{url_for('sollus_tickets.detail', ticket_id=ticket.id)}"
    except RuntimeError:
        ticket_url = ""
    return {
        "ticket_id": ticket.id,
        "ticket_number": ticket.number or ticket.id,
        "ticket_subject": ticket.subject,
        "ticket_status": ticket.status_key,
        "ticket_priority": ticket.priority_key,
        "requester": ticket.requester_label,
        "assignee": ticket.assignee.name or ticket.assignee.email if ticket.assignee else "",
        "department": ticket.department.name if ticket.department else "",
        "body": body or "",
        "ticket_url": ticket_url,
    }


def _format_template(value: str, context: dict) -> str:
    output = value or ""
    for key, replacement in context.items():
        output = output.replace("{" + key + "}", str(replacement or ""))
    return output


def _event(ticket: SollusTicket, action: str, message: str, actor_id: int | None, before=None, after=None) -> None:
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


def unlink_tickets(relation_id: int, actor_id: int | None) -> int:
    relation = SollusTicketRelation.query.get(relation_id)
    if not relation:
        raise ValueError("Relação não encontrada.")

    source = relation.source
    target = relation.target
    relation_type = relation.relation_type
    source_id = relation.source_ticket_id

    # Log de auditoria
    from modules.audit.utils import write_audit
    write_audit(
        entity_type="ticket",
        action="unlink",
        entity_id=source_id,
        before={"target_ticket_id": relation.target_ticket_id, "relation_type": relation_type},
        message=f"Relação ({relation_type}) removida entre ticket {source.number or source_id} e ticket {target.number or relation.target_ticket_id}."
    )

    # Se a relação for do tipo 'merged', reabre o chamado de origem
    if relation_type == "merged":
        if source and source.status_key == "closed" and "Mesclado" in (source.close_reason or ""):
            source.status_key = "open"
            source.close_reason = None
            source.closed_at = None
            source.updated_at = datetime.utcnow()
            _event(source, "unmerge", f"Desfeito vínculo de mesclagem com o ticket {target.number or target.id}.", actor_id)
            write_audit(
                entity_type="ticket",
                action="reopen",
                entity_id=source.id,
                message=f"Ticket {source.number or source.id} reaberto ao desfazer mesclagem."
            )

    # Loga o evento também no chamado de destino
    if target:
        _event(target, "unlink", f"Desfeito vínculo ({relation_type}) com o ticket {source.number or source.id}.", actor_id)

    db.session.delete(relation)
    db.session.commit()
    return source_id

