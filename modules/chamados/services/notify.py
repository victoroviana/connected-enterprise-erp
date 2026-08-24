# services/notify.py
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Iterable, List, Optional, Dict

from flask import current_app, url_for, request
from markupsafe import escape

from modules.audit.utils import write_audit_external

def _pt_status(s: Optional[str]) -> str:
    s = (s or '').lower()
    return {'open': 'Aberto', 'in_progress': 'Em andamento', 'closed': 'Finalizado'}.get(s, '—')

def _pt_priority(p: Optional[str]) -> str:
    p = (p or '').lower()
    return {'low': 'Baixa', 'medium': 'Média', 'high': 'Alta', 'urgent': 'Urgente'}.get(p, '—')

def _base_url() -> str:
    # Usa MAIL_BASE_URL se houver; senão, tenta derivar do request
    cfg = current_app.config
    return (cfg.get('MAIL_BASE_URL') or request.url_root.rstrip('/')).rstrip('/')

def _uniq_emails(items: Iterable[str]) -> List[str]:
    out, seen = [], set()
    for e in items:
        if not e:
            continue
        e = e.strip().lower()
        if e and e not in seen:
            seen.add(e)
            out.append(e)
    return out

def recipients_for_ticket(ticket, *, include_actor: bool, actor=None) -> List[str]:
    """Coleta e-mails de pessoas 'vinculadas' ao ticket:
       - solicitante (ticket.user)
       - atendente (ticket.assignee, se existir)
       - autores de mensagens anteriores (se houver relação/consulta)
       Remove o ator (quem executou a ação) quando include_actor=False.
    """
    emails: List[str] = []

    # solicitante
    try:
        if getattr(ticket, 'user', None) and getattr(ticket.user, 'email', None):
            emails.append(ticket.user.email)
    except Exception:
        pass

    # atendente
    try:
        assignee = getattr(ticket, 'assignee', None)
        if assignee and getattr(assignee, 'email', None):
            emails.append(assignee.email)
    except Exception:
        pass

    # autores de mensagens
    try:
        msgs = getattr(ticket, 'messages', None)
        if msgs is None:
            # busca direta para evitar depender do relacionamento
            from modules.chamados.models import TicketMessage
            msgs = TicketMessage.query.filter_by(ticket_id=ticket.id).all()
        for m in msgs or []:
            if getattr(m, 'author', None) and getattr(m.author, 'email', None):
                emails.append(m.author.email)
    except Exception:
        pass

    # remove o ator, se for o caso
    if not include_actor and actor and getattr(actor, 'email', None):
        actor_email = actor.email.strip().lower()
        emails = [e for e in emails if e.strip().lower() != actor_email]

    return _uniq_emails(emails)

