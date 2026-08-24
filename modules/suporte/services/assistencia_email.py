"""Legacy-style email notifications for assistencia tecnica."""
from __future__ import annotations

from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr
import smtplib
import ssl
from typing import Iterable

from flask import current_app

from modules.audit.utils import write_audit_external

_DEFAULT_HOST = "smtp.example.com"
_DEFAULT_PORT = 587
_DEFAULT_USERNAME = "notificacoes@example.com"
# _DEFAULT_PASSWORD removed - must be set via ASSISTENCIA_SMTP_PASSWORD or MAIL_PASSWORD env var
_DEFAULT_FROM_EMAIL = "assistencia@example.com"
_DEFAULT_FROM_NAME = "Assistência Técnica"
_DEFAULT_RECIPIENTS = ["tecnica@example.com"]


def _format_date_br(value: date | datetime | str | None) -> str:
    if not value:
        return "-"
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _build_text(lines: Iterable[str]) -> str:
    return "\n".join([line for line in lines if line is not None])


def _smtp_settings() -> dict:
    cfg = current_app.config
    return {
        "host": cfg.get("ASSISTENCIA_SMTP_HOST") or cfg.get("MAIL_SERVER") or _DEFAULT_HOST,
        "port": int(cfg.get("ASSISTENCIA_SMTP_PORT") or cfg.get("MAIL_PORT") or _DEFAULT_PORT),
        "username": cfg.get("ASSISTENCIA_SMTP_USERNAME") or cfg.get("MAIL_USERNAME") or _DEFAULT_USERNAME,
        "password": cfg.get("ASSISTENCIA_SMTP_PASSWORD") or cfg.get("MAIL_PASSWORD") or None,
        "from_email": cfg.get("ASSISTENCIA_FROM_EMAIL") or cfg.get("MAIL_DEFAULT_SENDER") or _DEFAULT_FROM_EMAIL,
        "from_name": cfg.get("ASSISTENCIA_FROM_NAME") or _DEFAULT_FROM_NAME,
        "recipients": cfg.get("ASSISTENCIA_EMAIL_TO") or _DEFAULT_RECIPIENTS,
        "use_tls": cfg.get("ASSISTENCIA_SMTP_USE_TLS") if cfg.get("ASSISTENCIA_SMTP_USE_TLS") is not None else cfg.get("MAIL_USE_TLS", True),
        "use_ssl": cfg.get("ASSISTENCIA_SMTP_USE_SSL") if cfg.get("ASSISTENCIA_SMTP_USE_SSL") is not None else cfg.get("MAIL_USE_SSL", False),
    }


