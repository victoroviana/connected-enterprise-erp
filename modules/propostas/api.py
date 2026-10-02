from __future__ import annotations

import os
import json
import base64
import smtplib
from datetime import datetime
from email.message import EmailMessage
import mimetypes
from socket import timeout as SocketTimeout
from typing import Callable

from flask import Blueprint, current_app, jsonify, request, session
from flask_login import login_required, current_user
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from extensions import csrf, executor

api_bp = Blueprint('api_bp', __name__, url_prefix='/api')   #  prefixo nico


class _CNPJNotFoundError(Exception):
    """Erro levantado quando o CNPJ no  encontrado na API pblica."""


class _CNPJServiceError(Exception):
    """Erro genrico para falhas na comunicao/decodificao da API."""


def _fetch_cnpj_payload(
    cnpj: str,
    *,
    opener: Callable[[Request, float], object] = urlopen,
    timeout: float = 6,
) -> dict:
    """Consulta a API de CNPJ usando apenas a biblioteca padro.

    Parameters
    ----------
    cnpj:
        Nmero do CNPJ normalizado (somente dgitos).
    opener:
        Funo compatvel com ``urllib.request.urlopen`` usada para facilitar testes.
    timeout:
        Tempo limite da requisio, em segundos.

    Returns
    -------
    dict
        Contedo JSON retornado pela API pblica.
    """

    req = Request(
        f'https://publica.cnpj.ws/cnpj/{cnpj}',
        headers={'Accept': 'application/json'}
    )

    try:
        with opener(req, timeout=timeout) as resp:  # type: ignore[arg-type]
            payload = resp.read()
            headers = getattr(resp, 'headers', None)
            charset = None
            if headers is not None and hasattr(headers, 'get_content_charset'):
                charset = headers.get_content_charset()
    except HTTPError as exc:
        if exc.code == 404:
            raise _CNPJNotFoundError from exc
        raise _CNPJServiceError from exc
    except (URLError, SocketTimeout) as exc:
        raise _CNPJServiceError from exc

    if not charset:
        charset = 'utf-8'

    try:
        text = payload.decode(charset)
    except (LookupError, UnicodeDecodeError) as exc:
        raise _CNPJServiceError from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise _CNPJServiceError from exc


@api_bp.route('/cnpj/<cnpj>', methods=['GET'])
@login_required
def consultar_cnpj(cnpj):
    cnpj = ''.join(filter(str.isdigit, cnpj))
    if len(cnpj) != 14:
        return jsonify(error='CNPJ invlido (14 dgitos).'), 400

    try:
        data = _fetch_cnpj_payload(cnpj)
    except _CNPJNotFoundError:
        return jsonify(error='CNPJ no encontrado.'), 404
    except _CNPJServiceError:
        return jsonify(error='Erro ao consultar API externa.'), 502

    return jsonify(
        company=data.get('razao_social', ''),
        cnpj=data.get('cnpj', ''),
        email=data.get('email', ''),
        telefone=data.get('ddd_telefone_1', '')
    )


