"""Serviço de envio de e-mails do módulo Sollus Tickets.

Usa Flask-Mail (extensions.mail) com templates armazenados em
SollusTicketEmailTemplate, substituindo variáveis no estilo %{ticket.number}.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from utils.timezone import get_local_timezone

from flask import current_app
from flask_mail import Message

from extensions import db, mail


# ---------------------------------------------------------------------------
# Variável helpers
# ---------------------------------------------------------------------------

def _ticket_vars(ticket) -> dict:
    """Monta dicionário de variáveis disponíveis para templates de ticket."""
    contact = ticket.contact
    requester = ticket.requester
    assignee = ticket.assignee
    dept = ticket.department

    requester_name = ""
    requester_email = ""
    if contact:
        requester_name = contact.name or contact.email or ""
        requester_email = contact.email or ""
    elif requester:
        requester_name = requester.nome_completo or requester.email or ""
        requester_email = requester.email or ""

    local_tz = get_local_timezone()
    
    def to_local_str(dt):
        if not dt: return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(local_tz).strftime("%d/%m/%Y %H:%M")

    # Construct absolute ticket URL
    cfg = current_app.config
    from flask import request
    try:
        base_url = (cfg.get("MAIL_BASE_URL") or request.url_root.rstrip('/')).rstrip('/')
    except Exception:
        base_url = ""
    ticket_url = f"{base_url}/suporte/tickets/{ticket.id}"

    ticket_num_val = ticket.number or str(ticket.id)

    return {
        "ticket.number": ticket_num_val,
        "ticket_number": ticket_num_val,
        "ticket.subject": ticket.subject or "",
        "ticket_subject": ticket.subject or "",
        "ticket.status": ticket.status_key or "",
        "ticket_status": ticket.status_key or "",
        "ticket.priority": ticket.priority_key or "",
        "ticket_priority": ticket.priority_key or "",
        "ticket.department": dept.name if dept else "",
        "ticket_department": dept.name if dept else "",
        "department": dept.name if dept else "",
        "ticket.created_at": to_local_str(ticket.created_at),
        "ticket_created_at": to_local_str(ticket.created_at),
        "ticket.due_at": to_local_str(ticket.due_at),
        "ticket_due_at": to_local_str(ticket.due_at),
        "requester.name": requester_name,
        "requester_name": requester_name,
        "requester": requester_name,
        "requester.email": requester_email,
        "requester_email": requester_email,
        "assignee.name": (assignee.nome_completo or assignee.email) if assignee else "",
        "assignee_name": (assignee.nome_completo or assignee.email) if assignee else "",
        "assignee.email": assignee.email if assignee else "",
        "assignee_email": assignee.email if assignee else "",
        "ticket_url": ticket_url,
    }


def _entry_vars(entry) -> dict:
    """Variáveis de uma thread entry (resposta)."""
    author = entry.author
    return {
        "reply.body": entry.body or "",
        "reply_body": entry.body or "",
        "body": entry.body or "",
        "agent.name": (author.nome_completo or author.email) if author else "",
        "agent_name": (author.nome_completo or author.email) if author else "",
        "agent.email": author.email if author else "",
        "agent_email": author.email if author else "",
    }


def _render_template_str(template_str: str, variables: dict) -> str:
    """Substitui %{variavel} e {variavel} no template pelos valores correspondentes."""
    if not template_str:
        return ""

    # 1. Substitui no formato %{variavel}
    def replacer_percent(match):
        key = match.group(1).strip()
        return str(variables.get(key, match.group(0)))
    res = re.sub(r"%\{([^}]+)\}", replacer_percent, template_str)

    # 2. Substitui no formato {variavel} se a chave existir no dicionário
    def replacer_bracket(match):
        key = match.group(1).strip()
        if key in variables:
            return str(variables[key])
        return match.group(0)
    # Apenas substitui se não tiver o % antes (para evitar duplicidade)
    res = re.sub(r"(?<!%)\{([^}]+)\}", replacer_bracket, res)

    return res


# ---------------------------------------------------------------------------
# Lookup de template
# ---------------------------------------------------------------------------

def _get_email_template(event_key: str):
    """Busca o template de e-mail pelo evento. Retorna None se não houver."""
    from modules.sollus_tickets.models import SollusTicketEmailTemplate
    return (
        SollusTicketEmailTemplate.query
        .filter_by(event_key=event_key, is_active=True)
        .first()
    )


def _send(
    recipients: list[str],
    subject: str,
    html_body: str,
    text_body: str = "",
    reply_to: Optional[str] = None,
    extra_headers: Optional[dict] = None,
    attachments=None,
) -> bool:
    """Enfileira o e-mail na tabela SollusEmailQueue para envio posterior."""
    recipients = [r.strip() for r in recipients if r and r.strip()]
    if not recipients:
        current_app.logger.debug("[tickets_mail] sem destinatários — ignorado.")
        return False

    try:
        from modules.sollus_tickets.models import SollusEmailQueue
        import json

        att_ids = ""
        if attachments:
            att_ids = ",".join(str(att.id) for att in attachments if getattr(att, "id", None))

        headers_str = ""
        if extra_headers:
            headers_str = json.dumps(extra_headers)

        email_item = SollusEmailQueue(
            recipients=",".join(recipients),
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            reply_to=reply_to,
            extra_headers=headers_str,
            attachment_ids=att_ids,
            status="pending",
            attempts=0
        )
        db.session.add(email_item)
        db.session.commit()
        current_app.logger.info("[tickets_mail] e-mail '%s' enfileirado para %s", subject, recipients)
        return True
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("[tickets_mail] falha ao enfileirar e-mail '%s': %s", subject, exc)
        return False


def process_email_queue(app) -> int:
    """
    Processa a fila de e-mails pendentes.
    Deve ser executado dentro do contexto do Flask app.
    """
    from modules.sollus_tickets.models import SollusEmailQueue, SollusTicketAttachment
    import json
    from pathlib import Path
    
    if not app.config.get("MAIL_ENABLED", True):
        return 0

    sent_count = 0
    try:
        pending_items = (
            SollusEmailQueue.query
            .filter(
                SollusEmailQueue.status.in_(["pending", "failed"]),
                SollusEmailQueue.attempts < 3
            )
            .order_by(SollusEmailQueue.id.asc())
            .limit(20)
            .all()
        )

        if not pending_items:
            return 0

        for item in pending_items:
            item.attempts += 1
            recipients = [r.strip() for r in item.recipients.split(",") if r.strip()]
            if not recipients:
                item.status = "skipped"
                item.last_error = "Sem destinatarios validos"
                db.session.commit()
                continue

            try:
                msg = Message(subject=item.subject, recipients=recipients)
                msg.html = item.html_body
                msg.body = item.text_body or re.sub(r"<[^>]+>", "", item.html_body)

                effective_reply_to = item.reply_to or app.config.get("MAIL_REPLY_TO")
                if effective_reply_to:
                    msg.reply_to = effective_reply_to

                if item.extra_headers:
                    try:
                        headers_dict = json.loads(item.extra_headers)
                        # Remove and set Message-ID if present in extra headers
                        msg_id_key = next((k for k in headers_dict if k.lower() == "message-id"), None)
                        if msg_id_key:
                            msg.message_id = headers_dict[msg_id_key].strip()
                            del headers_dict[msg_id_key]
                        msg.extra_headers = headers_dict
                    except Exception:
                        pass

                # Anexa arquivos se houver
                if item.attachment_ids:
                    att_ids = [int(x) for x in item.attachment_ids.split(",") if x.strip().isdigit()]
                    if att_ids:
                        attachments = SollusTicketAttachment.query.filter(SollusTicketAttachment.id.in_(att_ids)).all()
                        uploads_dir = Path(app.config.get("UPLOADS_DIR", "uploads"))
                        for att in attachments:
                            if att.content_type and ";inline" in att.content_type:
                                continue
                            file_path = uploads_dir / att.storage_path if att.storage_path else None
                            if file_path and file_path.exists():
                                with open(file_path, "rb") as f:
                                    data = f.read()
                                mime = (att.content_type or "application/octet-stream").split(";")[0]
                                msg.attach(
                                    filename=att.original_name,
                                    content_type=mime,
                                    data=data,
                                )

                mail.send(msg)
                item.status = "sent"
                item.last_error = None
                sent_count += 1

            except Exception as exc:
                db.session.rollback()
                app.logger.exception("[tickets_mail_queue] Erro ao enviar item %s: %s", item.id, exc)
                item.status = "failed"
                item.last_error = str(exc)

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

    except Exception as exc:
        db.session.rollback()
        app.logger.exception("[tickets_mail_queue] Erro geral ao processar a fila")

    return sent_count

# ---------------------------------------------------------------------------
# Função pública: resposta do agente
# ---------------------------------------------------------------------------

def _strip_external_ticket_links(html_body: str, text_body: str) -> tuple[str, str]:
    """Remove o link 'Abrir ticket' e referências a {ticket_url} dos e-mails externos.

    Funciona em dois cenários:
    1. Template ainda NÃO renderizado: remove links cujo href contém {ticket_url}
    2. Template JÁ renderizado: remove links cujo texto visível é "Abrir ticket/chamado"
    """
    if html_body:
        # Caso 1 — remove parágrafos com link {ticket_url} (antes do render)
        html_body = re.sub(
            r'<p>\s*<a[^>]*href=["\']%?\{ticket(?:_url|\.staff_link)\}["\'][^>]*>.*?</a>\s*</p>',
            '',
            html_body,
            flags=re.IGNORECASE | re.DOTALL
        )
        # Caso 1 — remove tags de link avulsas com {ticket_url}
        html_body = re.sub(
            r'<a[^>]*href=["\']%?\{ticket(?:_url|\.staff_link)\}["\'][^>]*>.*?</a>',
            '',
            html_body,
            flags=re.IGNORECASE | re.DOTALL
        )
        # Caso 2 — remove parágrafos cujo link tem texto "Abrir ticket/chamado" (após render)
        html_body = re.sub(
            r'<p>\s*<a[^>]*>\s*Abrir\s+(?:ticket|chamado)\s*</a>\s*</p>',
            '',
            html_body,
            flags=re.IGNORECASE
        )
        # Caso 2 — remove tags de link avulsas com texto "Abrir ticket/chamado"
        html_body = re.sub(
            r'<a[^>]*>\s*Abrir\s+(?:ticket|chamado)\s*</a>',
            '',
            html_body,
            flags=re.IGNORECASE
        )
    if text_body:
        # Remove referências textuais do link (antes e depois do render)
        text_body = re.sub(r'Abrir\s+(?:ticket|chamado):?\s*%?\{ticket(?:_url|\.staff_link)\}', '', text_body, flags=re.IGNORECASE)
        text_body = re.sub(r'%?\{ticket(?:_url|\.staff_link)\}', '', text_body, flags=re.IGNORECASE)
        text_body = re.sub(r'Abrir\s+(?:ticket|chamado)\s*', '', text_body, flags=re.IGNORECASE)
    return html_body, text_body


def send_ticket_reply_email(ticket, entry) -> bool:
    """
    Dispara e-mail de resposta do agente para o solicitante do ticket.
    Usa o template de evento 'ticket.reply' ou fallback genérico.
    Só envia para respostas públicas (não notas internas).
    """
    if getattr(entry, "visibility", "public") == "internal":
        return False  # notas internas não são enviadas por e-mail

    # Destinatário: e-mail do contact ou do requester
    recipient_email = None
    if ticket.contact and ticket.contact.email:
        recipient_email = ticket.contact.email
    elif ticket.requester and ticket.requester.email:
        recipient_email = ticket.requester.email

    # Adicionar colaboradores
    recipients = []
    if recipient_email:
        recipients.append(recipient_email)
    for collab in getattr(ticket, "collaborators", []):
        if collab.contact and collab.contact.email:
            email = collab.contact.email
            if email not in recipients:
                recipients.append(email)

    if not recipients:
        return False

    variables = {**_ticket_vars(ticket), **_entry_vars(entry)}
    tmpl = _get_email_template("ticket.reply") or _get_email_template("reply")

    if tmpl:
        # Strip external ticket links from the template before formatting
        body_html_clean, body_text_clean = _strip_external_ticket_links(tmpl.body_html, tmpl.body_text or "")
        
        subject = _render_template_str(tmpl.subject, variables)
        html_body = _render_template_str(body_html_clean, variables)
        text_body = _render_template_str(body_text_clean, variables)
    else:
        # Fallback se não houver template cadastrado
        subject = f"[#{variables['ticket.number']}] {variables['ticket.subject']}"
        html_body = (
            f"<p>Olá, <strong>{variables['requester.name'] or 'cliente'}</strong>.</p>"
            f"<p>Uma atualização foi adicionada ao seu chamado <strong>#{variables['ticket.number']}</strong> — "
            f"<em>{variables['ticket.subject']}</em>:</p>"
            f"<blockquote style='border-left:4px solid #ccc;padding:8px 16px;margin:0;color:#555'>"
            f"{entry.body}"
            f"</blockquote>"
            f"<p>Atenciosamente,<br><strong>{variables['agent.name'] or 'Equipe de Suporte'}</strong></p>"
        )
        text_body = f"Atualização no chamado #{variables['ticket.number']}:\n\n{entry.body}"

    # Cabeçalho de thread de e-mail para encadeamento
    extra_headers = {}
    if ticket.number:
        extra_headers["References"] = f"<ticket-{ticket.number}@sollus>"
        extra_headers["In-Reply-To"] = f"<ticket-{ticket.number}@sollus>"

    # Coleta os anexos da entry (excluindo inline/assinaturas)
    entry_attachments = [
        att for att in getattr(entry, "attachments", [])
        if att.content_type is None or ";inline" not in att.content_type
    ]

    return _send(recipients, subject, html_body, text_body, extra_headers=extra_headers, attachments=entry_attachments)


# ---------------------------------------------------------------------------
# Função pública: auto-resposta ao abrir ticket
# ---------------------------------------------------------------------------

def send_ticket_autoresponse(ticket) -> bool:
    """
    Dispara e-mail de confirmação ao solicitante quando um novo ticket é criado.
    Usa template 'new_ticket_autoresponse' ou fallback genérico.
    """
    recipient_email = None
    if ticket.contact and ticket.contact.email:
        recipient_email = ticket.contact.email
    elif ticket.requester and ticket.requester.email:
        recipient_email = ticket.requester.email

    if not recipient_email:
        return False

    variables = _ticket_vars(ticket)
    tmpl = _get_email_template("new_ticket_autoresponse") or _get_email_template("new.ticket.autoresp")

    if tmpl:
        # Strip external ticket links from the template before formatting
        body_html_clean, body_text_clean = _strip_external_ticket_links(tmpl.body_html, tmpl.body_text or "")
        
        subject = _render_template_str(tmpl.subject, variables)
        html_body = _render_template_str(body_html_clean, variables)
        text_body = _render_template_str(body_text_clean, variables)
    else:
        subject = f"Seu chamado foi aberto: #{variables['ticket.number']} — {variables['ticket.subject']}"
        html_body = (
            f"<p>Olá, <strong>{variables['requester.name'] or 'cliente'}</strong>.</p>"
            f"<p>Seu chamado foi recebido com sucesso e está sendo analisado pela nossa equipe.</p>"
            f"<table style='border-collapse:collapse;width:100%;max-width:500px'>"
            f"<tr><td style='padding:6px;font-weight:bold'>Número:</td><td style='padding:6px'>#{variables['ticket.number']}</td></tr>"
            f"<tr><td style='padding:6px;font-weight:bold'>Assunto:</td><td style='padding:6px'>{variables['ticket.subject']}</td></tr>"
            f"<tr><td style='padding:6px;font-weight:bold'>Departamento:</td><td style='padding:6px'>{variables['ticket.department']}</td></tr>"
            f"<tr><td style='padding:6px;font-weight:bold'>Prioridade:</td><td style='padding:6px'>{variables['ticket.priority']}</td></tr>"
            f"<tr><td style='padding:6px;font-weight:bold'>Aberto em:</td><td style='padding:6px'>{variables['ticket.created_at']}</td></tr>"
            f"</table>"
            f"<p>Responderemos em breve. Guarde o número <strong>#{variables['ticket.number']}</strong> para acompanhar.</p>"
            f"<p>Atenciosamente,<br><strong>Equipe de Suporte</strong></p>"
        )
        text_body = (
            f"Chamado #{variables['ticket.number']} recebido.\n"
            f"Assunto: {variables['ticket.subject']}\n"
            f"Aberto em: {variables['ticket.created_at']}\n\n"
            "Responderemos em breve."
        )

    return _send([recipient_email], subject, html_body, text_body)


# ---------------------------------------------------------------------------
# Função pública: alerta de SLA vencida
# ---------------------------------------------------------------------------

def send_sla_alert_email(ticket) -> bool:
    """
    Dispara alerta de SLA vencida para o responsável pelo ticket.
    Usa template 'ticket.overlimit' ou fallback.
    """
    # Limitar envio de e-mails a 2 vezes por dia: uma de manhã e uma de tarde (horário local)
    local_tz = get_local_timezone()
    now_local = datetime.now(local_tz)

    if now_local.hour < 12:
        period_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        period_end_local = now_local.replace(hour=11, minute=59, second=59, microsecond=999999)
    else:
        period_start_local = now_local.replace(hour=12, minute=0, second=0, microsecond=0)
        period_end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)

    period_start_utc = period_start_local.astimezone(timezone.utc).replace(tzinfo=None)
    period_end_utc = period_end_local.astimezone(timezone.utc).replace(tzinfo=None)

    from modules.sollus_tickets.models import SollusTicketEvent

    already_sent = (
        SollusTicketEvent.query
        .filter(
            SollusTicketEvent.ticket_id == ticket.id,
            SollusTicketEvent.action == "sla_alert",
            SollusTicketEvent.created_at >= period_start_utc,
            SollusTicketEvent.created_at <= period_end_utc
        )
        .first()
    )
    if already_sent:
        return False

    recipients = []
    if ticket.assignee and ticket.assignee.email:
        recipients.append(ticket.assignee.email)
    # CC para manager do departamento
    if ticket.department:
        from modules.sollus_tickets.models import SollusTicketDepartmentAccess
        managers = (
            SollusTicketDepartmentAccess.query
            .filter_by(department_id=ticket.department.id, is_manager=True)
            .all()
        )
        for ma in managers:
            if ma.user and ma.user.email and ma.user.email not in recipients:
                recipients.append(ma.user.email)

    # Sempre incluir o diretor (Leonardo Santos) para receber alertas de SLA de todos os tickets
    director_email = "leonardo.santos@sollustecnologia.com"
    if director_email not in recipients:
        recipients.append(director_email)

    if not recipients:
        return False

    variables = _ticket_vars(ticket)
    overdue_since = ""
    if ticket.overdue_at:
        delta = datetime.now(timezone.utc).replace(tzinfo=None) - ticket.overdue_at
        hours = int(delta.total_seconds() // 3600)
        overdue_since = f"{hours}h em atraso"

    variables["sla.overdue_since"] = overdue_since

    tmpl = _get_email_template("ticket.overlimit") or _get_email_template("sla.alert")

    if tmpl:
        subject = _render_template_str(tmpl.subject, variables)
        html_body = _render_template_str(tmpl.body_html, variables)
        text_body = _render_template_str(tmpl.body_text or "", variables)
    else:
        subject = f"⚠️ SLA Vencida — #{variables['ticket.number']} ({overdue_since})"
        html_body = (
            f"<p>O ticket abaixo ultrapassou o prazo de SLA.</p>"
            f"<table style='border-collapse:collapse;width:100%;max-width:500px'>"
            f"<tr><td style='padding:6px;font-weight:bold'>Número:</td><td style='padding:6px'>#{variables['ticket.number']}</td></tr>"
            f"<tr><td style='padding:6px;font-weight:bold'>Assunto:</td><td style='padding:6px'>{variables['ticket.subject']}</td></tr>"
            f"<tr><td style='padding:6px;font-weight:bold'>Responsável:</td><td style='padding:6px'>{variables['assignee.name']}</td></tr>"
            f"<tr><td style='padding:6px;font-weight:bold'>Atraso:</td><td style='padding:6px;color:#c00'>{overdue_since}</td></tr>"
            f"</table>"
            f"<p>Por favor, aja imediatamente.</p>"
        )
        text_body = f"SLA vencida: #{variables['ticket.number']} — {variables['ticket.subject']} ({overdue_since})"

    sent = _send(recipients, subject, html_body, text_body)
    if sent:
        event = SollusTicketEvent(
            ticket_id=ticket.id,
            action="sla_alert",
            message=f"Alerta de SLA atrasada enviado para: {', '.join(recipients)}"
        )
        db.session.add(event)
        db.session.commit()
    return sent


# ---------------------------------------------------------------------------
# Job de alertas de SLA (chamado pelo scheduler)
# ---------------------------------------------------------------------------

def run_sla_alerts(app=None) -> int:
    """
    Varre todos os tickets abertos com SLA vencida e dispara e-mails de alerta.
    Retorna o número de alertas enviados.
    Deve ser chamado dentro de app_context.
    """
    from modules.sollus_tickets.models import SollusTicket

    sent = 0
    try:
        overdue_tickets = (
            SollusTicket.query
            .filter(
                SollusTicket.overdue_at.isnot(None),
                SollusTicket.status_key.notin_(["closed", "resolved", "archived"]),
                SollusTicket.closed_at.is_(None),  # extra guard: never alert on closed tickets
            )
            .limit(100)
            .all()
        )
        for ticket in overdue_tickets:
            try:
                if send_sla_alert_email(ticket):
                    sent += 1
            except Exception:
                if app:
                    app.logger.exception("[sla_alert] erro no ticket %s", ticket.id)
    except Exception:
        if app:
            app.logger.exception("[sla_alert] erro ao buscar tickets com SLA vencida")
    return sent
