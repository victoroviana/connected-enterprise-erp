from __future__ import annotations

import html
import io
import os
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Sequence

from PIL import Image
from flask import current_app

from modules.propostas.gerar_proposta import render_proposta_html_pdf
from modules.audit.utils import write_audit_external


def _resolve_mail_settings() -> dict[str, object]:
    config = current_app.config
    host = config.get("MAIL_SERVER") or config.get("EMAIL_SMTP_SERVER")
    if not host:
        raise RuntimeError("Configuração MAIL_SERVER ausente para envio de e-mail.")

    sender = config.get("MAIL_SENDER") or config.get("MAIL_DEFAULT_SENDER")
    if not sender:
        raise RuntimeError("Configuração MAIL_SENDER ausente para envio de e-mail.")

    use_ssl = bool(config.get("MAIL_USE_SSL", False))
    use_tls = bool(config.get("MAIL_USE_TLS", not use_ssl))
    port = config.get("MAIL_PORT")
    if not port:
        port = 465 if use_ssl else (587 if use_tls else 25)

    return {
        "host": host,
        "sender": sender,
        "use_ssl": use_ssl,
        "use_tls": use_tls,
        "port": port,
        "username": config.get("MAIL_USERNAME"),
        "password": config.get("MAIL_PASSWORD"),
        "reply_to": config.get("MAIL_REPLY_TO"),
    }


def _default_email_body(proposta, corpo_email: str) -> tuple[str, str]:
    corpo = (corpo_email or "").strip() or (
        f"Ola {proposta.client_name},\n\n"
        "Segue em anexo a proposta comercial referente ao nosso atendimento.\n\n"
        "Fico a disposicao para duvidas."
    )
    plain_body = corpo
    html_body = "<p>" + "<br>".join(html.escape(plain_body).splitlines()) + "</p>"
    return plain_body, html_body


def _append_signature_if_available(proposta, message: EmailMessage, html_body: str) -> str:
    signature_rel = getattr(getattr(proposta, "usuario", None), "signature_path", None)
    if not signature_rel:
        return html_body

    signature_abs = os.path.join(current_app.static_folder, signature_rel)
    if not os.path.exists(signature_abs):
        return html_body

    signature_cid = make_msgid()
    with Image.open(signature_abs) as sig_img:
        sig_img = sig_img.convert("RGBA")
        sig_img.thumbnail((720, 260), Image.LANCZOS)
        buffer = io.BytesIO()
        sig_img.save(buffer, format="PNG", optimize=True)
        signature_data = buffer.getvalue()

    html_body += (
        "\n"
        "<p style=\"margin-top:16px;\"><img src=\"cid:{cid}\" alt=\"Assinatura\" "
        "width=\"700\" style=\"max-width:700px;height:auto;display:block;\"></p>"
    ).format(cid=signature_cid[1:-1])

    # Replace the HTML alternative with the updated content and attach inline image
    message.get_payload()[-1].set_content(html_body, subtype="html")
    message.get_payload()[-1].add_related(signature_data, maintype="image", subtype="png", cid=signature_cid)
    return html_body


def send_proposal_email(
    proposta,
    corpo_email: str,
    cc_list: Sequence[str],
    *,
    pdf_bytes: bytes | None = None,
    template_relpath: str | None = None,
    context: dict | None = None,
) -> None:
    settings = _resolve_mail_settings()

    if pdf_bytes is None:
        if template_relpath is None or context is None:
            raise ValueError("É necessário fornecer o PDF ou o contexto para gerar o anexo da proposta.")
        pdf_bytes = render_proposta_html_pdf(template_relpath, context)

    msg = EmailMessage()
    msg["Subject"] = proposta.filename or "Proposta Comercial"
    msg["From"] = settings["sender"]
    msg["To"] = proposta.email
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    if settings["reply_to"]:
        msg["Reply-To"] = settings["reply_to"]

    plain_body, html_body = _default_email_body(proposta, corpo_email)
    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype="html")
    html_body = _append_signature_if_available(proposta, msg, html_body)

    filename = (proposta.filename or "proposta").strip() or "proposta"
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=f"{filename}.pdf",
    )

    if settings["use_ssl"]:
        server = smtplib.SMTP_SSL(settings["host"], settings["port"])
    else:
        server = smtplib.SMTP(settings["host"], settings["port"])

    try:
        if settings["use_tls"] and not settings["use_ssl"]:
            server.starttls()
        if settings["username"]:
            server.login(settings["username"], settings["password"] or "")
        server.send_message(msg)
        try:
            write_audit_external(
                entity_type="propostas_email",
                entity_id=getattr(proposta, "id", None),
                action="email_send",
                message="Envio de proposta por email concluido.",
                after={
                    "assunto": msg.get("Subject"),
                    "to": proposta.email,
                    "cc": list(cc_list or []),
                    "status": "success",
                },
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de proposta por email.")
    except Exception as exc:
        try:
            write_audit_external(
                entity_type="propostas_email",
                entity_id=getattr(proposta, "id", None),
                action="email_error",
                message="Falha ao enviar proposta por email.",
                after={
                    "assunto": msg.get("Subject"),
                    "to": proposta.email,
                    "cc": list(cc_list or []),
                    "status": "error",
                    "erro": str(exc),
                },
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar erro de envio de proposta.")
        raise
    finally:  # pragma: no cover - defensive cleanup
        try:
            server.quit()
        except Exception:
            pass
