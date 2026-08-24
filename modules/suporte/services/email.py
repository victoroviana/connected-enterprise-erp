"""Envio de e-mails relacionados aos atendimentos de suporte."""
from __future__ import annotations

from datetime import datetime

from flask import current_app
from flask_mail import Message

from extensions import mail
from modules.audit.utils import write_audit_external


def send_atendimento_concluido_email(entry) -> bool:
    """Envia e-mail de conclusão do atendimento para o cliente e equipe administrativa.

    Destinatários: e-mail do registro (entry.email) + lista SUPPORT_EMAIL_CC do .env.
    """
    if not entry.email:
        return False

    subject = f"Atendimento concluído - {entry.cliente or ''}".strip()
    cc_list = current_app.config.get(
        "SUPPORT_EMAIL_CC",
        [
            "suporte@example.com",
            "adm@example.com",
        ],
    )

    body_lines = [
        f"Atendimento concluído por: {entry.assigned_user.nome_completo if entry.assigned_user else '—'}",
        f"Cliente: {entry.cliente or '—'}",
        f"OS de Entrada: {entry.os_entrada or '—'}",
        f"Sistema: {entry.sistema or '—'}",
        f"Resumo:\n{entry.resumo_atendimento or entry.descricao or 'Sem descrição.'}",
    ]
    body = "\n\n".join(body_lines)

    try:
        msg = Message(subject=subject or "Atendimento concluído", recipients=[entry.email], cc=cc_list)
        msg.body = body
        msg.html = body.replace("\n", "<br>")
        mail.send(msg)
        try:
            write_audit_external(
                entity_type="suporte_email",
                action="email_send",
                message="E-mail de conclusão de atendimento enviado.",
                after={"assunto": subject, "to": [entry.email], "cc": cc_list, "status": "success"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de e-mail de conclusão de atendimento.")
        return True
    except Exception:
        current_app.logger.exception("Falha ao enviar e-mail de atendimento concluído")
        try:
            write_audit_external(
                entity_type="suporte_email",
                action="email_error",
                message="Falha ao enviar e-mail de conclusão de atendimento.",
                after={"assunto": subject, "to": [entry.email], "cc": cc_list, "status": "error"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar erro no e-mail de conclusão de atendimento.")
        return False


def _format_br_date(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%d/%m/%Y")
        except Exception:
            pass
    return str(value) if value else "-"


def send_chamado_satisfacao_email(
    *,
    email: str,
    cliente: str | None,
    data_atendimento,
    hora_entrada: str | None,
    hora_saida: str | None,
    tecnico: str | None,
    quem_atendeu: str | None,
    descricao: str | None,
    link: str,
) -> bool:
    if not email or not link:
        return False

    subject = "Pesquisa de Satisfação - Sollus Tecnologia"
    data_label = _format_br_date(data_atendimento)
    periodo = f"Entrada: {hora_entrada or '-'} - Saída: {hora_saida or '-'}"

    body = f"""
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background-color: #ffffff;
                margin: 0;
                padding: 40px 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding: 20px 40px;
                box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
                border-radius: 8px;
            }}
            h3 {{
                color: #333;
                font-weight: 600;
                border-bottom: 2px solid #eee;
                padding-bottom: 10px;
                margin-bottom: 20px;
            }}
            ul {{
                padding-left: 0;
                list-style-type: none;
            }}
            li {{
                margin-bottom: 10px;
                color: #555;
            }}
            strong {{
                color: #333;
            }}
            a.btn {{
                display: inline-block;
                padding: 10px 20px;
                color: #ffffff;
                background-color: #007BFF;
                border-radius: 4px;
                text-decoration: none;
                font-weight: 600;
                margin-top: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h3>Detalhes do Seu Atendimento:</h3>
            <div class="details">
                <ul>
                    <li>Nome do cliente: <strong>{cliente or '-'}</strong></li>
                    <li>Data do atendimento: <strong>{data_label}</strong></li>
                    <li>Período: <strong>{periodo}</strong></li>
                    <li>Resumo do atendimento: <strong>{descricao or 'Sem descrição.'}</strong></li>
                    <li>Técnico Responsável: <strong>{tecnico or '-'}</strong></li>
                    <li>Responsável no local: <strong>{quem_atendeu or '-'}</strong></li>
                </ul>
            </div>
            <p>Por favor, <a href="{link}" class="btn">clique aqui</a> para responder nossa pesquisa de satisfação.</p>
            <p class="mt-2">Agradecemos sua colaboração e estamos sempre à disposição para qualquer necessidade!</p>
            <p class="mt-4">Atenciosamente,</p>
            <p>Equipe Sollus Tecnologia</p>
        </div>
    </body>
    </html>
    """

    try:
        msg = Message(subject=subject, recipients=[email])
        msg.body = body.replace("<br>", "\n")
        msg.html = body
        mail.send(msg)
        return True
    except Exception:
        current_app.logger.exception("Falha ao enviar e-mail de pesquisa de satisfação.")
        return False

def send_atendimento_meet_email(entry, recipients) -> bool:
    recipient_list = [email for email in (recipients or []) if email]
    if not recipient_list or not entry or not entry.meet_link:
        try:
            write_audit_external(
                entity_type="suporte_email",
                action="email_skip",
                message="Envio de email do Meet ignorado: dados incompletos.",
                after={
                    "to": recipient_list,
                    "status": "missing_data",
                    "has_entry": bool(entry),
                    "has_meet_link": bool(getattr(entry, "meet_link", None)) if entry else False,
                },
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email do Meet (skip).")
        return False

    start_label = "-"
    if isinstance(entry.meet_start, datetime):
        start_label = entry.meet_start.strftime("%d/%m/%Y %H:%M")

    subject = f"Reuniao de suporte - {entry.cliente or ''}".strip()
    body_lines = [
        "Segue o link da reuniao no Google Meet.",
        f"Cliente: {entry.cliente or '-'}",
        f"Tipo: {entry.tipo_atendimento or '-'}",
        f"OS de Entrada: {entry.os_entrada or '-'}",
        f"Data e hora: {start_label}",
        f"Link do Meet: {entry.meet_link}",
    ]
    body = "\n\n".join(body_lines)

    try:
        msg = Message(subject=subject or "Reuniao de suporte", recipients=recipient_list)
        msg.body = body
        msg.html = body.replace("\n", "<br>")
        mail.send(msg)
        try:
            write_audit_external(
                entity_type="suporte_email",
                action="email_send",
                message="Envio de email do Meet concluido.",
                after={"assunto": subject, "to": recipient_list, "status": "success"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email do Meet.")
        return True
    except Exception:
        current_app.logger.exception("Falha ao enviar e-mail do Meet")
        try:
            write_audit_external(
                entity_type="suporte_email",
                action="email_error",
                message="Falha ao enviar email do Meet.",
                after={"assunto": subject, "to": recipient_list, "status": "error"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar erro no email do Meet.")
        return False