def send_email(subject: str, recipients: List[str], html_body: str, text_body: Optional[str] = None) -> None:
    cfg = current_app.config
    if not cfg.get('MAIL_ENABLED', False):
        current_app.logger.info('MAIL_DISABLED: %s -> %s', subject, recipients)
        try:
            write_audit_external(
                entity_type="chamados_email",
                action="email_skip",
                message="Envio de email de chamado ignorado: MAIL_ENABLED falso.",
                after={"assunto": subject, "to": recipients, "status": "disabled"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email de chamado (skip).")
        return
    if not recipients:
        current_app.logger.info('MAIL_SKIP_EMPTY_RECIPIENTS: %s', subject)
        try:
            write_audit_external(
                entity_type="chamados_email",
                action="email_skip",
                message="Envio de email de chamado ignorado: sem destinatarios.",
                after={"assunto": subject, "to": [], "status": "no_recipients"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email de chamado (sem destinatarios).")
        return

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = cfg.get('MAIL_DEFAULT_SENDER', 'noreply@example.com')
    msg['To'] = ', '.join(recipients)

    if text_body:
        msg.set_content(text_body)
    # Parte HTML
    msg.add_alternative(html_body, subtype='html')

    try:
        with smtplib.SMTP(cfg.get('MAIL_SERVER', 'localhost'), cfg.get('MAIL_PORT', 25), timeout=30) as smtp:
            if cfg.get('MAIL_USE_TLS', False):
                smtp.starttls()
            if cfg.get('MAIL_USERNAME') and cfg.get('MAIL_PASSWORD'):
                smtp.login(cfg['MAIL_USERNAME'], cfg['MAIL_PASSWORD'])
            smtp.send_message(msg)
        current_app.logger.info('MAIL_SENT "%s" -> %s', subject, recipients)
        try:
            write_audit_external(
                entity_type="chamados_email",
                action="email_send",
                message="Envio de email de chamado concluido.",
                after={"assunto": subject, "to": recipients, "status": "success"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email de chamado.")
    except Exception as e:
        current_app.logger.exception('MAIL_ERROR sending "%s" to %s: %s', subject, recipients, e)

def notify_ticket_event(ticket, *, action: str, actor=None, extra: Optional[Dict] = None) -> None:
    """action: 'created' | 'reply' | 'assigned' | 'status' | 'attachment'"""
    extra = extra or {}
    recips = recipients_for_ticket(ticket, include_actor=False, actor=actor)
    if not recips:
        return

    actor_name = (getattr(actor, 'name', None) or getattr(actor, 'email', None) or 'Sistema')
    base = _base_url()
    link = f"{base}{url_for('tickets.ticket_detail', ticket_id=ticket.id)}"

    ev_label = {
        'created': 'criado',
        'reply': 'atualizado com uma nova resposta',
        'assigned': 'atribuído',
        'status': 'atualizado',
        'attachment': 'atualizado com novo anexo',
    }.get(action, 'atualizado')

    subject = f"[Chamados] #{ticket.id} — {escape(ticket.title or 'Sem título')} ({_pt_status(getattr(ticket,'status',None))})"

    # Blocos opcionais
    extra_html = ""
    if action == 'reply' and 'body' in extra:
        body = escape(extra.get('body') or '')  # simples; pode enriquecer
        extra_html += f'<p><strong>Mensagem:</strong><br><div style="white-space:pre-wrap">{body}</div></p>'
    if action == 'assigned':
        assignee = getattr(ticket, 'assignee', None)
        who = escape(getattr(assignee, 'name', None) or getattr(assignee, 'email', None) or '—')
        extra_html += f'<p><strong>Novo atendente:</strong> {who}</p>'
    if action == 'status':
        extra_html += f'<p><strong>Novo status:</strong> {_pt_status(getattr(ticket,"status",None))}</p>'
    if action == 'attachment' and 'filename' in extra:
        extra_html += f'<p><strong>Anexo:</strong> {escape(extra["filename"])}</p>'

    html = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif">
      <p>Olá,</p>
      <p>O chamado <strong>#{ticket.id} — {escape(ticket.title or 'Sem título')}</strong> foi {ev_label} por <strong>{escape(actor_name)}</strong>.</p>

      <table cellpadding="6" cellspacing="0" style="border-collapse:collapse">
        <tr><td><strong>Status</strong></td><td>{_pt_status(getattr(ticket,'status',None))}</td></tr>
        <tr><td><strong>Prioridade</strong></td><td>{_pt_priority(getattr(ticket,'priority',None))}</td></tr>
        <tr><td><strong>Solicitante</strong></td><td>{escape(getattr(getattr(ticket,'user',None),'name',None) or getattr(getattr(ticket,'user',None),'email',None) or '—')}</td></tr>
        <tr><td><strong>Atendente</strong></td><td>{escape(getattr(getattr(ticket,'assignee',None),'name',None) or getattr(getattr(ticket,'assignee',None),'email',None) or '—')}</td></tr>
      </table>

      {extra_html}

      <p><a href="{link}">Abrir o chamado no sistema</a></p>
      <hr>
      <small>Mensagem automática do sistema de chamados.</small>
    </div>
    """

    text = (
        f"Chamado #{ticket.id} — {ticket.title or 'Sem título'}\n"
        f"Ação: {ev_label} por {actor_name}\n"
        f"Status: {_pt_status(getattr(ticket,'status',None))}\n"
        f"Prioridade: {_pt_priority(getattr(ticket,'priority',None))}\n"
        f"Abrir: {link}\n"
    )

    send_email(subject, recips, html, text)