def _send_html_email(subject: str, html_body: str, text_body: str | None = None) -> bool:
    if current_app.config.get("MAIL_ENABLED", True) is False:
        try:
            write_audit_external(
                entity_type="assistencia_email",
                action="email_skip",
                message="Envio de email de assistencia tecnica ignorado: MAIL_ENABLED falso.",
                after={"assunto": subject, "status": "disabled"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email de assistencia tecnica (skip).")
        return False

    settings = _smtp_settings()
    recipients = settings["recipients"]
    if isinstance(recipients, str):
        recipients = [recipients]
    recipients = [addr for addr in recipients if addr]
    if not recipients:
        try:
            write_audit_external(
                entity_type="assistencia_email",
                action="email_skip",
                message="Envio de email de assistencia tecnica ignorado: sem destinatarios.",
                after={"assunto": subject, "to": [], "status": "no_recipients"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email de assistencia tecnica (sem destinatarios).")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings["from_name"], settings["from_email"]))
    msg["To"] = ", ".join(recipients)

    text_payload = text_body or html_body.replace("<br>", "\n").replace("<br/>", "\n")
    msg.set_content(text_payload)
    msg.add_alternative(html_body, subtype="html")

    skip_tls_verify = str(current_app.config.get("MAIL_SKIP_TLS_VERIFY", "")).strip() == "1"
    context = ssl.create_default_context()
    if skip_tls_verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    try:
        use_ssl = settings.get("use_ssl", False) or settings["port"] == 465
        if use_ssl:
            smtp_client = smtplib.SMTP_SSL(settings["host"], settings["port"], context=context, timeout=30)
        else:
            smtp_client = smtplib.SMTP(settings["host"], settings["port"], timeout=30)

        with smtp_client as smtp:
            smtp.ehlo()
            if not use_ssl and settings["use_tls"]:
                smtp.starttls(context=context)
                smtp.ehlo()
            if settings["username"] and settings["password"]:
                smtp.login(settings["username"], settings["password"])
            smtp.send_message(msg)
        try:
            write_audit_external(
                entity_type="assistencia_email",
                action="email_send",
                message="Envio de email de assistencia tecnica concluido.",
                after={"assunto": subject, "to": recipients, "status": "success"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email de assistencia tecnica.")
        return True
    except Exception:
        current_app.logger.exception("Falha ao enviar e-mail de assistencia tecnica")
        try:
            write_audit_external(
                entity_type="assistencia_email",
                action="email_error",
                message="Falha ao enviar email de assistencia tecnica.",
                after={"assunto": subject, "to": recipients, "status": "error"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar erro no email de assistencia tecnica.")
        return False


def send_assistencia_update_email(tarefa, actor: str) -> bool:
    subject = "Atualização de Tarefa"
    data_fim = _format_date_br(getattr(tarefa, "data_fim", None))
    descricao = getattr(tarefa, "descricao", None) or "-"
    atualizacoes = getattr(tarefa, "atualizacoes", None) or "-"
    html_body = f"""<html>
    <head><title>Atualização de Tarefa</title></head>
    <body>
      <h1>Tarefa Atualizada, verifique e faça as ações necessárias:</h1>
      <ul>
        <li><strong>Nome da Empresa:</strong> {tarefa.nome}</li>
        <li><strong>Data Limite:</strong> {data_fim}</li>
        <li><strong>Departamento Responsável no Momento:</strong> {tarefa.departamento_responsavel}</li>
        <li><strong>Descrição:</strong> {descricao}</li>
        <li><strong>Atualizações:</strong> {atualizacoes}</li>
        <li><strong>Status do equipamento:</strong> {tarefa.status}</li>
        <li><strong>Ordem de Serviço:</strong> {tarefa.OS}</li>
        <li><strong>Status ORCAMENTO:</strong> {getattr(tarefa, 'ORCAMENTO', None) or '-'}</li>
        <li><strong>CONTRATO:</strong> {getattr(tarefa, 'CONTRATO', None) or '-'}</li>
        <li><strong>Modificado por:</strong> {actor}</li>
      </ul>
    </body>
    </html>"""

    text_lines = [
        "Tarefa Atualizada, verifique e faça as ações necessárias:",
        f"Nome da Empresa: {tarefa.nome}",
        f"Data Limite: {data_fim}",
        f"Departamento Responsável no Momento: {tarefa.departamento_responsavel}",
        f"Descrição: {descricao}",
        f"Atualizações: {atualizacoes}",
        f"Status do equipamento: {tarefa.status}",
        f"Ordem de Serviço: {tarefa.OS}",
        f"Status ORCAMENTO: {getattr(tarefa, 'ORCAMENTO', None) or '-'}",
        f"CONTRATO: {getattr(tarefa, 'CONTRATO', None) or '-'}",
        f"Modificado por: {actor}",
    ]
    return _send_html_email(subject, html_body, _build_text(text_lines))


def send_assistencia_fabrica_email(tarefa, actor: str) -> bool:
    subject = "Atualização de Tarefa"
    data_fim = _format_date_br(getattr(tarefa, "data_fim", None))
    data_envio = _format_date_br(getattr(tarefa, "data_envio", None))
    data_retorno = _format_date_br(getattr(tarefa, "data_retorno", None))
    atualizacoes = getattr(tarefa, "atualizacoes", None) or "-"
    html_body = f"""<html>
    <head><title>Atualização de Tarefa</title></head>
    <body>
      <h1>Equipamento enviado à fábrica, verifique se realmente foi enviado:</h1>
      <ul>
        <li><strong>Nome da Empresa:</strong> {tarefa.nome}</li>
        <li><strong>Data Fim:</strong> {data_fim}</li>
        <li><strong>Departamento Responsável:</strong> {tarefa.departamento_responsavel}</li>
        <li><strong>Status:</strong> {tarefa.status}</li>
        <li><strong>OS:</strong> {tarefa.OS}</li>
        <li><strong>ORCAMENTO:</strong> {getattr(tarefa, 'ORCAMENTO', None) or '-'}</li>
        <li><strong>CONTRATO:</strong> {getattr(tarefa, 'CONTRATO', None) or '-'}</li>
        <li><strong>Data Envio:</strong> {data_envio}</li>
        <li><strong>Data Retorno:</strong> {data_retorno}</li>
        <li><strong>Atualizacoes:</strong> {atualizacoes}</li>
        <li><strong>Modificado por:</strong> {actor}</li>
      </ul>
    </body>
    </html>"""

    text_lines = [
        "Equipamento Enviado a fabrica, verifique se realmente foi enviado:",
        f"Nome da Empresa: {tarefa.nome}",
        f"Data Fim: {data_fim}",
        f"Departamento Responsavel: {tarefa.departamento_responsavel}",
        f"Status: {tarefa.status}",
        f"OS: {tarefa.OS}",
        f"ORCAMENTO: {getattr(tarefa, 'ORCAMENTO', None) or '-'}",
        f"CONTRATO: {getattr(tarefa, 'CONTRATO', None) or '-'}",
        f"Data Envio: {data_envio}",
        f"Data Retorno: {data_retorno}",
        f"Atualizacoes: {atualizacoes}",
        f"Modificado por: {actor}",
    ]
    return _send_html_email(subject, html_body, _build_text(text_lines))