@api_bp.route('/reportar_problema', methods=['POST'])
@csrf.exempt
def reportar_problema():
    """Recebe relato de erro/problema enviado pelo colaborador via popup da Sol (E-mail / WhatsApp)."""
    try:
        pagina = (request.form.get('pagina') or '').strip()
        acao = (request.form.get('acao') or '').strip()
        descricao = (request.form.get('descricao') or '').strip()
        canal = (request.form.get('canal') or 'email').strip().lower()

        # Obter identificação do colaborador
        colaborador_nome = "Colaborador"
        colaborador_email = "Não informado"
        try:
            if current_user and current_user.is_authenticated:
                colaborador_nome = getattr(current_user, 'nome_completo', None) or getattr(current_user, 'usuario', None) or "Colaborador"
                colaborador_email = getattr(current_user, 'email', None) or "Não informado"
            elif session.get("nome"):
                colaborador_nome = session.get("nome")
                colaborador_email = session.get("email") or "Não informado"
            elif session.get("usuario"):
                colaborador_nome = session.get("usuario")
        except Exception:
            pass

        # Validar campos básicos
        if not descricao and not acao:
            return jsonify(ok=False, message="Por favor, preencha o que você estava fazendo e a descrição do problema."), 400

        # Tratar print da tela
        image_bytes = None
        image_filename = None
        image_url = None
        maintype = "image"
        subtype = "png"

        uploads_dir = os.path.join(current_app.static_folder or "static", "uploads", "reportes_problemas")
        os.makedirs(uploads_dir, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        print_file = request.files.get("print")
        print_base64 = request.form.get("print_base64")

        if print_file and print_file.filename:
            orig_name = print_file.filename
            ext = os.path.splitext(orig_name)[1].lower() or ".png"
            safe_filename = f"print_{timestamp_str}_{os.urandom(3).hex()}{ext}"
            file_path = os.path.join(uploads_dir, safe_filename)
            print_file.save(file_path)
            with open(file_path, "rb") as f:
                image_bytes = f.read()
            image_filename = safe_filename
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type:
                parts = mime_type.split("/")
                maintype, subtype = parts[0], parts[1]
            base_url = current_app.config.get("MAIL_BASE_URL") or "http://localhost:6001"
            image_url = f"{base_url.rstrip('/')}/static/uploads/reportes_problemas/{safe_filename}"
        elif print_base64 and "base64," in print_base64:
            header, encoded = print_base64.split("base64,", 1)
            ext = ".png"
            if "image/jpeg" in header:
                ext = ".jpg"
                maintype, subtype = "image", "jpeg"
            elif "image/webp" in header:
                ext = ".webp"
                maintype, subtype = "image", "webp"
            safe_filename = f"print_{timestamp_str}_{os.urandom(3).hex()}{ext}"
            file_path = os.path.join(uploads_dir, safe_filename)
            image_bytes = base64.b64decode(encoded)
            with open(file_path, "wb") as f:
                f.write(image_bytes)
            image_filename = safe_filename
            base_url = current_app.config.get("MAIL_BASE_URL") or "http://localhost:6001"
            image_url = f"{base_url.rstrip('/')}/static/uploads/reportes_problemas/{safe_filename}"

        # Se o canal for e-mail (ou enviado como backup no canal whatsapp)
        if canal in ["email", "ambos"]:
            recipient = "ti2@sollusgroup.com"
            cfg = current_app.config
            mail_server = cfg.get("MAIL_SERVER", "smtp.sollusgroup.com")
            mail_port = int(cfg.get("MAIL_PORT", 465) or 465)
            use_ssl = bool(cfg.get("MAIL_USE_SSL", True)) or mail_port == 465
            use_tls = bool(cfg.get("MAIL_USE_TLS", False))
            mail_user = cfg.get("MAIL_USERNAME", "noreply@sollusgroup.com")
            mail_pw = cfg.get("MAIL_PASSWORD", "1@Pgskmesob")
            sender = cfg.get("MAIL_DEFAULT_SENDER", "Sollus Connected <noreply@sollusgroup.com>")

            user_agent = request.headers.get("User-Agent", "Navegador padrão")
            client_ip = request.remote_addr or "127.0.0.1"
            now_formatted = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")

            subject = f"[Alerta TI Sollus] Problema em {pagina or 'Sistema'} ({colaborador_nome})"

            html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #07172e; color: #f8fafc; padding: 20px; margin: 0; }}
    .container {{ max-width: 650px; margin: 0 auto; background: linear-gradient(135deg, #07172e 0%, #0a254a 100%); border: 1px solid rgba(0, 164, 245, 0.35); border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.4); }}
    .header {{ background: linear-gradient(135deg, #07172e 0%, #004d7c 100%); padding: 22px 26px; border-bottom: 1px solid rgba(0, 164, 245, 0.25); }}
    .header h2 {{ margin: 0; color: #38bdf8; font-size: 20px; font-weight: 700; }}
    .header p {{ margin: 6px 0 0 0; color: #94a3b8; font-size: 13px; }}
    .content {{ padding: 24px 26px; }}
    .field {{ margin-bottom: 18px; }}
    .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #38bdf8; font-weight: 700; margin-bottom: 5px; }}
    .value {{ background: rgba(8, 34, 78, 0.5); border: 1px solid rgba(0, 164, 245, 0.2); border-radius: 10px; padding: 12px 14px; font-size: 14px; color: #f1f5f9; }}
    .footer {{ background: rgba(0,0,0,0.25); padding: 14px 26px; font-size: 11px; color: #64748b; text-align: center; border-top: 1px solid rgba(255,255,255,0.06); }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h2>☀️ Sollus Connected — Relato de Problema / Erro</h2>
      <p>Notificação da Central de Ajuda da Sol enviada diretamente para ti2@sollusgroup.com</p>
    </div>
    <div class="content">
      <div class="field">
        <div class="label">👤 Colaborador</div>
        <div class="value"><strong>{colaborador_nome}</strong> ({colaborador_email})</div>
      </div>
      <div class="field">
        <div class="label">📍 Página onde ocorreu</div>
        <div class="value"><strong>{pagina or 'Não especificada'}</strong></div>
      </div>
      <div class="field">
        <div class="label">🎯 O que estava fazendo</div>
        <div class="value">{acao or 'Não informado'}</div>
      </div>
      <div class="field">
        <div class="label">⚠️ Descritivo do problema / erro</div>
        <div class="value" style="white-space: pre-wrap; line-height: 1.5;">{descricao}</div>
      </div>
      <div class="field">
        <div class="label">📸 Print da Tela (Anexo)</div>
        <div class="value">
          {'Imagem anexada ao e-mail (' + image_filename + ')' if image_filename else 'Nenhum print anexado.'}
          {f'<br><br><a href="{image_url}" style="color: #38bdf8; text-decoration: underline;" target="_blank">Clique para visualizar a imagem no navegador</a>' if image_url else ''}
        </div>
      </div>
      <div class="field">
        <div class="label">ℹ️ Diagnóstico do Sistema</div>
        <div class="value" style="font-size: 12px; color: #94a3b8; line-height: 1.4;">
          Data/Hora: {now_formatted}<br>
          IP do cliente: {client_ip}<br>
          User-Agent: {user_agent}
        </div>
      </div>
    </div>
    <div class="footer">
      Sollus Connected • Equipe de TI: ti2@sollusgroup.com | WhatsApp: (21) 99229-7900
    </div>
  </div>
</body>
</html>"""

            plain_text = f"""SOLLUS CONNECTED - RELATO DE PROBLEMA
=====================================
Colaborador: {colaborador_nome} ({colaborador_email})
Página: {pagina}
O que estava fazendo: {acao}
Descrição do problema: {descricao}
Print anexado: {'Sim (' + image_filename + ')' if image_filename else 'Não'}
Data/Hora: {now_formatted}
IP: {client_ip}
Navegador: {user_agent}
"""

            def _send_email_async(sub, to, from_s, html_c, text_c, img_b, img_f, mtype, stype, srv, port, ssl_flag, tls_flag, usr, pwd):
                try:
                    msg = EmailMessage()
                    msg['Subject'] = sub
                    msg['From'] = from_s
                    msg['To'] = to
                    msg.set_content(text_c)
                    msg.add_alternative(html_c, subtype='html')

                    if img_b and img_f:
                        msg.add_attachment(
                            img_b,
                            maintype=mtype,
                            subtype=stype,
                            filename=img_f
                        )

                    if ssl_flag:
                        with smtplib.SMTP_SSL(srv, port, timeout=25) as server:
                            if usr and pwd:
                                server.login(usr, pwd)
                            server.send_message(msg)
                    else:
                        with smtplib.SMTP(srv, port, timeout=25) as server:
                            if tls_flag:
                                server.starttls()
                            if usr and pwd:
                                server.login(usr, pwd)
                            server.send_message(msg)
                except Exception as ex:
                    print(f"[ERROR] Falha ao enviar e-mail de reporte para {to}: {ex}")

            executor.submit(
                _send_email_async,
                subject, recipient, sender, html_body, plain_text,
                image_bytes, image_filename, maintype, subtype,
                mail_server, mail_port, use_ssl, use_tls, mail_user, mail_pw
            )

        return jsonify(
            ok=True,
            message="Relato registrado com sucesso!",
            image_url=image_url,
            image_filename=image_filename,
            colaborador=colaborador_nome
        )

    except Exception as exc:
        current_app.logger.exception("Erro ao processar reporte de problema:")
        return jsonify(ok=False, message=f"Erro ao processar relato: {str(exc)}"), 500
