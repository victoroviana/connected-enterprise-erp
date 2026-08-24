"""Contratos blueprint: lista de contratos."""
from __future__ import annotations

from datetime import date, datetime
import calendar
import html
import math
import re
import unicodedata
from typing import Any

from utils.helpers import (
    normalize_dept_name as _normalize_dept_name,
    wants_json as _wants_json,
    paginate as _paginate,
    format_date as _format_date,
    format_datetime as _format_datetime,
    sanitize_html as _sanitize_html,
)

from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from modules.audit.utils import write_audit_external
from modules.propostas.blueprints.auth import login_required
from modules.propostas.blueprints.auth.permissions_utils import normalize_permissions


contratos_bp = Blueprint("contratos_bp", __name__, url_prefix="/contratos")

RESULTS_PER_PAGE = 10
CONTRATOS_ALLOWED_DEPTS = {"CONTRATOS"}
STATUS_TABS = ("Todos", "Ativo", "Inativo", "Cancelado", "Recuperado", "Revertido")
TODOS_EXCLUDE = {"Cancelado", "Recuperado", "Revertido"}




def _dept_names() -> set[str]:
    names: set[str] = set()
    try:
        for name in getattr(current_user, "department_names", []) or []:
            normalized = _normalize_dept_name(name)
            if normalized:
                names.add(normalized)
    except Exception:
        return set()
    return names


def _dept_is_contratos() -> bool:
    return bool(_dept_names() & CONTRATOS_ALLOWED_DEPTS)


def _is_admin_user() -> bool:
    role = (getattr(current_user, "tipo", None) or session.get("tipo") or "").lower()
    return role == "admin"


def _has_contratos_permission() -> bool:
    perms = getattr(current_user, "permissions", None) or {}
    try:
        perms = normalize_permissions(perms if isinstance(perms, dict) else {})
    except Exception:
        perms = perms if isinstance(perms, dict) else {}
    return any(
        perms.get(key, False)
        for key in ("contratos",)
    )




def _current_user_name() -> str:
    try:
        if current_user and getattr(current_user, "is_authenticated", False):
            return (
                getattr(current_user, "nome_completo", None)
                or getattr(current_user, "usuario", None)
                or getattr(current_user, "email", None)
                or "Sistema"
            )
    except Exception:
        pass
    return (
        session.get("logged_in_user")
        or session.get("usuario_nome")
        or session.get("nome")
        or "Sistema"
    )


def _resolve_contratos_smtp_settings() -> dict[str, Any]:
    cfg = current_app.config
    defaults = {
        "host": "smtp.sollustecnologia.com",
        "port": 587,
        "username": "contratos.automatico@sollustecnologia.com",
        "password": None,  # Must be configured via CONTRATOS_SMTP_PASSWORD or MAIL_PASSWORD env var
        "from_email": "contratos.automatico@sollustecnologia.com",
        "from_name": "Contratos Sollus",
        "use_tls": True,
    }
    return {
        "host": cfg.get("CONTRATOS_SMTP_HOST") or cfg.get("MAIL_SERVER") or defaults["host"],
        "port": int(cfg.get("CONTRATOS_SMTP_PORT") or cfg.get("MAIL_PORT") or defaults["port"]),
        "username": cfg.get("CONTRATOS_SMTP_USERNAME") or cfg.get("MAIL_USERNAME") or defaults["username"],
        "password": cfg.get("CONTRATOS_SMTP_PASSWORD") or cfg.get("MAIL_PASSWORD") or defaults["password"],
        "from_email": cfg.get("CONTRATOS_FROM_EMAIL") or cfg.get("MAIL_DEFAULT_SENDER") or defaults["from_email"],
        "from_name": cfg.get("CONTRATOS_FROM_NAME") or defaults["from_name"],
        "use_tls": cfg.get("CONTRATOS_SMTP_USE_TLS") if cfg.get("CONTRATOS_SMTP_USE_TLS") is not None else cfg.get("MAIL_USE_TLS", True),
        "use_ssl": cfg.get("CONTRATOS_SMTP_USE_SSL") if cfg.get("CONTRATOS_SMTP_USE_SSL") is not None else cfg.get("MAIL_USE_SSL", False),
    }


