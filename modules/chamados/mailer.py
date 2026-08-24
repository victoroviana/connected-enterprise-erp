"""SMTP helpers for chamados notifications."""
from __future__ import annotations

from typing import Iterable, Optional

from flask import current_app
from flask_mail import Message

from extensions import mail
from modules.audit.utils import write_audit_external


def enviar_email(
    destinatarios: Iterable[str],
    assunto: str,
    html_corpo: str,
    texto_corpo: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    sender: Optional[str] = None,
    reply_to: Optional[str] = None,
    attachments: Optional[Iterable] = None,
) -> bool:
    recipients = [email.strip() for email in destinatarios if email]
    if not recipients:
        try:
            write_audit_external(
                entity_type="chamados_email",
                action="email_skip",
                message="Envio de email de chamados ignorado: sem destinatarios.",
                after={"assunto": assunto, "to": [], "status": "no_recipients"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email de chamados (sem destinatarios).")
        return False

    if not current_app.config.get("MAIL_ENABLED", True):
        current_app.logger.info("[mail] MAIL_ENABLED desativado; ignorando envio '%s'", assunto)
        try:
            write_audit_external(
                entity_type="chamados_email",
                action="email_skip",
                message="Envio de email de chamados ignorado: MAIL_ENABLED falso.",
                after={"assunto": assunto, "to": recipients, "status": "disabled"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email de chamados (skip).")
        return True

    try:
        from modules.sollus_tickets.models import SollusEmailQueue
        from extensions import db
        import json

        headers_str = ""
        if headers:
            headers_str = json.dumps(headers)

        att_ids = ""
        if attachments:
            att_ids = ",".join(str(getattr(att, "id", att)) for att in attachments if att)

        email_item = SollusEmailQueue(
            recipients=",".join(recipients),
            subject=assunto,
            html_body=html_corpo,
            text_body=texto_corpo,
            reply_to=reply_to,
            extra_headers=headers_str,
            attachment_ids=att_ids if att_ids else None,
            status="pending",
            attempts=0
        )
        db.session.add(email_item)
        db.session.commit()

        try:
            write_audit_external(
                entity_type="chamados_email",
                action="email_queue",
                message="Email de chamados enfileirado.",
                after={"assunto": assunto, "to": recipients, "status": "pending"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar enfileiramento de email.")
        return True
    except Exception as exc:
        current_app.logger.exception("[mail] erro ao enfileirar '%s': %s", assunto, exc)
        try:
            write_audit_external(
                entity_type="chamados_email",
                action="email_error",
                message="Falha ao enfileirar email de chamados.",
                after={"assunto": assunto, "to": recipients, "status": "error"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar erro ao enfileirar email.")
        return False