def _send_email(
    *,
    subject: str,
    html_body: str,
    to: list[str],
    cc: list[str] | None = None,
    plain_body: str | None = None,
) -> bool:
    if current_app.config.get("MAIL_ENABLED", True) is False:
        try:
            write_audit_external(
                entity_type="contratos_email",
                action="email_skip",
                message="Envio de email de contratos ignorado: MAIL_ENABLED falso.",
                after={"assunto": subject, "status": "disabled"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email de contratos (skip).")
        return False

    settings = _resolve_contratos_smtp_settings()
    recipients = [addr for addr in to if addr]
    if not recipients:
        try:
            write_audit_external(
                entity_type="contratos_email",
                action="email_skip",
                message="Envio de email de contratos ignorado: sem destinatarios.",
                after={"assunto": subject, "status": "no_recipients"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email de contratos (sem destinatarios).")
        return False
    cc_list = [addr for addr in (cc or []) if addr]

    from email.message import EmailMessage
    from email.utils import formataddr
    import smtplib

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.get("from_name"), settings.get("from_email")))
    msg["To"] = ", ".join(recipients)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg.set_content(plain_body or html_body.replace("<br>", "\n").replace("<br/>", "\n"))
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    import ssl
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
            if not use_ssl and settings.get("use_tls"):
                smtp.starttls(context=context)
                smtp.ehlo()
            if settings.get("username"):
                smtp.login(settings["username"], settings.get("password") or "")
            smtp.send_message(msg)
        try:
            write_audit_external(
                entity_type="contratos_email",
                action="email_send",
                message="Envio de email de contratos concluido.",
                after={"assunto": subject, "to": recipients, "cc": cc_list, "status": "success"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar envio de email de contratos.")
        return True
    except Exception:
        current_app.logger.exception("Falha ao enviar e-mail de contratos")
        try:
            write_audit_external(
                entity_type="contratos_email",
                action="email_error",
                message="Falha ao enviar email de contratos.",
                after={"assunto": subject, "to": recipients, "cc": cc_list, "status": "error"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar erro no email de contratos.")
        return False


def _ensure_protocolos_table() -> None:
    sql = (
        "CREATE TABLE IF NOT EXISTS protocolos ("
        "id int(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,"
        "tabela_origem varchar(50) NOT NULL,"
        "id_tabela_origem int(11) NOT NULL,"
        "protocolo varchar(20) NOT NULL,"
        "data_criacao datetime NOT NULL"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"
    )
    db.session.execute(text(sql))


def _text_to_numbers(text_value: str) -> str:
    conversion_map = {
        "2": {"A", "B", "C"},
        "3": {"D", "E", "F"},
        "4": {"G", "H", "I"},
        "5": {"J", "K", "L"},
        "6": {"M", "N", "O"},
        "7": {"P", "Q", "R", "S"},
        "8": {"T", "U", "V"},
        "9": {"W", "X", "Y", "Z"},
    }
    converted = []
    for ch in text_value.upper():
        for number, letters in conversion_map.items():
            if ch in letters:
                converted.append(number)
                break
    return "".join(converted)


def _generate_protocol() -> str:
    base = _text_to_numbers("SOLLUS")
    protocol = f"{base}{datetime.now().strftime('%Y%m%d%H%M%S')}"
    row = db.session.execute(
        text("SELECT id FROM protocolos WHERE protocolo = :protocolo"),
        {"protocolo": protocol},
    ).fetchone()
    if row:
        return _generate_protocol()
    return protocol


@contratos_bp.before_request
def _check_contratos_permissions():
    from flask import request
    if "/api/" in getattr(request, "path", ""):
        return
    endpoint = getattr(request, "endpoint", "") or ""
    if endpoint and not endpoint.startswith("contratos_bp."):
        return
    if endpoint == "contratos_bp.sem_permissao":
        return
    if not current_user.is_authenticated:
        return
    if _is_admin_user() or _dept_is_contratos() or _has_contratos_permission():
        return
    if _wants_json():
        return jsonify({"ok": False, "message": "Sem permissão para contratos."}), 403
    flash("Você não tem permissão para acessar contratos. Procure seu superior.", "warning")
    return redirect(url_for("contratos_bp.sem_permissao"))


@contratos_bp.route("/sem-permissao")
@login_required
def sem_permissao():
    return render_template("errors/403.html", area_label="Contratos")


def _safe_int(value: Any, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _next_id(table: str, column: str = "id_pk") -> int:
    allowed_tables = {
        "ja_fin_contas_a_receber_contratos",
        "ja_cli_manutencao_agendamentos",
    }
    allowed_columns = {"id_pk"}
    if table not in allowed_tables or column not in allowed_columns:
        raise ValueError("Invalid table or column name in _next_id")

    row = db.session.execute(text(f"SELECT MAX({column}) AS max_id FROM {table}")).fetchone()
    max_id = row[0] if row and row[0] is not None else 0
    return int(max_id) + 1


def _parse_date_br(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _add_months(base: date, months: int, day_base: int | None = None) -> date:
    month = base.month - 1 + months
    year = base.year + month // 12
    month = month % 12 + 1
    day = day_base if day_base is not None else base.day
    last_day = calendar.monthrange(year, month)[1]
    day = min(day, last_day)
    return date(year, month, day)


def _parse_money(value: Any) -> float:
    text_value = str(value or "").strip()
    if not text_value:
        return 0.0
    try:
        if "," in text_value:
            text_value = text_value.replace(".", "").replace(",", ".")
        return float(text_value)
    except (TypeError, ValueError):
        return 0.0


def _format_money(value: Any) -> str:
    parsed = _parse_money(value)
    return f"{parsed:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")






def _sanitize_mojibake(value: Any) -> Any:
    if value is None:
        return value
    if isinstance(value, str):
        try:
            fixed = value.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value
        return fixed
    if isinstance(value, (list, tuple)):
        fixed = [_sanitize_mojibake(item) for item in value]
        return type(value)(fixed)
    return value


def _row_to_dict(row: Any) -> dict[str, Any]:
    mapping = getattr(row, "_mapping", None)
    data = dict(mapping) if mapping is not None else dict(row)
    return {key: _sanitize_mojibake(value) for key, value in data.items()}




def _normalize_status_bucket(value: Any) -> str | None:
    raw = (value or "").strip().lower()
    if not raw:
        return None
    if raw.startswith("cancelado"):
        return "Cancelado"
    if raw.startswith("revertido"):
        return "Revertido"
    if raw.startswith("recuperado"):
        return "Recuperado"
    if raw.startswith("inativo"):
        return "Inativo"
    if raw.startswith("ativo"):
        return "Ativo"
    return None


def _normalize_status_filter(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return "Todos"
    for label in STATUS_TABS:
        if raw == label.lower():
            return label
    aliases = {
        "ativos": "Ativo",
        "ativo": "Ativo",
        "inativos": "Inativo",
        "inativo": "Inativo",
        "cancelados": "Cancelado",
        "cancelado": "Cancelado",
        "recuperados": "Recuperado",
        "recuperado": "Recuperado",
        "revertidos": "Revertido",
        "revertido": "Revertido",
    }
    return aliases.get(raw, "Todos")


def _build_base_filters(
    *,
    search: str,
    contrato: str,
    protocolo: str,
    date_start: str,
    date_end: str,
) -> tuple[list[str], dict[str, Any]]:
    where: list[str] = []
    params: dict[str, Any] = {}

    if search:
        where.append("(cliente LIKE :search OR cnpj LIKE :search)")
        params["search"] = f"%{search}%"
    if contrato:
        where.append("contrato LIKE :contrato")
        params["contrato"] = f"%{contrato}%"
    if protocolo:
        where.append("protocolo = :protocolo")
        params["protocolo"] = protocolo
    if date_start and date_end:
        where.append("data_solicitacao BETWEEN :date_start AND :date_end")
        params["date_start"] = date_start
        params["date_end"] = date_end

    return where, params


def _fetch_status_counts(
    *,
    search: str,
    contrato: str,
    protocolo: str,
    date_start: str,
    date_end: str,
) -> dict[str, int]:
    where, params = _build_base_filters(
        search=search,
        contrato=contrato,
        protocolo=protocolo,
        date_start=date_start,
        date_end=date_end,
    )
    where_sql = " AND ".join(where) if where else "1=1"
    rows = db.session.execute(
        text(f"SELECT status, COUNT(id) AS total FROM contratos WHERE {where_sql} GROUP BY status"),
        params,
    ).fetchall()

    counts = {label: 0 for label in STATUS_TABS}
    total = 0
    for row in rows:
        row_status = row[0]
        row_total = int(row[1] or 0)
        total += row_total
        bucket = _normalize_status_bucket(row_status)
        if bucket:
            counts[bucket] += row_total
    if TODOS_EXCLUDE:
        counts["Todos"] = sum(
            count for label, count in counts.items() if label not in TODOS_EXCLUDE and label != "Todos"
        )
    else:
        counts["Todos"] = total
    return counts


def _fetch_contratos(
    *,
    status_filter: str,
    search: str,
    contrato: str,
    protocolo: str,
    date_start: str,
    date_end: str,
    page: int,
    per_page: int,
) -> tuple[list[dict[str, Any]], int]:
    columns = (
        "id, cliente, cnpj, base, contrato, protocolo, Sistema AS sistema, valor, tem_multa, "
        "valor_multa, data_solicitacao, data_cancelamento, data_revertido, base_ativa_ate, "
        "informacoes, status, cancelamento_concluido"
    )
    where, params = _build_base_filters(
        search=search,
        contrato=contrato,
        protocolo=protocolo,
        date_start=date_start,
        date_end=date_end,
    )
    if status_filter != "Todos":
        where.append("status = :status")
        params["status"] = status_filter
    elif TODOS_EXCLUDE:
        where.append("status NOT IN ('Cancelado', 'Recuperado', 'Revertido')")

    where_sql = " AND ".join(where) if where else "1=1"
    total = db.session.execute(
        text(f"SELECT COUNT(id) AS total FROM contratos WHERE {where_sql}"),
        params,
    ).scalar() or 0

    limit = per_page if per_page else 12
    offset = (page - 1) * limit
    query = text(
        f"SELECT {columns} FROM contratos WHERE {where_sql} "
        "ORDER BY data_cancelamento DESC, data_solicitacao DESC LIMIT :limit OFFSET :offset"
    )
    params.update({"limit": limit, "offset": offset})
    rows = db.session.execute(query, params).fetchall()

    payload: list[dict[str, Any]] = []
    for row in rows:
        item = _row_to_dict(row)
        multa_raw = str(item.get("tem_multa") or "").strip().lower()
        item["tem_multa_label"] = "Sim" if multa_raw in {"1", "true", "sim"} else "Não"
        item["valor_display"] = _format_money(item.get("valor"))
        item["valor_multa_display"] = _format_money(item.get("valor_multa"))
        item["data_solicitacao_br"] = _format_date(item.get("data_solicitacao"))
        item["data_cancelamento_br"] = _format_datetime(item.get("data_cancelamento"))
        item["data_revertido_br"] = _format_datetime(item.get("data_revertido"))
        item["base_ativa_ate_br"] = _format_date(item.get("base_ativa_ate"))
        item["cancelamento_concluido_br"] = _format_datetime(item.get("cancelamento_concluido"))
        payload.append(item)

    return payload, total


def _build_url(endpoint: str, **updates: Any) -> str:
    args = dict(request.args)
    for key, value in updates.items():
        if value in (None, ""):
            args.pop(key, None)
        else:
            args[key] = value
    return url_for(endpoint, **args)


@contratos_bp.route("/")
@login_required
def index():
    return redirect(url_for("contratos_bp.cancelados"))


@contratos_bp.route("/cancelados")
@login_required
def cancelados():
    page = _safe_int(request.args.get("page"), 1)
    search = (request.args.get("search") or "").strip()
    contrato = (request.args.get("contrato") or "").strip()
    protocolo = (request.args.get("protocolo") or "").strip()
    date_start = (request.args.get("date_start") or "").strip()
    date_end = (request.args.get("date_end") or "").strip()
    status_filter = _normalize_status_filter(request.args.get("status"))

    status_counts = _fetch_status_counts(
        search=search,
        contrato=contrato,
        protocolo=protocolo,
        date_start=date_start,
        date_end=date_end,
    )

    contratos, total = _fetch_contratos(
        status_filter=status_filter,
        search=search,
        contrato=contrato,
        protocolo=protocolo,
        date_start=date_start,
        date_end=date_end,
        page=page,
        per_page=RESULTS_PER_PAGE,
    )
    pagination = _paginate(total, page, RESULTS_PER_PAGE)
    stats = [
        {"label": "Registros", "value": total},
        {"label": "Página", "value": f"{pagination['page']}/{pagination['pages']}"},
    ]

    return render_template(
        "admin/contratos/cancelados.html",
        contratos=contratos,
        pagination=pagination,
        stats=stats,
        status_tabs=STATUS_TABS,
        status_counts=status_counts,
        status_value=status_filter,
        search_value=search,
        contrato_value=contrato,
        protocolo_value=protocolo,
        date_start=date_start,
        date_end=date_end,
        build_url=lambda **kw: _build_url("contratos_bp.cancelados", **kw),
    )


@contratos_bp.route("/historico", methods=["POST"])
@login_required
def historico():
    contrato_id = _safe_int(request.form.get("id"), 0)
    if not contrato_id:
        return Response("", mimetype="text/html")
    row = db.session.execute(
        text("SELECT informacoes FROM contratos WHERE id = :id"),
        {"id": contrato_id},
    ).fetchone()
    historico = row[0] if row and row[0] else ""
    return Response(_sanitize_html(str(historico or "")), mimetype="text/html")


@contratos_bp.route("/update-info", methods=["POST"])
@login_required
def update_info():
    contrato_id = _safe_int(request.form.get("id"), 0)
    new_info = (request.form.get("new_info") or "").strip()
    if not contrato_id or not new_info:
        return jsonify({"ok": False, "message": "Informe a nova informação."}), 400

    now_label = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    user_name = _current_user_name()

    row = db.session.execute(
        text("SELECT informacoes FROM contratos WHERE id = :id"),
        {"id": contrato_id},
    ).fetchone()
    current_info = row[0] if row and row[0] else ""

    if current_info:
        updated_info = (
            f'{current_info}<li><span class="bullet"></span>{html.escape(new_info)} '
            f"{now_label} - Adicionado Por: {html.escape(user_name)}</li>"
        )
    else:
        updated_info = (
            f'<li><span class="bullet"></span>{html.escape(new_info)} '
            f"{now_label} - Usuário: {html.escape(user_name)}</li>"
        )
    updated_info = f"<br>{updated_info}<br>"

    db.session.execute(
        text("UPDATE contratos SET informacoes = :info WHERE id = :id"),
        {"info": _sanitize_html(updated_info), "id": contrato_id},
    )
    db.session.commit()

    return jsonify({"ok": True, "message": "Informação adicionada com sucesso!"})


@contratos_bp.route("/cancelamento", methods=["POST"])
@login_required
def solicitar_cancelamento():
    contrato_id = _safe_int(request.form.get("id"), 0)
    cancelamento_raw = (request.form.get("cancelamento") or "").strip()
    if not contrato_id:
        return jsonify({"ok": False, "message": "ID inválido."}), 400

    if cancelamento_raw:
        try:
            cancelamento_dt = datetime.strptime(cancelamento_raw, "%d/%m/%Y %H:%M:%S")
        except ValueError:
            cancelamento_dt = datetime.now()
    else:
        cancelamento_dt = datetime.now()

    cancelamento_db = cancelamento_dt.strftime("%Y-%m-%d %H:%M:%S")
    cancelamento_label = cancelamento_dt.strftime("%d/%m/%Y %H:%M:%S")
    user_name = _current_user_name()

    row = db.session.execute(
        text("SELECT informacoes FROM contratos WHERE id = :id"),
        {"id": contrato_id},
    ).fetchone()
    current_info = row[0] if row and row[0] else ""
    updated_info = (
        f'{current_info}<li><span class="bullet"></span> Cancelamento Solicitado - '
        f"{cancelamento_label} Por: {html.escape(user_name)}</li>"
    )

    db.session.execute(
        text("UPDATE contratos SET data_cancelamento = :data, informacoes = :info WHERE id = :id"),
        {"data": cancelamento_db, "info": _sanitize_html(updated_info), "id": contrato_id},
    )

    dados = db.session.execute(
        text(
            "SELECT cliente, cnpj, contrato, base, data_solicitacao, informacoes, Sistema AS sistema "
            "FROM contratos WHERE id = :id"
        ),
        {"id": contrato_id},
    ).fetchone()
    db.session.commit()

    if dados:
        cliente, cnpj, contrato, base, data_solicitacao, informacoes, sistema = dados
        data_solicitacao_fmt = _format_date(data_solicitacao)
        subject = f"Solicitação de Cancelamento recebida - {cliente}"
        message = f"""
<html>
<head>
  <style>
    .email-content {{
      max-width: 600px;
      margin: 20px auto;
      border: 1px solid #e7e7e7;
      padding: 20px;
      border-radius: 5px;
      box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
    }}
    .header {{ text-align: center; margin-bottom: 30px; font-weight: bold; }}
    .info-item {{ margin-bottom: 10px; font-size: 16px; }}
    .info-title {{ font-weight: bold; display: inline-block; width: 150px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="email-content">
      <div class="header">Solicitação de Cancelamento</div>
      <div class="info-item"><span class="info-title">Cliente:</span> {cliente}</div>
      <div class="info-item"><span class="info-title">CNPJ:</span> {cnpj}</div>
      <div class="info-item"><span class="info-title">Contrato:</span> {contrato}</div>
      <div class="info-item"><span class="info-title">Tipo de Contrato:</span> {sistema}</div>
      <div class="info-item"><span class="info-title">Unidade:</span> {base}</div>
      <div class="info-item"><span class="info-title">Data da Solicitação:</span> {data_solicitacao_fmt}</div>
      <div class="info-item"><span class="info-title">Mais informações:</span> {informacoes}</div>
      <div class="info-item"><span class="info-title">Solicitante:</span> {user_name}</div>
    </div>
  </div>
</body>
</html>
"""
        _send_email(
            subject=subject,
            html_body=message,
            to=["leonardo.santos@sollustecnologia.com"],
            cc=["contratos@sollustecnologia.com", "contratos2@sollustecnologia.com"],
        )

    return jsonify({"ok": True, "message": "Data de cancelamento atualizada com sucesso!"})


@contratos_bp.route("/deferir-cancelamento", methods=["POST"])
@login_required
def deferir_cancelamento():
    contrato_id = _safe_int(request.form.get("id"), 0)
    if not contrato_id:
        return jsonify({"ok": False, "message": "ID inválido."}), 400

    now_db = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.session.execute(
        text("UPDATE contratos SET cancelamento_concluido = :data, status = :status WHERE id = :id"),
        {"data": now_db, "status": "Cancelado", "id": contrato_id},
    )

    dados = db.session.execute(
        text("SELECT contrato, cliente, cnpj FROM contratos WHERE id = :id"),
        {"id": contrato_id},
    ).fetchone()
    db.session.commit()

    if dados:
        contrato, cliente, cnpj = dados
        subject = f"Cancelamento de contrato concluído - ID {contrato_id}"
        message = (
            f"O cancelamento do contrato de número: {contrato} foi concluído em {now_db}.\n\n"
            f"Empresa: {cliente} CNPJ: {cnpj}\n"
            "O contrato está agora em situação de Cancelado."
        )
        _send_email(
            subject=subject,
            html_body="",
            plain_body=message,
            to=["leonardo.santos@sollustecnologia.com"],
            cc=["contratos@sollustecnologia.com", "contratos2@sollustecnologia.com"],
        )

    return jsonify({"ok": True, "message": "Cancelamento concluído com sucesso!"})


@contratos_bp.route("/reverter-cancelamento", methods=["POST"])
@login_required
def reverter_cancelamento():
    contrato_id = _safe_int(request.form.get("id"), 0)
    if not contrato_id:
        return jsonify({"ok": False, "message": "ID inválido."}), 400

    now_db = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = db.session.execute(
        text(
            "UPDATE contratos SET status = 'Revertido', data_revertido = :data WHERE id = :id"
        ),
        {"data": now_db, "id": contrato_id},
    )
    db.session.commit()

    if result.rowcount:
        return jsonify({"ok": True, "message": "Cancelamento revertido com sucesso."})
    return jsonify({"ok": True, "message": "Nenhuma alteração realizada."})


@contratos_bp.route("/inativar", methods=["POST"])
@login_required
def inativar_contrato():
    contrato_id = _safe_int(request.form.get("id"), 0)
    if not contrato_id:
        return jsonify({"ok": False, "message": "ID inválido."}), 400

    row = db.session.execute(
        text("SELECT informacoes FROM contratos WHERE id = :id"),
        {"id": contrato_id},
    ).fetchone()
    current_info = row[0] if row and row[0] else ""
    now_label = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    user_name = _current_user_name()
    updated_info = (
        f'{current_info}<li><span class="bullet"></span>Sistema Inativo -  '
        f"{now_label}  Inativado por: {html.escape(user_name)} </li>"
    )

    db.session.execute(
        text(
            "UPDATE contratos SET status = 'Inativo', data_inativacao = NOW(), informacoes = :info WHERE id = :id"
        ),
        {"info": _sanitize_html(updated_info), "id": contrato_id},
    )
    db.session.commit()

    return jsonify({"ok": True})


@contratos_bp.route("/adicionar", methods=["POST"])
@login_required
def adicionar_contrato():
    cliente = (request.form.get("cliente") or "").strip()
    cnpj = (request.form.get("cnpj") or "").strip()
    email = (request.form.get("email") or "").strip()
    base = (request.form.get("base") or "").strip()
    contrato = (request.form.get("contrato") or "").strip()
    sistema = (request.form.get("Sistema") or "").strip()
    valor = (request.form.get("valor") or "").strip()
    tem_multa = (request.form.get("tem_multa") or "").strip()
    valor_multa = (request.form.get("valor_multa") or "0").strip()
    data_solicitacao_raw = (request.form.get("data_solicitacao") or "").strip()
    contratos_vigencia = (request.form.get("contratos_vigencia") or "").strip()
    base_ativa_custom = (request.form.get("base_ativa_ate") or "").strip()

    if not all([cliente, cnpj, email, base, contrato, sistema, valor, tem_multa, data_solicitacao_raw]):
        flash("Preencha todos os campos obrigatórios.", "warning")
        return redirect(url_for("contratos_bp.cancelados"))

    try:
        data_solicitacao = datetime.strptime(data_solicitacao_raw, "%Y-%m-%d").date()
    except ValueError:
        flash("Data de solicitação inválida.", "warning")
        return redirect(url_for("contratos_bp.cancelados"))

    criado_por = _current_user_name()
    status = "Ativo"
    tem_multa_value = "1" if tem_multa == "1" else "0"
    valor_parsed = _parse_money(valor)
    valor_multa_parsed = _parse_money(valor_multa)
    if tem_multa_value == "0":
        valor_multa_parsed = 0.0

    if tem_multa_value == "0" and contratos_vigencia == "NAO" and not base_ativa_custom:
        flash("Informe a base ativa até para contratos sem vigência.", "warning")
        return redirect(url_for("contratos_bp.cancelados"))

    result = db.session.execute(
        text(
            "INSERT INTO contratos (cliente, cnpj, email, base, contrato, Sistema, valor, tem_multa, "
            "valor_multa, data_solicitacao, status, criado_por) "
            "VALUES (:cliente, :cnpj, :email, :base, :contrato, :sistema, :valor, :tem_multa, "
            ":valor_multa, :data_solicitacao, :status, :criado_por)"
        ),
        {
            "cliente": cliente,
            "cnpj": cnpj,
            "email": email,
            "base": base,
            "contrato": contrato,
            "sistema": sistema,
            "valor": valor_parsed,
            "tem_multa": tem_multa_value,
            "valor_multa": valor_multa_parsed,
            "data_solicitacao": data_solicitacao.strftime("%Y-%m-%d"),
            "status": status,
            "criado_por": criado_por,
        },
    )
    contrato_id = result.lastrowid

    solicitacao_day = data_solicitacao.day
    if tem_multa_value == "0" and contratos_vigencia == "NAO" and base_ativa_custom:
        base_ativa_ate = base_ativa_custom
    else:
        if 1 <= solicitacao_day <= 19:
            base_ativa_ate = data_solicitacao.replace(day=26)
        else:
            month = data_solicitacao.month + 1
            year = data_solicitacao.year
            if month > 12:
                month = 1
                year += 1
            base_ativa_ate = date(year, month, 26)
        base_ativa_ate = base_ativa_ate.strftime("%Y-%m-%d")

    db.session.execute(
        text("UPDATE contratos SET base_ativa_ate = :data WHERE id = :id"),
        {"data": base_ativa_ate, "id": contrato_id},
    )

    _ensure_protocolos_table()
    protocolo = _generate_protocol()
    db.session.execute(
        text("UPDATE contratos SET protocolo = :protocolo WHERE id = :id"),
        {"protocolo": protocolo, "id": contrato_id},
    )
    db.session.execute(
        text(
            "INSERT INTO protocolos (tabela_origem, id_tabela_origem, protocolo, data_criacao) "
            "VALUES (:tabela, :id_tabela, :protocolo, :data)"
        ),
        {
            "tabela": "contratos",
            "id_tabela": contrato_id,
            "protocolo": protocolo,
            "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    db.session.commit()

    base_ativa_ate_label = _format_date(base_ativa_ate)
    multa_texto = "Sim" if tem_multa_value == "1" else "Não"
    valor_label = _format_money(valor_parsed)
    valor_multa_label = _format_money(valor_multa_parsed)
    message = f"""
<html><body>
  <p>Olá {cliente} CNPJ: {cnpj},</p>
  <p>Recebemos a solicitação de cancelamento. Seguem os detalhes:</p>
  <ul>
    <li><b>Número do Contrato:</b> {contrato}</li>
    <li><b>Serviço contratado:</b> {sistema}</li>
    <li><b>Valor Mensal:</b> R$ {valor_label}</li>
    <li><b>Multa por cancelamento:</b> {multa_texto}</li>
    <li><b>Valor:</b> R$ {valor_multa_label}</li>
    <li><b>Prazo para coleta dos arquivos fiscais:</b> {base_ativa_ate_label}</li>
    <li><b>Número do protocolo:</b> {protocolo}</li>
  </ul>
  <p>Atenciosamente,<br>Contratos - Sollus Tecnologia</p>
</body></html>
"""
    _send_email(
        subject=f"Sua solicitação de Cancelamento foi recebida {cliente}",
        html_body=message,
        to=[email],
        cc=["contratos@sollustecnologia.com", "contratos2@sollustecnologia.com"],
    )

    flash("Contrato criado com sucesso.", "success")
    return redirect(url_for("contratos_bp.cancelados"))


@contratos_bp.route("/verifica-empresa")
@login_required
def verifica_empresa():
    cnpj = (request.args.get("cnpj") or "").strip()
    if not cnpj:
        return ""
    cnpj = re.sub(r"\D+", "", cnpj)

    row = db.session.execute(
        text("SELECT cliente FROM empresa WHERE cnpj = :cnpj"),
        {"cnpj": cnpj},
    ).fetchone()
    if row and row[0]:
        return str(row[0])

    try:
        import requests

        resp = requests.get(f"https://www.receitaws.com.br/v1/cnpj/{cnpj}", timeout=12)
        if resp.ok:
            data = resp.json()
            if data.get("nome"):
                return str(data.get("nome"))
    except Exception:
        current_app.logger.warning("Falha ao consultar receitaws para CNPJ %s", cnpj)

    return "CNPJ não encontrado."

@contratos_bp.route("/contas-a-receber")
@login_required
def contas_receber_contratos():
    page = _safe_int(request.args.get("page"), 1)
    cliente_id = _parse_int(request.args.get("cliente_id"))
    usuario_id = session.get("usuario_id")
    per_page = RESULTS_PER_PAGE
    offset = max(0, (page - 1) * per_page)

    where: list[str] = []
    params: dict[str, Any] = {}
    has_empresa_scope = False
    if usuario_id:
        has_empresa_scope = db.session.execute(
            text(
                "SELECT 1 FROM ja_emp_empresas_usuarios "
                "WHERE idusuarios_fk = :usuario_id LIMIT 1"
            ),
            {"usuario_id": usuario_id},
        ).fetchone() is not None
    if cliente_id:
        where.append("con.idclientes_fk = :cliente_id")
        params["cliente_id"] = cliente_id
    if has_empresa_scope:
        where.append(
            "EXISTS (SELECT 1 FROM ja_emp_empresas_usuarios eu "
            "WHERE eu.idempresas_fk = cl.idempresas_fk AND eu.idusuarios_fk = :usuario_id)"
        )
        params["usuario_id"] = usuario_id
    where.append("ar.data_vencimento <= CURRENT_DATE()")
    where.append("ar.data_pagamento IS NULL")
    where.append("ar.valor_pago IS NULL")
    where_sql = " AND ".join(where) if where else "1 = 1"

    contrato_key_sql = "COALESCE(NULLIF(TRIM(con.contrato_numero), ''), '__SEM_CONTRATO__')"

    total = db.session.execute(
        text(
            "SELECT COUNT(*) FROM ("
            f"SELECT con.idclientes_fk AS cliente_id, {contrato_key_sql} AS contrato_numero_key "
            "FROM ja_fin_contas_a_receber_contratos ar "
            "INNER JOIN ja_cli_contrato_locacao_manutencao con ON con.id_pk = ar.idcontrato_locacao_manutencao_fk "
            "INNER JOIN ja_cli_clientes cl ON cl.id_pk = con.idclientes_fk "
            f"WHERE {where_sql} "
            f"GROUP BY con.idclientes_fk, {contrato_key_sql}"
            ") AS grupos"
        ),
        params,
    ).scalar() or 0
    group_rows = db.session.execute(
        text(
            f"SELECT con.idclientes_fk AS cliente_id, {contrato_key_sql} AS contrato_numero_key, "
            "MIN(ar.data_vencimento) AS min_vencimento "
            "FROM ja_fin_contas_a_receber_contratos ar "
            "INNER JOIN ja_cli_contrato_locacao_manutencao con ON con.id_pk = ar.idcontrato_locacao_manutencao_fk "
            "INNER JOIN ja_cli_clientes cl ON cl.id_pk = con.idclientes_fk "
            f"WHERE {where_sql} "
            f"GROUP BY con.idclientes_fk, {contrato_key_sql} "
            "ORDER BY min_vencimento "
            "LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": per_page, "offset": offset},
    ).fetchall()

    contas = []
    if group_rows:
        group_filters = []
        group_params: dict[str, Any] = {}
        for idx, row in enumerate(group_rows):
            group_filters.append(
                f"(con.idclientes_fk = :gid_{idx} AND {contrato_key_sql} = :gnum_{idx})"
            )
            group_params[f"gid_{idx}"] = row.cliente_id
            group_params[f"gnum_{idx}"] = row.contrato_numero_key

        rows = db.session.execute(
            text(
                "SELECT ar.id_pk, ar.data_vencimento, ar.valor_cobrado, ar.data_pagamento, ar.valor_pago, "
                "cl.nome_fantasia, con.contrato_numero, "
                "con.idclientes_fk AS cliente_id, ar.idcontrato_locacao_manutencao_fk AS contrato_id, "
                f"{contrato_key_sql} AS contrato_numero_key "
                "FROM ja_fin_contas_a_receber_contratos ar "
                "INNER JOIN ja_cli_contrato_locacao_manutencao con ON con.id_pk = ar.idcontrato_locacao_manutencao_fk "
                "INNER JOIN ja_cli_clientes cl ON cl.id_pk = con.idclientes_fk "
                f"WHERE {where_sql} AND ({' OR '.join(group_filters)}) "
                "ORDER BY con.idclientes_fk, con.contrato_numero, ar.data_vencimento, ar.id_pk"
            ),
            {**params, **group_params},
        ).fetchall()

        grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for row in rows:
            data = dict(row._mapping)
            data["data_vencimento_br"] = _format_date(data.get("data_vencimento"))
            data["data_pagamento_br"] = _format_date(data.get("data_pagamento"))
            key = (data.get("cliente_id"), data.get("contrato_numero_key"))
            grouped.setdefault(key, []).append(data)

        for row in group_rows:
            key = (row.cliente_id, row.contrato_numero_key)
            items = grouped.get(key, [])
            if not items:
                continue
            oldest = items[0]
            oldest["parcelas_total"] = len(items)
            oldest["parcelas_outros"] = items[1:]
            oldest["parcelas_restantes"] = max(len(items) - 1, 0)
            contas.append(oldest)

    if has_empresa_scope:
        clientes_query = (
            "SELECT cl.id_pk, cl.nome_fantasia "
            "FROM ja_cli_clientes cl "
            "WHERE EXISTS (SELECT 1 FROM ja_emp_empresas_usuarios eu "
            "WHERE eu.idempresas_fk = cl.idempresas_fk AND eu.idusuarios_fk = :usuario_id) "
            "ORDER BY cl.nome_fantasia"
        )
        clientes_rows = db.session.execute(
            text(clientes_query), {"usuario_id": usuario_id}
        ).fetchall()
        clientes = [dict(r._mapping) for r in clientes_rows]
    else:
        clientes = [
            dict(r._mapping)
            for r in db.session.execute(
                text("SELECT id_pk, nome_fantasia FROM ja_cli_clientes ORDER BY nome_fantasia")
            ).fetchall()
        ]

    pagination = _paginate(total, page, per_page)

    return render_template(
        "admin/contratos/contas_receber_contratos.html",
        contas=contas,
        clientes=clientes,
        cliente_id=cliente_id,
        pagination=pagination,
        build_url=_build_url,
    )


@contratos_bp.route("/contas-a-receber/novo", methods=["GET", "POST"])
@login_required
def contas_receber_contratos_novo():
    origin = request.form.get("origin") if request.method == "POST" else None
    if request.method == "POST":
        cliente_id = _parse_int(request.form.get("selCliente"))
        contrato_id = _parse_int(request.form.get("selNumeroContratos"))
        data_vencimento = _parse_date_br(request.form.get("txtDataVencimento"))
        valor_cobrado = _parse_money(request.form.get("txtValor"))
        data_pagamento = _parse_date_br(request.form.get("txtDataPagamento"))
        valor_pago = _parse_money(request.form.get("txtValorPago"))

        if not cliente_id or not contrato_id or not data_vencimento:
            flash("Preencha cliente, contrato e data de vencimento.", "warning")
            if origin == "list":
                return redirect(url_for("contratos_bp.contas_receber_contratos"))
        else:
            try:
                conta_id = _next_id("ja_fin_contas_a_receber_contratos")
                db.session.execute(
                    text(
                        "INSERT INTO ja_fin_contas_a_receber_contratos "
                        "(id_pk, data_vencimento, data_pagamento, valor_cobrado, valor_pago, "
                        "idcontrato_locacao_manutencao_fk) "
                        "VALUES (:id, :data_vencimento, :data_pagamento, :valor_cobrado, :valor_pago, :contrato)"
                    ),
                    {
                        "id": conta_id,
                        "data_vencimento": data_vencimento,
                        "data_pagamento": data_pagamento,
                        "valor_cobrado": valor_cobrado,
                        "valor_pago": valor_pago,
                        "contrato": contrato_id,
                    },
                )
                db.session.commit()
                if request.form.get("save_more"):
                    flash("Conta salva. Você pode cadastrar outra.", "success")
                    return redirect(url_for("contratos_bp.contas_receber_contratos_novo"))
                flash("Conta cadastrada.", "success")
                return redirect(url_for("contratos_bp.contas_receber_contratos"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao criar conta a receber contrato")
                flash("Erro ao salvar conta.", "danger")
                if origin == "list":
                    return redirect(url_for("contratos_bp.contas_receber_contratos"))

    clientes = [
        dict(r._mapping)
        for r in db.session.execute(
            text("SELECT id_pk, nome_fantasia FROM ja_cli_clientes ORDER BY nome_fantasia")
        ).fetchall()
    ]

    return render_template(
        "admin/contratos/contas_receber_contratos_form.html",
        conta=None,
        clientes=clientes,
        contratos=[],
        action_url=url_for("contratos_bp.contas_receber_contratos_novo"),
        back_url=url_for("contratos_bp.contas_receber_contratos"),
        allow_more=True,
        subtitle="Cadastre uma nova conta a receber de contrato.",
    )


@contratos_bp.route("/contas-a-receber/<int:conta_id>/editar", methods=["GET", "POST"])
@login_required
def contas_receber_contratos_editar(conta_id: int):
    row = db.session.execute(
        text(
            "SELECT ar.*, con.idclientes_fk "
            "FROM ja_fin_contas_a_receber_contratos ar "
            "LEFT JOIN ja_cli_contrato_locacao_manutencao con ON con.id_pk = ar.idcontrato_locacao_manutencao_fk "
            "WHERE ar.id_pk = :id"
        ),
        {"id": conta_id},
    ).fetchone()
    if not row:
        flash("Conta não encontrada.", "warning")
        return redirect(url_for("contratos_bp.contas_receber_contratos"))
    conta = dict(row._mapping)

    if request.method == "POST":
        contrato_id = _parse_int(request.form.get("selNumeroContratos"))
        data_vencimento = _parse_date_br(request.form.get("txtDataVencimento"))
        valor_cobrado = _parse_money(request.form.get("txtValor"))
        data_pagamento = _parse_date_br(request.form.get("txtDataPagamento"))
        valor_pago = _parse_money(request.form.get("txtValorPago"))

        if not contrato_id or not data_vencimento:
            flash("Preencha contrato e data de vencimento.", "warning")
        else:
            try:
                db.session.execute(
                    text(
                        "UPDATE ja_fin_contas_a_receber_contratos SET "
                        "data_vencimento = :data_vencimento, data_pagamento = :data_pagamento, "
                        "valor_cobrado = :valor_cobrado, valor_pago = :valor_pago, "
                        "idcontrato_locacao_manutencao_fk = :contrato "
                        "WHERE id_pk = :id"
                    ),
                    {
                        "id": conta_id,
                        "data_vencimento": data_vencimento,
                        "data_pagamento": data_pagamento,
                        "valor_cobrado": valor_cobrado,
                        "valor_pago": valor_pago,
                        "contrato": contrato_id,
                    },
                )
                db.session.commit()
                flash("Conta atualizada.", "success")
                return redirect(url_for("contratos_bp.contas_receber_contratos"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao atualizar conta a receber contrato")
                flash("Erro ao atualizar conta.", "danger")

    clientes = [
        dict(r._mapping)
        for r in db.session.execute(
            text("SELECT id_pk, nome_fantasia FROM ja_cli_clientes ORDER BY nome_fantasia")
        ).fetchall()
    ]
    contratos = [
        dict(r._mapping)
        for r in db.session.execute(
            text(
                "SELECT id_pk, contrato_numero FROM ja_cli_contrato_locacao_manutencao "
                "WHERE idclientes_fk = :id ORDER BY contrato_numero"
            ),
            {"id": conta.get("idclientes_fk")},
        ).fetchall()
    ]

    conta["data_vencimento_br"] = _format_date(conta.get("data_vencimento"))
    conta["data_pagamento_br"] = _format_date(conta.get("data_pagamento"))

    return render_template(
        "admin/contratos/contas_receber_contratos_form.html",
        conta=conta,
        clientes=clientes,
        contratos=contratos,
        action_url=url_for("contratos_bp.contas_receber_contratos_editar", conta_id=conta_id),
        back_url=url_for("contratos_bp.contas_receber_contratos"),
        allow_more=False,
        subtitle="Atualize a conta a receber.",
    )


@contratos_bp.route("/contas-a-receber/<int:conta_id>/excluir", methods=["POST"])
@login_required
def contas_receber_contratos_excluir(conta_id: int):
    try:
        db.session.execute(
            text("DELETE FROM ja_fin_contas_a_receber_contratos WHERE id_pk = :id"),
            {"id": conta_id},
        )
        db.session.commit()
        flash("Conta removida.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao excluir conta a receber contrato")
        flash("Erro ao excluir conta.", "danger")
    return redirect(url_for("contratos_bp.contas_receber_contratos"))


@contratos_bp.route("/contas-a-receber/contratos/<int:cliente_id>")
@login_required
def contas_receber_contratos_buscar(cliente_id: int):
    selected_id = _parse_int(request.args.get("selected_id"))
    rows = db.session.execute(
        text(
            "SELECT COALESCE(MIN(CASE WHEN id_pk = :selected_id THEN id_pk END), MIN(id_pk)) AS id_pk, "
            "TRIM(contrato_numero) AS contrato_numero "
            "FROM ja_cli_contrato_locacao_manutencao "
            "WHERE idclientes_fk = :id AND contrato_numero IS NOT NULL AND TRIM(contrato_numero) <> '' "
            "GROUP BY TRIM(contrato_numero) "
            "ORDER BY TRIM(contrato_numero)"
        ),
        {"id": cliente_id, "selected_id": selected_id},
    ).fetchall()
    data = [{"id": row.id_pk, "contrato_numero": row.contrato_numero} for row in rows]
    return jsonify(data)


def _format_time(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%H:%M")
        except Exception:
            pass
    raw = str(value)
    return raw[:5]


@contratos_bp.route("/manutencoes-agendadas")
@login_required
def manutencoes_agendadas():
    page = _safe_int(request.args.get("page"), 1)
    ficha_id = _parse_int(request.args.get("ficha"))
    cliente_id = _parse_int(request.args.get("cliente_id"))
    localidade_id = _parse_int(request.args.get("localidade_id"))
    mes_atendimento = _parse_int(request.args.get("mes"))
    nao_realizadas = request.args.get("nao_realizadas") in {"1", "true", "t", "sim"}

    per_page = RESULTS_PER_PAGE
    offset = max(0, (page - 1) * per_page)

    where: list[str] = []
    params: dict[str, Any] = {}
    if ficha_id:
        where.append("m.id_pk = :ficha_id")
        params["ficha_id"] = ficha_id
    if cliente_id:
        where.append("con.idclientes_fk = :cliente_id")
        params["cliente_id"] = cliente_id
    if localidade_id:
        where.append("loc.id_pk = :localidade_id")
        params["localidade_id"] = localidade_id
    if mes_atendimento:
        where.append("MONTH(m.data_inicio_para_atendimento) = :mes")
        params["mes"] = mes_atendimento
    if nao_realizadas:
        where.append("m.data IS NULL")

    where_sql = " AND ".join(where) if where else "1 = 1"

    total = db.session.execute(
        text(
            "SELECT COUNT(DISTINCT m.idcontrato_localidade_equipamento_fk) "
            "FROM ja_cli_manutencao_agendamentos m "
            "LEFT JOIN ja_cli_contrato_localidade_equipamento l ON l.id_pk = m.idcontrato_localidade_equipamento_fk "
            "LEFT JOIN ja_cli_contrato_locacao_manutencao con ON con.id_pk = l.idcontrato_locacao_manutencao_fk "
            "LEFT JOIN ja_cli_clientes cl ON cl.id_pk = con.idclientes_fk "
            "LEFT JOIN ja_prm_localidades loc ON loc.id_pk = l.idlocalidades_fk "
            f"WHERE {where_sql}"
        ),
        params,
    ).scalar() or 0

    group_rows = db.session.execute(
        text(
            "SELECT m.idcontrato_localidade_equipamento_fk AS grupo_id, "
            "MAX(m.data_inicio_para_atendimento) AS max_inicio "
            "FROM ja_cli_manutencao_agendamentos m "
            "LEFT JOIN ja_cli_contrato_localidade_equipamento l ON l.id_pk = m.idcontrato_localidade_equipamento_fk "
            "LEFT JOIN ja_cli_contrato_locacao_manutencao con ON con.id_pk = l.idcontrato_locacao_manutencao_fk "
            "LEFT JOIN ja_cli_clientes cl ON cl.id_pk = con.idclientes_fk "
            "LEFT JOIN ja_prm_localidades loc ON loc.id_pk = l.idlocalidades_fk "
            f"WHERE {where_sql} "
            "GROUP BY m.idcontrato_localidade_equipamento_fk "
            "ORDER BY max_inicio DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": per_page, "offset": offset},
    ).fetchall()

    grupo_ids = [row.grupo_id for row in group_rows if row.grupo_id is not None]
    manutencoes = []
    if grupo_ids:
        rows = db.session.execute(
            text(
                "SELECT m.id_pk, m.data_inicio_para_atendimento, m.data, m.hora_entrada, m.hora_saida, "
                "cl.nome_fantasia, con.contrato_numero, u.nome AS tecnico, loc.localidade, l.descricao, "
                "m.idcontrato_localidade_equipamento_fk AS grupo_id "
                "FROM ja_cli_manutencao_agendamentos m "
                "LEFT JOIN ja_cli_contrato_localidade_equipamento l ON l.id_pk = m.idcontrato_localidade_equipamento_fk "
                "LEFT JOIN ja_cli_contrato_locacao_manutencao con ON con.id_pk = l.idcontrato_locacao_manutencao_fk "
                "LEFT JOIN ja_cli_clientes cl ON cl.id_pk = con.idclientes_fk "
                "LEFT JOIN ja_prm_localidades loc ON loc.id_pk = l.idlocalidades_fk "
                "LEFT JOIN ja_usr_usuarios u ON u.id_pk = m.idusuarios_fk "
                f"WHERE {where_sql} "
                "AND m.idcontrato_localidade_equipamento_fk IN :grupo_ids "
                "ORDER BY m.data_inicio_para_atendimento DESC, m.id_pk DESC"
            ),
            {**params, "grupo_ids": tuple(grupo_ids)},
        ).fetchall()

        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            data = dict(row._mapping)
            localidade = data.get("localidade") or ""
            descricao = data.get("descricao") or ""
            if descricao:
                localidade = f"{localidade} - {descricao}" if localidade else descricao
            data["localidade_label"] = localidade or "-"
            data["data_inicio_br"] = _format_date(data.get("data_inicio_para_atendimento"))
            data["data_visita_br"] = _format_date(data.get("data"))
            data["hora_entrada_br"] = _format_time(data.get("hora_entrada"))
            data["hora_saida_br"] = _format_time(data.get("hora_saida"))
            grouped.setdefault(data.get("grupo_id"), []).append(data)

        for row in group_rows:
            items = grouped.get(row.grupo_id, [])
            if not items:
                continue
            atual = items[0]
            atual["agendamentos_total"] = len(items)
            atual["agendamentos_outros"] = items[1:]
            atual["agendamentos_restantes"] = max(len(items) - 1, 0)
            manutencoes.append(atual)

    clientes = [
        dict(r._mapping)
        for r in db.session.execute(
            text("SELECT id_pk, nome_fantasia FROM ja_cli_clientes ORDER BY nome_fantasia")
        ).fetchall()
    ]
    localidades = [
        dict(r._mapping)
        for r in db.session.execute(
            text("SELECT id_pk, localidade FROM ja_prm_localidades ORDER BY localidade")
        ).fetchall()
    ]
    usuarios = [
        dict(r._mapping)
        for r in db.session.execute(
            text("SELECT id_pk, nome FROM ja_usr_usuarios ORDER BY nome")
        ).fetchall()
    ]

    pagination = _paginate(total, page, per_page)

    return render_template(
        "admin/contratos/manutencoes_agendadas.html",
        manutencoes=manutencoes,
        clientes=clientes,
        localidades=localidades,
        usuarios=usuarios,
        filtros={
            "ficha": ficha_id,
            "cliente_id": cliente_id,
            "localidade_id": localidade_id,
            "mes": mes_atendimento,
            "nao_realizadas": nao_realizadas,
        },
        pagination=pagination,
        build_url=_build_url,
    )


def _agendar_manutencoes(localidade_id: int, contrato: dict[str, Any], dia_base: int) -> None:
    data_assinatura = contrato.get("data_assinatura")
    if isinstance(data_assinatura, str):
        data_assinatura = datetime.strptime(data_assinatura[:10], "%Y-%m-%d").date()
    if isinstance(data_assinatura, datetime):
        data_assinatura = data_assinatura.date()
    if not isinstance(data_assinatura, date):
        data_assinatura = date.today()

    vigencia = _parse_int(contrato.get("vigencia")) or 1
    tipo_atendimento = _parse_int(contrato.get("tipo_atendimento")) or 1
    total_fichas = max(1, int(vigencia / tipo_atendimento))

    base_date = _add_months(data_assinatura, 0, dia_base)

    for i in range(total_fichas):
        agendamento_data = _add_months(base_date, tipo_atendimento * i, dia_base)
        agendamento_id = _next_id("ja_cli_manutencao_agendamentos")
        db.session.execute(
            text(
                "INSERT INTO ja_cli_manutencao_agendamentos "
                "(id_pk, idusuarios_fk, data, hora_entrada, hora_saida, data_inicio_para_atendimento, "
                "idcontrato_localidade_equipamento_fk) "
                "VALUES (:id_pk, :idusuarios_fk, :data, :hora_entrada, :hora_saida, :data_inicio, :localidade)"
            ),
            {
                "id_pk": agendamento_id,
                "idusuarios_fk": None,
                "data": None,
                "hora_entrada": None,
                "hora_saida": None,
                "data_inicio": agendamento_data.strftime("%Y-%m-%d"),
                "localidade": localidade_id,
            },
        )


@contratos_bp.route("/manutencoes-agendadas/novo", methods=["GET", "POST"])
@login_required
def manutencoes_agendadas_novo():
    origin = request.form.get("origin") if request.method == "POST" else None
    if request.method == "POST":
        acao = request.form.get("acao") or "1"
        cliente_id = _parse_int(request.form.get("selCliente"))
        contrato_id = _parse_int(request.form.get("selNumeroContratos"))
        localidade_id = _parse_int(request.form.get("selLocalidade"))

        if not cliente_id or not contrato_id or not localidade_id:
            flash("Preencha cliente, contrato e localidade.", "warning")
            if origin == "list":
                return redirect(url_for("contratos_bp.manutencoes_agendadas"))
        else:
            try:
                if acao == "2":
                    dia_base = _parse_int(request.form.get("txtDiaBaseAtendimento")) or 1
                    contrato_row = db.session.execute(
                        text("SELECT data_assinatura, vigencia, tipo_atendimento FROM ja_cli_contrato_locacao_manutencao WHERE id_pk = :id"),
                        {"id": contrato_id},
                    ).fetchone()
                    contrato = dict(contrato_row._mapping) if contrato_row else {}
                    _agendar_manutencoes(localidade_id, contrato, dia_base)
                else:
                    data_inicio = _parse_date_br(request.form.get("txtDataAtendimento"))
                    if not data_inicio:
                        flash("Informe a data de atendimento.", "warning")
                        raise ValueError("data_inicio")
                    agendamento_id = _next_id("ja_cli_manutencao_agendamentos")
                    db.session.execute(
                        text(
                            "INSERT INTO ja_cli_manutencao_agendamentos "
                            "(id_pk, idusuarios_fk, data, hora_entrada, hora_saida, data_inicio_para_atendimento, "
                            "idcontrato_localidade_equipamento_fk) "
                            "VALUES (:id_pk, :idusuarios_fk, :data, :hora_entrada, :hora_saida, :data_inicio, :localidade)"
                        ),
                        {
                            "id_pk": agendamento_id,
                            "idusuarios_fk": _parse_int(request.form.get("selUsuarios")),
                            "data": _parse_date_br(request.form.get("txtDataVisita")),
                            "hora_entrada": (request.form.get("txtHoraEntrada") or "").strip() or None,
                            "hora_saida": (request.form.get("txtHoraSaida") or "").strip() or None,
                            "data_inicio": data_inicio,
                            "localidade": localidade_id,
                        },
                    )

                db.session.commit()
                if request.form.get("save_more"):
                    flash("Agendamento salvo. Você pode cadastrar outro.", "success")
                    return redirect(url_for("contratos_bp.manutencoes_agendadas_novo"))
                flash("Agendamento cadastrado.", "success")
                return redirect(url_for("contratos_bp.manutencoes_agendadas"))
            except (SQLAlchemyError, ValueError):
                db.session.rollback()
                current_app.logger.exception("Falha ao salvar manutencao agendada")
                flash("Erro ao salvar manutenção.", "danger")
                if origin == "list":
                    return redirect(url_for("contratos_bp.manutencoes_agendadas"))

    clientes = [
        dict(r._mapping)
        for r in db.session.execute(
            text("SELECT id_pk, nome_fantasia FROM ja_cli_clientes ORDER BY nome_fantasia")
        ).fetchall()
    ]
    usuarios = [
        dict(r._mapping)
        for r in db.session.execute(
            text("SELECT id_pk, nome FROM ja_usr_usuarios ORDER BY nome")
        ).fetchall()
    ]

    return render_template(
        "admin/contratos/manutencoes_agendadas_form.html",
        manutencao=None,
        clientes=clientes,
        contratos=[],
        localidades=[],
        usuarios=usuarios,
        action_url=url_for("contratos_bp.manutencoes_agendadas_novo"),
        back_url=url_for("contratos_bp.manutencoes_agendadas"),
        allow_more=True,
        subtitle="Cadastre um novo agendamento de manutencao.",
    )


@contratos_bp.route("/manutencoes-agendadas/<int:agendamento_id>/editar", methods=["GET", "POST"])
@login_required
def manutencoes_agendadas_editar(agendamento_id: int):
    row = db.session.execute(
        text(
            "SELECT m.*, con.idclientes_fk, con.id_pk AS contrato_id "
            "FROM ja_cli_manutencao_agendamentos m "
            "LEFT JOIN ja_cli_contrato_localidade_equipamento l ON l.id_pk = m.idcontrato_localidade_equipamento_fk "
            "LEFT JOIN ja_cli_contrato_locacao_manutencao con ON con.id_pk = l.idcontrato_locacao_manutencao_fk "
            "WHERE m.id_pk = :id"
        ),
        {"id": agendamento_id},
    ).fetchone()
    if not row:
        if request.args.get("format") == "json":
            return jsonify({"error": "Agendamento não encontrado"}), 404
        flash("Agendamento não encontrado.", "warning")
        return redirect(url_for("contratos_bp.manutencoes_agendadas"))
    manutencao = dict(row._mapping)

    if request.args.get("format") == "json":
        return jsonify({
            "id_pk": row.id_pk,
            "idclientes_fk": row.idclientes_fk,
            "contrato_id": row.contrato_id,
            "idcontrato_localidade_equipamento_fk": row.idcontrato_localidade_equipamento_fk,
            "idusuarios_fk": row.idusuarios_fk,
            "data_inicio_br": _format_date(row.data_inicio_para_atendimento),
            "data_visita_br": _format_date(row.data),
            "hora_entrada": row.hora_entrada or "",
            "hora_saida": row.hora_saida or "",
        })

    if request.method == "POST":
        contrato_id = _parse_int(request.form.get("selNumeroContratos"))
        localidade_id = _parse_int(request.form.get("selLocalidade"))
        data_inicio = _parse_date_br(request.form.get("txtDataAtendimento"))
        if not contrato_id or not localidade_id or not data_inicio:
            flash("Preencha contrato, localidade e data de atendimento.", "warning")
        else:
            try:
                db.session.execute(
                    text(
                        "UPDATE ja_cli_manutencao_agendamentos SET "
                        "idusuarios_fk = :idusuarios_fk, data = :data, hora_entrada = :hora_entrada, "
                        "hora_saida = :hora_saida, data_inicio_para_atendimento = :data_inicio, "
                        "idcontrato_localidade_equipamento_fk = :localidade "
                        "WHERE id_pk = :id"
                    ),
                    {
                        "id": agendamento_id,
                        "idusuarios_fk": _parse_int(request.form.get("selUsuarios")),
                        "data": _parse_date_br(request.form.get("txtDataVisita")),
                        "hora_entrada": (request.form.get("txtHoraEntrada") or "").strip() or None,
                        "hora_saida": (request.form.get("txtHoraSaida") or "").strip() or None,
                        "data_inicio": data_inicio,
                        "localidade": localidade_id,
                    },
                )
                db.session.commit()
                flash("Agendamento atualizado.", "success")
                return redirect(url_for("contratos_bp.manutencoes_agendadas"))
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Falha ao atualizar manutencao agendada")
                flash("Erro ao atualizar manutenção.", "danger")

    clientes = [
        dict(r._mapping)
        for r in db.session.execute(
            text("SELECT id_pk, nome_fantasia FROM ja_cli_clientes ORDER BY nome_fantasia")
        ).fetchall()
    ]
    contratos = [
        dict(r._mapping)
        for r in db.session.execute(
            text(
                "SELECT id_pk, contrato_numero FROM ja_cli_contrato_locacao_manutencao "
                "WHERE idclientes_fk = :id ORDER BY contrato_numero"
            ),
            {"id": manutencao.get("idclientes_fk")},
        ).fetchall()
    ]
    localidades = [
        dict(r._mapping)
        for r in db.session.execute(
            text(
                "SELECT l.id_pk, loc.localidade, l.descricao "
                "FROM ja_cli_contrato_localidade_equipamento l "
                "LEFT JOIN ja_prm_localidades loc ON loc.id_pk = l.idlocalidades_fk "
                "WHERE l.idcontrato_locacao_manutencao_fk = :id"
            ),
            {"id": manutencao.get("contrato_id")},
        ).fetchall()
    ]
    usuarios = [
        dict(r._mapping)
        for r in db.session.execute(
            text("SELECT id_pk, nome FROM ja_usr_usuarios ORDER BY nome")
        ).fetchall()
    ]

    manutencao["data_inicio_br"] = _format_date(manutencao.get("data_inicio_para_atendimento"))
    manutencao["data_visita_br"] = _format_date(manutencao.get("data"))

    return render_template(
        "admin/contratos/manutencoes_agendadas_form.html",
        manutencao=manutencao,
        clientes=clientes,
        contratos=contratos,
        localidades=localidades,
        usuarios=usuarios,
        action_url=url_for("contratos_bp.manutencoes_agendadas_editar", agendamento_id=agendamento_id),
        back_url=url_for("contratos_bp.manutencoes_agendadas"),
        allow_more=False,
        subtitle="Atualize o agendamento de manutencao.",
    )


@contratos_bp.route("/manutencoes-agendadas/<int:agendamento_id>/excluir", methods=["POST"])
@login_required
def manutencoes_agendadas_excluir(agendamento_id: int):
    try:
        db.session.execute(
            text("DELETE FROM ja_cli_manutencao_agendamentos WHERE id_pk = :id"),
            {"id": agendamento_id},
        )
        db.session.commit()
        flash("Agendamento removido.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao excluir manutencao agendada")
        flash("Erro ao excluir manutenção.", "danger")
    return redirect(url_for("contratos_bp.manutencoes_agendadas"))


@contratos_bp.route("/manutencoes-agendadas/contratos/<int:cliente_id>")
@login_required
def manutencoes_agendadas_contratos(cliente_id: int):
    rows = db.session.execute(
        text(
            "SELECT id_pk, contrato_numero FROM ja_cli_contrato_locacao_manutencao "
            "WHERE idclientes_fk = :id AND DATE_ADD(data_assinatura, INTERVAL vigencia MONTH) > CURDATE() "
            "ORDER BY contrato_numero"
        ),
        {"id": cliente_id},
    ).fetchall()
    data = [{"id": row.id_pk, "contrato_numero": row.contrato_numero} for row in rows]
    return jsonify(data)


@contratos_bp.route("/manutencoes-agendadas/localidades/<int:contrato_id>")
@login_required
def manutencoes_agendadas_localidades(contrato_id: int):
    rows = db.session.execute(
        text(
            "SELECT l.id_pk, loc.localidade, l.descricao "
            "FROM ja_cli_contrato_localidade_equipamento l "
            "LEFT JOIN ja_prm_localidades loc ON loc.id_pk = l.idlocalidades_fk "
            "WHERE l.idcontrato_locacao_manutencao_fk = :id"
        ),
        {"id": contrato_id},
    ).fetchall()
    data = []
    for row in rows:
        localidade = row.localidade or ""
        descricao = row.descricao or ""
        label = f"{localidade} - {descricao}" if descricao and localidade else (descricao or localidade)
        data.append({"id": row.id_pk, "localidade": label or "-"})
    return jsonify(data)


@contratos_bp.route("/manutencoes-agendadas/ficha", methods=["POST"])
@login_required
def manutencoes_agendadas_ficha():
    fichas = request.form.getlist("ficha")
    if not fichas:
        flash("Selecione pelo menos uma ficha.", "warning")
        return redirect(url_for("contratos_bp.manutencoes_agendadas"))

    ids = [int(x) for x in fichas if str(x).isdigit()]
    if not ids:
        flash("Selecione pelo menos uma ficha.", "warning")
        return redirect(url_for("contratos_bp.manutencoes_agendadas"))

    rows = db.session.execute(
        text(
            "SELECT m.id_pk, m.data_inicio_para_atendimento, "
            "cl.nome_fantasia, cl.razao_social, cl.cnpj AS cliente_cnpj, cl.cpf AS cliente_cpf, "
            "cl.inscricao_estadual AS cliente_ie, cl.email AS cliente_email, cl.telefone1 AS cliente_telefone1, "
            "cl.telefone2 AS cliente_telefone2, cl.contato AS cliente_contato, cl.contato_setor AS cliente_contato_setor, "
            "cl.endereco AS cliente_endereco, cl.endereco_numero AS cliente_endereco_numero, "
            "cl.endereco_complemento AS cliente_endereco_complemento, cl.endereco_bairro AS cliente_endereco_bairro, "
            "cl.endereco_municipio AS cliente_endereco_municipio, cl.endereco_uf AS cliente_endereco_uf, "
            "cl.endereco_cep AS cliente_endereco_cep, "
            "con.contrato_numero, con.manutencao_hardeware, con.manutencao_software, con.locacao, "
            "con.tipo_atendimento, con.reposicao_de_peca, "
            "l.endereco AS inst_endereco, l.endereco_numero AS inst_endereco_numero, "
            "l.endereco_complemento AS inst_endereco_complemento, l.endereco_bairro AS inst_endereco_bairro, "
            "l.endereco_municipio AS inst_endereco_municipio, l.endereco_uf AS inst_endereco_uf, "
            "l.endereco_cep AS inst_endereco_cep, l.contato AS inst_contato, l.contato_setor AS inst_contato_setor, "
            "l.email AS inst_email, l.telefone1 AS inst_telefone, "
            "eq.marca AS eq_marca, eq.modelo AS eq_modelo, eq.numero_serie AS eq_numero_serie "
            "FROM ja_cli_manutencao_agendamentos m "
            "LEFT JOIN ja_cli_contrato_localidade_equipamento l ON l.id_pk = m.idcontrato_localidade_equipamento_fk "
            "LEFT JOIN ja_cli_contrato_locacao_manutencao con ON con.id_pk = l.idcontrato_locacao_manutencao_fk "
            "LEFT JOIN ja_cli_clientes cl ON cl.id_pk = con.idclientes_fk "
            "LEFT JOIN ja_cli_contrato_equipamentos eq ON eq.idcontrato_localidade_equipamento_fk = l.id_pk "
            "WHERE m.id_pk IN :ids"
        ),
        {"ids": tuple(ids)},
    ).fetchall()

    fichas_rows = {}
    for row in rows:
        d = dict(row._mapping)
        agend_id = d["id_pk"]
        if agend_id not in fichas_rows:
            fichas_rows[agend_id] = {
                "id_pk": d["id_pk"],
                "data_inicio_para_atendimento": d["data_inicio_para_atendimento"],
                "data_inicio_br": _format_date(d["data_inicio_para_atendimento"]),
                "referencia": d["data_inicio_para_atendimento"].strftime("%m/%Y") if d["data_inicio_para_atendimento"] else "",
                "razao_social": d["razao_social"] or d["nome_fantasia"] or "-",
                "cliente_endereco_completo": f"{d['cliente_endereco'] or ''}, {d['cliente_endereco_numero'] or ''} {d['cliente_endereco_complemento'] or ''}".strip(", "),
                "cliente_bairro": d["cliente_endereco_bairro"] or "",
                "cliente_cidade": d["cliente_endereco_municipio"] or "",
                "cliente_cep": d["cliente_endereco_cep"] or "",
                "cliente_estado": d["cliente_endereco_uf"] or "",
                "cliente_cnpj_cpf": d["cliente_cnpj"] or d["cliente_cpf"] or "",
                "cliente_ie": d["cliente_ie"] or "",
                "cliente_contato": d["cliente_contato"] or "",
                "cliente_contato_setor": d["cliente_contato_setor"] or "",
                "cliente_email": d["cliente_email"] or "",
                "cliente_telefone": d["cliente_telefone1"] or d["cliente_telefone2"] or "",
                
                "inst_endereco_completo": f"{d['inst_endereco'] or ''}, {d['inst_endereco_numero'] or ''} {d['inst_endereco_complemento'] or ''}".strip(", "),
                "inst_bairro": d["inst_endereco_bairro"] or "",
                "inst_cidade": d["inst_endereco_municipio"] or "",
                "inst_cep": d["inst_endereco_cep"] or "",
                "inst_estado": d["inst_endereco_uf"] or "",
                "inst_contato": d["inst_contato"] or "",
                "inst_contato_setor": d["inst_contato_setor"] or "",
                "inst_email": d["inst_email"] or "",
                "inst_telefone": d["inst_telefone"] or "",
                
                "contrato_numero": d["contrato_numero"] or "-",
                "tipo_atendimento_label": "LOCAÇÃO" if d["locacao"] == 1 else (
                    "MANUTENÇÃO DE HARDWARE E SOFTWARE" if d["manutencao_hardeware"] == 1 and d["manutencao_software"] == 1 else (
                        "MANUTENÇÃO DE HARDWARE" if d["manutencao_hardeware"] == 1 else (
                            "MANUTENÇÃO DE SOFTWARE" if d["manutencao_software"] == 1 else "MANUTENÇÃO"
                        )
                    )
                ),
                "categoria_atendimento": (
                    "MENSAL" if d["tipo_atendimento"] == 1 else (
                        "BIMESTRAL" if d["tipo_atendimento"] == 2 else (
                            "TRIMESTRAL" if d["tipo_atendimento"] == 3 else (
                                "QUADRIMESTRAL" if d["tipo_atendimento"] == 4 else (
                                    "SEMESTRAL" if d["tipo_atendimento"] == 6 else (
                                        "ANUAL" if d["tipo_atendimento"] == 12 else "AVULSO"
                                    )
                                )
                            )
                        )
                    )
                ),
                "tipo_contrato": "COM PEÇA" if d["reposicao_de_peca"] == 1 else "SEM PEÇA",
                "equipamentos": []
            }
        
        if d.get("eq_marca") or d.get("eq_modelo") or d.get("eq_numero_serie"):
            eq_dict = {
                "marca": d["eq_marca"] or "",
                "modelo": d["eq_modelo"] or "",
                "numero_serie": d["eq_numero_serie"] or ""
            }
            if eq_dict not in fichas_rows[agend_id]["equipamentos"]:
                fichas_rows[agend_id]["equipamentos"].append(eq_dict)

    fichas_list = [fichas_rows[k] for k in sorted(fichas_rows.keys())]

    return render_template("admin/contratos/ficha_manutencao.html", fichas=fichas_list, date=date)
