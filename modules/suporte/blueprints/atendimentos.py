"""Blueprint responsável pelos painéis de suporte."""

from __future__ import annotations

import csv
import io
import math
import re
import secrets
import time
import traceback
from pathlib import Path
import requests
from urllib.parse import urlencode
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unicodedata import normalize

from sqlalchemy import inspect, nullsfirst, text
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    send_file,
    session,
    url_for,
)
from utils.helpers import (
    wants_json as _wants_json,
    normalize_dept_name as _normalize_dept_name,
)
from flask_login import current_user, login_required

from extensions import db
from modules.audit.utils import write_audit
from modules.propostas.blueprints.auth.permissions_utils import normalize_role_key, raw_permissions, current_permissions
from modules.propostas.models import AgendaEntry, User

from ..forms import (
    AtendimentoFilterForm,
    ChamadoFiltroForm,
    ConcluidoFilterForm,
    CriarChamadoForm,
    EditarAtendimentoForm,
    EditarChamadoForm,
    FecharChamadoForm,
    NovoAtendimentoForm,
)
from ..models import AtendimentoSuporte, AtendimentoSuporteLog, UltimoAtendimento
from ..services.atendimentos import (
    STATUS_DISPLAY_MAP,
    fetch_paginated_atendimentos,
)
from ..services.chamados import (
    create_chamado,
    delete_chamado,
    fetch_chamados,
    count_chamados,
    get_chamado,
    get_region,
    list_regions,
    update_chamado,
)
from ..services.cnpj import (
    ReceitaAPIError,
    fetch_receita_data,
    normalize_cnpj,
    upsert_empresa_from_receita,
    ensure_empresa_record,
)
from ..services.email import (
    send_atendimento_concluido_email,
    send_atendimento_meet_email,
    send_chamado_satisfacao_email,
)
from ..services.logs import log_changes
from ..services.meetings import create_meet_event, update_meet_event
from ..services.meetings import meet_config_status
from ..services.uploads import (
    delete_support_file,
    find_support_file,
    resolve_support_file,
    save_support_file,
)
from .shared_agenda import register_agenda_routes

SUPPORT_TYPE_ICONS = {
    "treinamento coletivo": "fa-solid fa-people-group",
    "treinamento": "fa-solid fa-person-chalkboard",
    "atendimento": "fa-solid fa-headset",
    "instalacao": "fa-solid fa-screwdriver-wrench",
    "demonstracao": "fa-solid fa-person-chalkboard",
    "consultoria": "fa-solid fa-handshake-angle",
    "visita": "fa-solid fa-person-walking",
    "default": "fa-solid fa-clipboard-list",
}


def _normalize_type_key(value: str | None) -> str:
    if not value:
        return ""
    normalized = normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_value.lower().strip()


def resolve_type_icon(label: str | None) -> str:
    key = _normalize_type_key(label)
    for pattern, icon in SUPPORT_TYPE_ICONS.items():
        if pattern == "default":
            continue
        if key.startswith(pattern):
            return icon
    return SUPPORT_TYPE_ICONS["default"]


def _is_collective_training(label: str | None) -> bool:
    return "treinamento coletivo" in _normalize_type_key(label)


def _split_emails(*values: str | None) -> List[str]:
    raw_items: List[str] = []
    for value in values:
        if not value:
            continue
        raw_items.extend(re.split(r"[,\n;]+", value))
    emails: List[str] = []
    seen: set[str] = set()
    for item in raw_items:
        email = item.strip()
        if not email:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        emails.append(email)
    return emails


def _create_support_meet(
    *,
    cliente: str,
    tipo_atendimento: str | None,
    os_entrada: str | None,
    criado_por: str | None,
    start_dt: datetime,
    attendees: List[str],
    send_updates: bool = True,
) -> tuple[str | None, str | None]:
    duration = current_app.config.get("GOOGLE_MEET_DURATION_MINUTES", 180)
    summary = f"Atendimento Suporte - {cliente}".strip()
    description_lines = [
        f"Cliente: {cliente}",
        f"Tipo: {tipo_atendimento or '-'}",
        f"OS entrada: {os_entrada or '-'}",
        f"Criado por: {criado_por or '-'}",
    ]
    description = "\n".join(description_lines)
    return create_meet_event(
        summary=summary,
        description=description,
        start_dt=start_dt,
        duration_minutes=duration,
        attendees=attendees,
        send_updates=send_updates,
    )


OS_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
)

OS_TIME_FORMATS = ("%H:%M:%S", "%H:%M")


def _parse_os_datetime(value, *, date_hint: datetime | date | None = None):
    """Parse valores heterogêneos de datas das OS."""
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())

    normalized_hint: date | None = None
    if isinstance(date_hint, datetime):
        normalized_hint = date_hint.date()
    elif isinstance(date_hint, date):
        normalized_hint = date_hint

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass

        for fmt in OS_DATETIME_FORMATS:
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue

        for fmt in OS_TIME_FORMATS:
            try:
                parsed_time = datetime.strptime(raw, fmt).time()
            except ValueError:
                continue
            base_for_time = normalized_hint or datetime.now().date()
            return datetime.combine(base_for_time, parsed_time)

    return None


def _format_br_date(value):
    dt = _parse_os_datetime(value)
    if dt:
        return dt.strftime("%d/%m/%Y")
    return value if isinstance(value, str) and value else None


def _format_br_datetime(value):
    dt = _parse_os_datetime(value)
    if dt:
        return dt.strftime("%d/%m/%Y %H:%M")
    return value if isinstance(value, str) and value else None


def _sla_minutes(raw_value: str | None) -> int:
    value = str(raw_value or "").strip().casefold()
    if value in {"sim", "sim.", "s"}:
        return 48 * 60
    return 72 * 60


def _working_seconds_between(start: datetime, end: datetime) -> int:
    if not start or not end:
        return 0
    if end < start:
        start, end = end, start
    current = start
    total_seconds = 0
    while current < end:
        weekday = current.weekday()  # 0=Seg, 6=Dom
        next_day = datetime.combine(current.date() + timedelta(days=1), datetime.min.time())
        segment_end = end if end < next_day else next_day
        if weekday < 5:
            total_seconds += int((segment_end - current).total_seconds())
        current = next_day
    return total_seconds


def _format_os_duration(
    start: datetime | None, end: datetime | None
) -> tuple[str | None, int | None]:
    if not start or not end:
        return None, None
    delta_seconds = max(0, _working_seconds_between(start, end))
    total_minutes = delta_seconds // 60
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}", total_minutes


def _sort_chamado_entry(entry: Dict[str, Any]) -> datetime:
    for key in ("data_os_tecnico", "hora_saida", "data", "data_os_criada"):
        dt = _parse_os_datetime(entry.get(key))
        if dt:
            return dt
    return datetime.min


def _decorate_chamados(
    chamados: List[Dict[str, Any]], *, closed: bool = False
) -> List[Dict[str, Any]]:
    now = datetime.now()
    enriched: List[Dict[str, Any]] = []

    for entry in chamados:
        data = dict(entry)

        data["data_display"] = _format_br_date(data.get("data"))
        data["data_os_criada_display"] = _format_br_datetime(
            data.get("data_os_criada")
        )

        created_at = _parse_os_datetime(data.get("data_os_criada"))
        base_date = created_at or _parse_os_datetime(data.get("data"))

        opened_at = (
            _parse_os_datetime(data.get("hora_entrada"), date_hint=base_date)
            or created_at
            or base_date
        )

        closed_at = None
        if closed:
            tecnico_at = _parse_os_datetime(data.get("data_os_tecnico"))
            closed_date_hint = tecnico_at or base_date or opened_at
            closed_at = (
                tecnico_at
                or _parse_os_datetime(
                    data.get("hora_saida"), date_hint=closed_date_hint
                )
                or base_date
            )

        tempo_label, total_minutes = _format_os_duration(opened_at, closed_at or now)
        tempo_display = f"{tempo_label}h" if tempo_label else None

        sla_minutes = _sla_minutes(data.get("contrato"))

        if total_minutes is None:
            tempo_class = "unknown"
            tempo_text = None
        else:
            within_sla = total_minutes <= sla_minutes
            if closed:
                tempo_class = "ok" if within_sla else "danger"
                tempo_text = f"Atendimento em {tempo_label}h"
                if not within_sla:
                    tempo_text += " · Fora do período"
            else:
                tempo_class = "warning" if within_sla else "danger"
                tempo_text = f"OS aberta há {tempo_label}h"
                if not within_sla:
                    tempo_text += " · Está atrasada"

        data["tempo_os_aberta"] = tempo_display
        data["tempo_os_class"] = tempo_class
        data["tempo_os_text"] = tempo_text
        data["tempo_os_hint"] = (
            f"Encerrada em {closed_at.strftime('%d/%m/%Y %H:%M')}"
            if closed and closed_at
            else (f"Criada em {opened_at.strftime('%d/%m/%Y %H:%M')}" if opened_at else None)
        )

        raw_tecnico = data.get("tecnico") or ""
        data["sem_tecnico"] = (raw_tecnico.strip() == "") if isinstance(raw_tecnico, str) else not bool(raw_tecnico)

        enriched.append(data)

    return enriched


def _resolve_chamado_file_ref(item: Dict[str, Any], kind: str) -> str | None:
    stored = (
        item.get("arquivo_entrada")
        if kind == "entrada"
        else item.get("arquivo_saida")
    ) or (
        item.get("arq_entrada")
        if kind == "entrada"
        else item.get("arq_saida")
    )
    if stored:
        return stored
    os_code = item.get("ordem_servico")
    fallback = find_support_file(os_code, kind) if os_code else None
    if fallback:
        return fallback
    if kind == "saida":
        numero_manutencao = item.get("numero_manutencao")
        if numero_manutencao and numero_manutencao != os_code:
            return find_support_file(numero_manutencao, kind)
    return None


support_bp = Blueprint(
    "support_bp",
    __name__,
    url_prefix="/admin/suporte",
)
register_agenda_routes(support_bp)

tech_bp = Blueprint(
    "tech_bp",
    __name__,
    url_prefix="/admin/tecnica",
)

def _meet_oauth_config():
    client_id = current_app.config.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = current_app.config.get("GOOGLE_OAUTH_CLIENT_SECRET")
    redirect_uri = current_app.config.get("GOOGLE_OAUTH_REDIRECT_URI")
    if not redirect_uri:
        redirect_uri = url_for("support_bp.meet_oauth_callback", _external=True)
    return client_id, client_secret, redirect_uri


@support_bp.route("/meet/oauth/start")
@login_required
def meet_oauth_start():
    client_id, _client_secret, redirect_uri = _meet_oauth_config()
    if not client_id or not redirect_uri:
        flash("Configure o OAuth do Google Calendar antes de autorizar.", "warning")
        return redirect(url_for("support_bp.atendimentos_dashboard"))
    state = secrets.token_urlsafe(16)
    session["meet_oauth_state"] = state
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return redirect(url)


@support_bp.route("/meet/oauth/callback")
@login_required
def meet_oauth_callback():
    error = request.args.get("error")
    if error:
        flash(f"OAuth recusado: {error}", "danger")
        return redirect(url_for("support_bp.atendimentos_dashboard"))
    state = request.args.get("state")
    if not state or state != session.get("meet_oauth_state"):
        flash("Falha na validação do OAuth.", "danger")
        return redirect(url_for("support_bp.atendimentos_dashboard"))
    code = request.args.get("code")
    if not code:
        flash("OAuth sem código de autorização.", "danger")
        return redirect(url_for("support_bp.atendimentos_dashboard"))

    client_id, client_secret, redirect_uri = _meet_oauth_config()
    if not client_id or not client_secret:
        flash("OAuth não configurado (client id/secret).", "danger")
        return redirect(url_for("support_bp.atendimentos_dashboard"))

    token_url = current_app.config.get(
        "GOOGLE_OAUTH_TOKEN_URI", "https://oauth2.googleapis.com/token"
    )
    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    resp = requests.post(token_url, data=payload, timeout=20)
    if resp.status_code != 200:
        current_app.logger.error("OAuth token exchange failed: %s", resp.text)
        flash("Falha ao obter o token OAuth.", "danger")
        return redirect(url_for("support_bp.atendimentos_dashboard"))

    data = resp.json() or {}
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        message = (
            "Token de atualização não retornado. Revogue o acesso em sua conta Google "
            "e autorize novamente para gerar o refresh token."
        )
        return render_template_string(
            "<h3>OAuth concluído</h3><p>{{ message }}</p>", message=message
        )

    instructions = (
        "Adicione este valor em GOOGLE_OAUTH_REFRESH_TOKEN no .env e reinicie a aplicação."
    )
    return render_template_string(
        "<h3>OAuth concluído</h3><p><strong>Refresh token:</strong></p>"
        "<pre>{{ token }}</pre><p>{{ instructions }}</p>",
        token=refresh_token,
        instructions=instructions,
    )


def _store_precreated_meet(event_id: str | None, link: str | None, start_dt: datetime | None):
    if not event_id or not link:
        return
    cached = session.get("meet_precreated")
    if not isinstance(cached, dict):
        cached = {}
    cached[event_id] = {
        "link": link,
        "start": start_dt.isoformat() if start_dt else None,
        "ts": int(time.time()),
    }
    if len(cached) > 8:
        ordered = sorted(cached.items(), key=lambda item: item[1].get("ts", 0))
        for key, _payload in ordered[:-8]:
            cached.pop(key, None)
    session["meet_precreated"] = cached


def _get_precreated_meet(event_id: str | None, link: str | None = None) -> dict | None:
    if not event_id:
        return None
    cached = session.get("meet_precreated")
    if not isinstance(cached, dict):
        return None
    entry = cached.get(event_id)
    if not entry:
        return None
    if link and entry.get("link") != link:
        return None
    return entry


@support_bp.route("/meet/preview", methods=["POST"])
@login_required
def meet_preview():
    payload = request.get_json(silent=True) or request.form
    meet_start_raw = (payload.get("meet_start") or "").strip()
    if not meet_start_raw:
        return jsonify({"ok": False, "message": "Informe a data e hora da reuniao."}), 400

    start_dt = _parse_os_datetime(meet_start_raw)
    if not start_dt:
        return jsonify({"ok": False, "message": "Data e hora inválida."}), 400

    provided_link = (payload.get("meet_link") or "").strip()
    provided_event_id = (payload.get("meet_event_id") or "").strip()
    if provided_link and provided_event_id:
        cached = _get_precreated_meet(provided_event_id, provided_link)
        if cached:
            cached_start = cached.get("start") if isinstance(cached, dict) else None
            resolved_start = _parse_os_datetime(cached_start) or start_dt
            return jsonify(
                {
                    "ok": True,
                    "meet_link": provided_link,
                    "meet_event_id": provided_event_id,
                    "meet_start": resolved_start.isoformat() if resolved_start else None,
                }
            )

    meet_session_key = (payload.get("meet_session_key") or "").strip() or None
    tipo_atendimento = payload.get("tipo_atendimento") or ""
    is_collective = _is_collective_training(tipo_atendimento)
    attendees = _split_emails(payload.get("email"), payload.get("meet_extra_emails"))

    meet_link = None
    meet_event_id = None
    meet_start_resolved = start_dt

    config_status = meet_config_status()
    if not config_status.get("ok"):
        reason = config_status.get("reason")
        if reason == "missing_client":
            message = "Cliente Google API nao disponivel no servidor."
        elif reason == "missing_calendar":
            message = "Defina GOOGLE_CALENDAR_ID ou GOOGLE_DELEGATED_USER no .env."
        elif reason == "refresh_failed":
            message = (
                "Nao foi possivel atualizar o token OAuth. "
                "Verifique GOOGLE_OAUTH_REFRESH_TOKEN/CLIENT_ID/CLIENT_SECRET."
            )
        elif reason == "service_file_missing":
            message = "Arquivo do service account não encontrado. Verifique GOOGLE_SERVICE_ACCOUNT_FILE."
        elif reason == "service_account_invalid":
            message = "Nao foi possivel carregar o service account do Google."
        else:
            message = (
                "Credenciais Google Meet nao configuradas. Defina "
                "GOOGLE_SERVICE_ACCOUNT_FILE ou GOOGLE_OAUTH_REFRESH_TOKEN/CLIENT_ID/CLIENT_SECRET."
            )
        return jsonify({"ok": False, "message": message}), 400

    if is_collective and meet_session_key:
        existing = (
            AtendimentoSuporte.query.filter(
                AtendimentoSuporte.meet_session_key == meet_session_key,
                AtendimentoSuporte.meet_link.isnot(None),
            )
            .order_by(AtendimentoSuporte.id.desc())
            .first()
        )
        if existing and existing.meet_link:
            meet_link = existing.meet_link
            meet_event_id = existing.meet_event_id
            meet_start_resolved = existing.meet_start or start_dt

    if not meet_link:
        try:
            meet_link, meet_event_id = _create_support_meet(
                cliente=(payload.get("cliente") or "").strip(),
                tipo_atendimento=tipo_atendimento,
                os_entrada=(payload.get("os_entrada") or "").strip(),
                criado_por=getattr(current_user, "nome_completo", None) or current_user.email,
                start_dt=start_dt,
                attendees=[],
                send_updates=False,
            )
        except Exception:
            current_app.logger.exception("Falha ao criar link do Meet em preview.")
            return jsonify({"ok": False, "message": "Não foi possível gerar o link do Meet."}), 500

    if not meet_link:
        return jsonify({"ok": False, "message": "Não foi possível gerar o link do Meet."}), 500

    _store_precreated_meet(meet_event_id, meet_link, meet_start_resolved)
    return jsonify(
        {
            "ok": True,
            "meet_link": meet_link,
            "meet_event_id": meet_event_id,
            "meet_start": meet_start_resolved.isoformat() if meet_start_resolved else None,
        }
    )


_CHAMADOS_BLUEPRINTS = {"support_bp", "tech_bp"}


def _current_chamados_namespace():
    try:
        blueprint = request.blueprint
    except RuntimeError:
        blueprint = None

    if blueprint in _CHAMADOS_BLUEPRINTS:
        return blueprint

    path = getattr(request, "path", "") or ""
    if path.startswith("/admin/tecnica"):
        return "tech_bp"
    return "support_bp"






def _dept_names(user=None) -> set[str]:
    actor = user or current_user
    names: set[str] = set()
    try:
        for name in getattr(actor, "department_names", []) or []:
            normalized = _normalize_dept_name(name)
            if normalized:
                names.add(normalized)
    except Exception:
        return set()
    return names


def _deny_access(area_label: str):
    if "/api/" in getattr(request, "path", "") or _wants_json():
        return jsonify({
            "error": "Access denied",
            "success": False,
            "message": f"Você não tem permissão para acessar {area_label}."
        }), 403
    flash(
        "Você não tem permissão para acessar esta área. Procure seu superior caso precise de acesso.",
        "warning",
    )
    return redirect(url_for("sem_permissao", area=area_label))


@support_bp.before_request
def _ensure_permission():
    from flask import request
    endpoint = getattr(request, "endpoint", "") or ""
    if endpoint == "sem_permissao":
        return
    if not current_user.is_authenticated and not session.get("usuario_id") and not session.get("user_id"):
        if "/api/" in getattr(request, "path", "") or _wants_json():
            return jsonify({"error": "Authentication required", "success": False, "message": "Autenticação necessária"}), 401
        try:
            login_url = url_for("auth_bp.login", next=request.full_path if request.method == "GET" else None)
        except Exception:
            login_url = "/login"
        return redirect(login_url)

    role_key = normalize_role_key(getattr(current_user, "tipo", None) or session.get("tipo"))
    if role_key in ("admin", "gestor"):
        return
    perms = current_permissions()
    if perms.get("admin_suporte") or perms.get("assistencia_atendimentos"):
        return
    allowed_depts = {"SUPORTE", "ASSISTENCIA TECNICA"}
    if _dept_names() & allowed_depts:
        return
    return _deny_access("Suporte")


@tech_bp.before_request
def _ensure_tecnica_permission():
    from flask import request
    endpoint = getattr(request, "endpoint", "") or ""
    if endpoint == "sem_permissao":
        return
    if not current_user.is_authenticated and not session.get("usuario_id") and not session.get("user_id"):
        if "/api/" in getattr(request, "path", "") or _wants_json():
            return jsonify({"error": "Authentication required", "success": False, "message": "Autenticação necessária"}), 401
        try:
            login_url = url_for("auth_bp.login", next=request.full_path if request.method == "GET" else None)
        except Exception:
            login_url = "/login"
        return redirect(login_url)

    role_key = normalize_role_key(getattr(current_user, "tipo", None) or session.get("tipo"))
    if role_key in ("admin", "gestor"):
        return
    perms = current_permissions()
    if perms.get("admin_agenda_tecnica") or perms.get("admin_assistencia"):
        return
    allowed_depts = {"ASSISTENCIA TECNICA", "ESTOQUE", "OFICINA"}
    if _dept_names() & allowed_depts:
        return
    return _deny_access("Técnica")


@support_bp.route("/atendimentos")
@login_required
def atendimentos_dashboard():
    technicians = _load_technicians()

    form = AtendimentoFilterForm(request.args)
    form.usuario_designado.choices = _technician_choices("Todos", technicians=technicians)
    
    create_form = NovoAtendimentoForm()
    edit_form = EditarAtendimentoForm()
    create_form.usuario_designado.choices = _technician_choices("Selecione", technicians=technicians)
    edit_form.usuario_designado.choices = _technician_choices(technicians=technicians)
    
    try:
        tipo_choices = _distinct_tipo_choices("Selecione")
        sistema_choices = _distinct_sistema_choices("Selecione")
        create_form.tipo_atendimento.choices = tipo_choices
        edit_form.tipo_atendimento.choices = tipo_choices
        create_form.sistema.choices = sistema_choices
        edit_form.sistema.choices = sistema_choices
    except Exception:
        current_app.logger.exception("Falha ao carregar choices para tipo/sistema")

    def _truncate_obs(text: str | None, limit: int = 30) -> str:
        cleaned = (text or "").strip()
        if len(cleaned) <= limit:
            return cleaned
        return f"{cleaned[:limit].rstrip()}..."

    today = date.today()
    agenda_entries = (
        AgendaEntry.query.options(joinedload(AgendaEntry.tecnico))
        .filter(AgendaEntry.data_atendimento == today)
        .order_by(AgendaEntry.periodo.asc(), AgendaEntry.id.desc())
        .all()
    )
    agenda_absences = []
    for entry in agenda_entries:
        user = entry.tecnico
        if not user or not user.is_active:
            continue
        if not _is_support_user(user):
            continue
        tecnico_nome = user.nome_completo or user.email or "Tecnico"
        search_param = tecnico_nome
        agenda_url = url_for("assist_bp.agenda_tecnica")
        query = urlencode({"search": search_param, "agenda_id": entry.id})
        agenda_absences.append(
            {
                "tecnico": tecnico_nome,
                "unidade": entry.unidade,
                "periodo": entry.periodo,
                "obs_short": _truncate_obs(entry.obs),
                "agenda_url": f"{agenda_url}?{query}" if query else agenda_url,
            }
        )

    # Query overdue support calls (older than 24 hours)
    from modules.suporte.models import AtendimentoSuporte
    from sqlalchemy import or_

    overdue_limit = datetime.now() - timedelta(hours=24)
    db_overdue = AtendimentoSuporte.query.filter(
        or_(
            AtendimentoSuporte.status.is_(None),
            AtendimentoSuporte.status.notin_(["Concluido", "concluido"])
        ),
        AtendimentoSuporte.data_entrada < overdue_limit
    ).order_by(AtendimentoSuporte.data_entrada.asc()).all()

    overdue_calls = []
    for c in db_overdue:
        entry_date = None
        if c.data_entrada:
            if hasattr(c.data_entrada, "date"):
                entry_date = c.data_entrada.date()
            elif isinstance(c.data_entrada, date):
                entry_date = c.data_entrada
            elif isinstance(c.data_entrada, str):
                txt = c.data_entrada.strip()
                if not txt.startswith("0000-00-00"):
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
                        try:
                            entry_date = datetime.strptime(txt, fmt).date()
                            break
                        except ValueError:
                            continue
        if not entry_date:
            entry_date = today

        delay_days = (today - entry_date).days
        os_label = c.os_entrada if c.os_entrada else "Sem O.S"
        overdue_calls.append({
            "id": c.id,
            "cliente": c.cliente,
            "os": os_label,
            "delay_days": delay_days,
        })

    return render_template(
        "admin/support/atendimentos.html",
        form=form,
        status_labels=STATUS_DISPLAY_MAP,
        create_form=create_form,
        edit_form=edit_form,
        api_endpoint=url_for("support_bp.atendimentos_api"),
        technicians=technicians,
        agenda_absences=agenda_absences,
        agenda_date=today.strftime("%d/%m/%Y"),
        overdue_calls=overdue_calls,
    )


@support_bp.route("/api/atendimentos")
@login_required
def atendimentos_api():
    form = AtendimentoFilterForm(request.args)
    form.usuario_designado.choices = _technician_choices("Todos")
    form.validate()

    page = request.args.get("page", default=1, type=int)
    per_page = 20

    pagination, counters, status_key = fetch_paginated_atendimentos(
        form, page=page, per_page=per_page
    )

    items = []
    for item in pagination.items:
        items.append({
            "id": item.id,
            "cliente": item.cliente,
            "cnpj": item.cnpj,
            "status": item.status,
            "status_label": item.status_label(),
            "data_entrada": item.data_entrada.isoformat() if item.data_entrada else None,
            "data_atendimento": item.data_atendimento.isoformat() if item.data_atendimento else None,
            "tipo_atendimento": item.tipo_atendimento,
            "tipo_icon": resolve_type_icon(item.tipo_atendimento),
            "descricao": item.descricao,
            "resumo_atendimento": item.resumo_atendimento,
            "observacoes": item.observacoes,
            "observacoes_alerta": item.observacoes_alerta,
            "os_entrada": item.os_entrada,
            "os_saida": item.os_saida,
            "arq_entrada": item.arq_entrada,
            "arq_saida": item.arq_saida,
            "tecnico": item.assigned_user.nome_completo if item.assigned_user else "Não atribuído",
            "tecnico_id": item.usuario_designado or 0,
            "unit_code": item.assigned_user.unit_code if item.assigned_user else None,
            "update_url": url_for('support_bp.editar_atendimento', atendimento_id=item.id),
            "json_url": url_for('support_bp.atendimento_json', atendimento_id=item.id),
            "logs_url": url_for('support_bp.atendimento_logs', atendimento_id=item.id),
            "download_entrada": url_for('support_bp.download_arquivo', atendimento_id=item.id, kind='entrada') if item.arq_entrada else None,
            "download_saida": url_for('support_bp.download_arquivo', atendimento_id=item.id, kind='saida') if item.arq_saida else None,
        })

    return jsonify({
        "items": items,
        "counters": counters,
        "status_key": status_key,
        "pagination": {
            "page": pagination.page,
            "pages": pagination.pages,
            "total": pagination.total,
            "has_prev": pagination.has_prev,
            "has_next": pagination.has_next,
            "prev_num": pagination.prev_num,
            "next_num": pagination.next_num
        }
    })


@support_bp.route("/chamados")
@login_required
def chamados_dashboard():
    regions = list_regions()
    if not regions:
        flash("Nenhuma unidade de chamados configurada.", "warning")
        return redirect(url_for("support_bp.atendimentos_dashboard"))

    form = ChamadoFiltroForm(request.args)
    form.region.choices = [(region.slug, region.label) for region in regions]
    selected_region = get_region(form.region.data) if form.region.data else regions[0]
    form.tecnico.choices = _distinct_chamado_choices(selected_region, "tecnico", for_filter=True)

    create_form = CriarChamadoForm()
    edit_form = EditarChamadoForm()
    close_form = FecharChamadoForm()
    _set_region_choices(create_form)
    _set_region_choices(edit_form)
    _populate_chamado_form_choices(
        selected_region,
        create_form=create_form,
        edit_form=edit_form,
        close_form=close_form,
    )

    namespace = _current_chamados_namespace()
    return render_template(
        "admin/support/chamados.html",
        form=form,
        regions=regions,
        create_form=create_form,
        edit_form=edit_form,
        close_form=close_form,
        api_endpoint=url_for(f"{namespace}.chamados_api"),
        chamados_namespace=namespace,
        assistencia_tabs=False,
    )


@support_bp.route("/api/chamados")
@login_required
def chamados_api():
    regions = list_regions()
    form = ChamadoFiltroForm(request.args)
    form.region.choices = [(region.slug, region.label) for region in regions]
    selected_region = get_region(form.region.data) if form.region.data else regions[0]
    form.tecnico.choices = _distinct_chamado_choices(selected_region, "tecnico", for_filter=True)
    if not form.region.data:
        form.region.data = regions[0].slug

    region = get_region(form.region.data)
    if not region:
        region = regions[0]

    status_group = request.args.get("status_group", "")
    status_val = form.status.data or request.args.get("status") or None
    
    # Se nao houver status especifico selecionado, filtramos pelo grupo ativo
    if not status_val and status_group:
        if status_group == "open":
            status_val = ["ABERTO", "OFICINA"]
        elif status_group == "closed":
            status_val = ["FECHADO"]

    total_items = count_chamados(
        region,
        data=form.data_visita.data.isoformat() if form.data_visita.data else None,
        tecnico=form.tecnico.data or None,
        status=status_val,
        ordem_servico=form.ordem_servico.data or None,
    )

    per_page = 5  # Forçado para 5 conforme solicitado
    pages = max(1, math.ceil(total_items / per_page))
    page = max(1, min(request.args.get("page", 1, type=int), pages))
    offset = (page - 1) * per_page

    closed = (form.status.data == "FECHADO" or status_group == "closed")
    chamados = fetch_chamados(
        region,
        data=form.data_visita.data.isoformat() if form.data_visita.data else None,
        tecnico=form.tecnico.data or None,
        status=status_val,
        ordem_servico=form.ordem_servico.data or None,
        limit=per_page,
        offset=offset,
        order_by_closed=closed,
    )

    decorated = _decorate_chamados(chamados, closed=closed)
    page_items = decorated

    namespace = _current_chamados_namespace()
    for item in page_items:
        item["update_url"] = url_for(f"{namespace}.editar_chamado", region_slug=region.slug, chamado_id=item["id"])
        item["close_url"] = url_for(f"{namespace}.fechar_chamado", region_slug=region.slug, chamado_id=item["id"])
        item["delete_url"] = url_for(f"{namespace}.excluir_chamado", region_slug=region.slug, chamado_id=item["id"])
        item["region_slug"] = region.slug
        arquivo_entrada = _resolve_chamado_file_ref(item, "entrada")
        arquivo_saida = _resolve_chamado_file_ref(item, "saida")
        item["download_entrada"] = (
            url_for(f"{namespace}.download_chamado_arquivo", region_slug=region.slug, chamado_id=item["id"], kind="entrada")
            if arquivo_entrada
            else None
        )
        item["download_saida"] = (
            url_for(f"{namespace}.download_chamado_arquivo", region_slug=region.slug, chamado_id=item["id"], kind="saida")
            if arquivo_saida
            else None
        )

    return jsonify({
        "items": page_items,
        "region": {"slug": region.slug, "label": region.label},
        "pagination": {
            "page": page,
            "pages": pages,
            "total": total_items,
            "has_prev": page > 1,
            "has_next": page < pages,
            "prev_num": page - 1,
            "next_num": page + 1
        }
    })


@support_bp.route("/chamados/concluidos")
@login_required
def chamados_concluidos():
    regions = list_regions()
    form = ChamadoFiltroForm(request.args)
    form.region.choices = [("__all__", "Todas as unidades")] + [(r.slug, r.label) for r in regions]
    
    return render_template(
        "admin/support/chamados_concluidos.html",
        form=form,
        regions=regions,
        api_endpoint=url_for("support_bp.chamados_api"),
        chamados_namespace=_current_chamados_namespace(),
    )


@support_bp.route("/chamados/<string:region_slug>/<int:chamado_id>/arquivo/<string:kind>")
@login_required
def download_chamado_arquivo(region_slug: str, chamado_id: int, kind: str):
    region = get_region(region_slug)
    if not region:
        abort(404)
    if kind not in {"entrada", "saida"}:
        abort(404)
    row = get_chamado(region, chamado_id)
    if not row:
        abort(404)
    stored = _resolve_chamado_file_ref(row, kind)
    path = resolve_support_file(stored)
    if not path:
        abort(404)
    try:
        return send_file(path, as_attachment=True, download_name=path.name)
    except Exception:
        current_app.logger.exception("Falha ao baixar anexo do chamado.")
        abort(404)


@support_bp.route("/atendimentos/concluidos")
@login_required
def atendimentos_concluidos():
    form = ConcluidoFilterForm(request.args)
    form.usuario_designado.choices = _technician_choices("Todos")
    return render_template(
        "admin/support/atendimentos_concluidos.html",
        form=form,
        api_endpoint=url_for("support_bp.atendimentos_api"),
    )


@support_bp.route("/atendimentos/concluidos/export")
@login_required
def exportar_concluidos():
    form = ConcluidoFilterForm(request.args)
    form.usuario_designado.choices = _technician_choices("Todos")
    entries = _fetch_concluded_entries(form)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Cliente", "Técnico", "Data atendimento", "OS", "Resumo"])
    for entry in entries:
        writer.writerow([
            entry.cliente,
            entry.assigned_user.nome_completo if entry.assigned_user else "",
            entry.data_atendimento.isoformat() if entry.data_atendimento else "",
            entry.os_entrada,
            (entry.resumo_atendimento or entry.descricao or ""),
        ])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="atendimentos_concluidos.csv",
    )


@support_bp.route("/chamados/criar", methods=["POST"])
@login_required
def criar_chamado():
    form = CriarChamadoForm()
    regions = []
    region = None
    region_slug = None
    payload = None

    try:
        regions = _set_region_choices(form)
        region_slug = form.region.data if form.region.data else None
        region = get_region(region_slug) if region_slug else None

        if region:
            _populate_chamado_form_choices(region, create_form=form)

        if not form.validate_on_submit():
            current_app.logger.warning("Falha na validação do formulário de chamado: %s", form.errors)
            flash("Não foi possível criar o chamado. Confira os campos obrigatórios.", "danger")
            return _safe_chamado_redirect(region_slug, regions)

        if not region:
            flash("Unidade inválida.", "danger")
            return _safe_chamado_redirect(region_slug, regions)

        ordem_servico = _append_unidade_suffix(form.ordem_servico.data, form.unidade.data)
        form.ordem_servico.data = ordem_servico

        if _ordem_servico_exists(region, ordem_servico):
            flash("A ordem de serviço já existe.", "danger")
            return _safe_chamado_redirect(region.slug, regions)

        payload = _build_chamado_payload(form)
        payload["ordem_servico"] = ordem_servico
        payload["retorno"] = "ABERTO"
        payload["criado_por"] = getattr(current_user, "nome_completo", None) or current_user.email

        # Cadastro auxiliar de empresa não pode derrubar a criação do chamado.
        # Como ensure_empresa_record antigo captura exceções internamente sem rollback,
        # isolamos esse passo em uma transação própria. Se algo falhar, limpamos a sessão
        # antes de tentar inserir o chamado.
        try:
            ensure_empresa_record(payload.get("cnpj"), payload.get("cliente"))
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("Falha auxiliar ao garantir cadastro da empresa do chamado.")
            _write_chamado_debug_log("ensure_empresa_record", exc, payload=payload)

        # Anexos também não podem derrubar o chamado por permissão/pasta.
        arquivo_entrada = None
        arquivo_saida = None
        try:
            arquivo_entrada = save_support_file(form.arquivo_entrada.data, ordem_servico, "entrada")
        except Exception as exc:
            current_app.logger.exception("Falha ao salvar anexo de entrada do chamado.")
            _write_chamado_debug_log("save_support_file entrada", exc, payload=payload)
        try:
            arquivo_saida = save_support_file(form.arquivo_saida.data, ordem_servico, "saida")
        except Exception as exc:
            current_app.logger.exception("Falha ao salvar anexo de saída do chamado.")
            _write_chamado_debug_log("save_support_file saida", exc, payload=payload)

        _set_chamado_file_payload(payload, entrada=arquivo_entrada, saida=arquivo_saida)

        chamado_id = create_chamado(region, payload)
        if not chamado_id:
            db.session.rollback()
            flash(
                "Não foi possível criar o chamado. O erro foi registrado em instance/chamados_debug_errors.log.",
                "danger",
            )
            return _safe_chamado_redirect(region.slug, regions)

        # Primeiro confirma o chamado no banco. Auditoria vem depois e não bloqueia o cadastro.
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("Falha ao confirmar criação do chamado.")
            _write_chamado_debug_log("commit criar_chamado", exc, payload=payload)
            flash(
                "Não foi possível confirmar o chamado no banco. Veja instance/chamados_debug_errors.log.",
                "danger",
            )
            return _safe_chamado_redirect(region.slug, regions)

        try:
            after_snapshot = _fetch_chamado_snapshot(region, chamado_id) or _snapshot_payload(region, payload, chamado_id)
            _log_chamado_audit("create", region, chamado_id=chamado_id, after=after_snapshot)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("Chamado criado, mas falhou ao registrar auditoria.")
            _write_chamado_debug_log("auditoria criar_chamado", exc, payload=payload)

        flash("Chamado criado com sucesso.", "success")
        return _safe_chamado_redirect(region.slug, regions)

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Erro inesperado ao criar chamado.")
        _write_chamado_debug_log(
            "erro inesperado criar_chamado",
            exc,
            payload=payload,
            form_errors=getattr(form, "errors", None),
        )
        flash(
            f"Erro interno ao criar chamado: {type(exc).__name__}. Veja instance/chamados_debug_errors.log.",
            "danger",
        )
        return _safe_chamado_redirect(region_slug, regions)


@support_bp.route("/chamados/<string:region_slug>/<int:chamado_id>/editar", methods=["POST"])
@login_required
def editar_chamado(region_slug: str, chamado_id: int):
    form = EditarChamadoForm()
    regions = _set_region_choices(form)
    region = get_region(region_slug) or get_region(form.region.data) if form.region.data else None
    if region:
        _populate_chamado_form_choices(region, edit_form=form)
    if not form.validate_on_submit():
        flash("Não foi possível atualizar o chamado.", "danger")
        return redirect(_redirect_chamados(region_slug, regions))

    if not region:
        flash("Unidade inválida.", "danger")
        return redirect(url_for("support_bp.chamados_dashboard"))

    before_snapshot = _fetch_chamado_snapshot(region, chamado_id)
    payload = _build_chamado_payload(form)
    arquivo_entrada = save_support_file(form.arquivo_entrada.data, form.ordem_servico.data, "entrada")
    arquivo_saida = save_support_file(form.arquivo_saida.data, form.ordem_servico.data, "saida")
    _set_chamado_file_payload(payload, entrada=arquivo_entrada, saida=arquivo_saida)
    update_chamado(region, chamado_id, payload)
    after_snapshot = _fetch_chamado_snapshot(region, chamado_id) or _snapshot_payload(region, payload, chamado_id)
    _log_chamado_audit("update", region, chamado_id=chamado_id, before=before_snapshot, after=after_snapshot)
    db.session.commit()
    flash("Chamado atualizado.", "success")
    return redirect(_redirect_chamados(region.slug, regions))


@support_bp.route("/chamados/<string:region_slug>/<int:chamado_id>/fechar", methods=["POST"])
@login_required
def fechar_chamado(region_slug: str, chamado_id: int):
    region = get_region(region_slug)
    if not region:
        flash("Unidade inválida.", "danger")
        return redirect(url_for("support_bp.chamados_dashboard"))

    form = FecharChamadoForm()
    _populate_chamado_form_choices(region, close_form=form)
    if not form.validate_on_submit():
        current_app.logger.warning("Erro de validação ao fechar chamado %s: %s", chamado_id, form.errors)
        for field, errors in form.errors.items():
            for error in errors:
                field_label = getattr(form, field).label.text
                flash(f"Campo '{field_label}': {error}", "danger")
        flash("Não foi possível fechar o chamado. Verifique os campos obrigatórios.", "danger")
        return redirect(_redirect_chamados(region_slug))

    before_snapshot = _fetch_chamado_snapshot(region, chamado_id)
    payload = _build_chamado_close_payload(form)
    os_code = (
        (before_snapshot or {}).get("ordem_servico")
        or str(chamado_id)
    )
    arquivo_saida = save_support_file(form.arquivo_saida.data, os_code, "saida")
    _set_chamado_file_payload(payload, saida=arquivo_saida)
    res = update_chamado(region, chamado_id, payload)
    if res is None:
        flash("Erro ao salvar informações de encerramento no banco de dados.", "danger")
        return redirect(_redirect_chamados(region_slug))
    after_snapshot = _fetch_chamado_snapshot(region, chamado_id)
    pesquisa_id = _insert_pesquisa_satisfacao(
        ordem_servico=(after_snapshot or {}).get("ordem_servico") or (before_snapshot or {}).get("ordem_servico"),
        tecnico=payload.get("tecnico") or (after_snapshot or {}).get("tecnico"),
        cliente=(after_snapshot or {}).get("cliente") or (before_snapshot or {}).get("cliente"),
    )
    numero_proposta = (after_snapshot or {}).get("numero_proposta") or (before_snapshot or {}).get("numero_proposta")
    usuario_label = getattr(current_user, "nome_completo", None) or current_user.email
    _update_novos_contratos_on_close(numero_proposta=numero_proposta, usuario=usuario_label)
    if payload.get("retorno") == "FECHADO" and pesquisa_id:
        email = (after_snapshot or {}).get("email_responsavel") or (before_snapshot or {}).get("email_responsavel")
        link_base = current_app.config.get("SATISFACAO_URL_BASE")
        if email and link_base:
            try:
                link = link_base.format(id=pesquisa_id)
            except Exception:
                link = link_base.replace("{id}", str(pesquisa_id))
            send_chamado_satisfacao_email(
                email=email,
                cliente=(after_snapshot or {}).get("cliente"),
                data_atendimento=(after_snapshot or {}).get("data"),
                hora_entrada=(after_snapshot or {}).get("hora_entrada"),
                hora_saida=(after_snapshot or {}).get("hora_saida"),
                tecnico=(after_snapshot or {}).get("tecnico"),
                quem_atendeu=(after_snapshot or {}).get("quem_atendeu"),
                descricao=(after_snapshot or {}).get("descricao"),
                link=link,
            )
    _log_chamado_audit("close", region, chamado_id=chamado_id, before=before_snapshot, after=after_snapshot)
    db.session.commit()
    flash("Chamado fechado com sucesso.", "success")
    return redirect(_redirect_chamados(region.slug))


@support_bp.route("/chamados/<string:region_slug>/<int:chamado_id>/excluir", methods=["POST"])
@login_required
def excluir_chamado(region_slug: str, chamado_id: int):
    region = get_region(region_slug)
    if not region:
        flash("Unidade inválida.", "danger")
        return redirect(url_for("support_bp.chamados_dashboard"))

    before_snapshot = _fetch_chamado_snapshot(region, chamado_id)
    delete_chamado(region, chamado_id)
    _log_chamado_audit("delete", region, chamado_id=chamado_id, before=before_snapshot)
    db.session.commit()
    flash("Chamado excluído.", "success")
    return redirect(_redirect_chamados(region.slug))


@support_bp.route("/chamados/export")
@login_required
def exportar_chamados():
    form = ChamadoFiltroForm(request.args)
    _set_region_choices(form)
    region = get_region(form.region.data) if form.region.data else list_regions()[0]
    if not region:
        abort(404)

    status_group = request.args.get("status_group", "")
    status_val = form.status.data or request.args.get("status") or None
    if not status_val and status_group:
        if status_group == "open":
            status_val = ["ABERTO", "OFICINA"]
        elif status_group == "closed":
            status_val = ["FECHADO"]

    chamados = fetch_chamados(
        region,
        data=form.data_visita.data.isoformat() if form.data_visita.data else None,
        tecnico=form.tecnico.data or None,
        status=status_val,
        ordem_servico=form.ordem_servico.data or None,
        limit=0,
    )

    output = io.StringIO()
    fieldnames = chamados[0].keys() if chamados else ["mensagem"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    if chamados:
        for item in chamados:
            writer.writerow({k: _format_csv_value(v) for k, v in item.items()})
    else:
        writer.writerow({"mensagem": "Sem registros"})

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"chamados_{region.slug}.csv",
    )


@support_bp.route("/chamados/export_pdf")
@login_required
def exportar_chamados_pdf():
    form = ChamadoFiltroForm(request.args)
    _set_region_choices(form)
    region = get_region(form.region.data) if form.region.data else list_regions()[0]
    if not region:
        abort(404)

    status_group = request.args.get("status_group", "")
    status_val = form.status.data or request.args.get("status") or None
    if not status_val and status_group:
        if status_group == "open":
            status_val = ["ABERTO", "OFICINA"]
        elif status_group == "closed":
            status_val = ["FECHADO"]

    closed = (form.status.data == "FECHADO" or status_group == "closed")
    chamados = fetch_chamados(
        region,
        data=form.data_visita.data.isoformat() if form.data_visita.data else None,
        tecnico=form.tecnico.data or None,
        status=status_val,
        ordem_servico=form.ordem_servico.data or None,
        limit=0,
        order_by_closed=closed,
    )

    decorated = _decorate_chamados(chamados, closed=closed)

    from modules.propostas.gerar_proposta import render_proposta_html_pdf

    context = {
        "chamados": decorated,
        "region": region,
        "filters": {
            "search": form.ordem_servico.data or "",
            "tecnico": form.tecnico.data or "",
            "status": form.status.data or "",
            "status_group": status_group,
            "data_visita": form.data_visita.data.strftime("%d/%m/%Y") if form.data_visita.data else ""
        },
        "now": datetime.now()
    }

    try:
        pdf_bytes = render_proposta_html_pdf("admin/support/chamados_pdf.html", context)
    except Exception as e:
        current_app.logger.exception("Falha ao gerar o PDF de chamados")
        abort(500, description="Erro ao gerar PDF.")

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"chamados_{region.slug}.pdf",
    )


@support_bp.route("/atendimentos/criar", methods=["POST"])
@login_required
def criar_atendimento():
    form = NovoAtendimentoForm()
    form.usuario_designado.choices = _technician_choices("Selecione")
    try:
        tipo_choices = _distinct_tipo_choices()
        sistema_choices = _distinct_sistema_choices()
        form.tipo_atendimento.choices = tipo_choices
        form.sistema.choices = sistema_choices
    except Exception:
        current_app.logger.exception("Falha ao carregar choices para tipo/sistema")

    if not form.validate_on_submit():
        flash("Não foi possível criar o atendimento. Verifique os campos obrigatórios.", "danger")
        return redirect(_redirect_back())

    meet_start = form.meet_start.data
    meet_session_key = (form.meet_session_key.data or "").strip() or None
    meet_link = None
    meet_event_id = None
    meet_start_resolved = meet_start
    is_collective = _is_collective_training(form.tipo_atendimento.data)
    send_meet_email = False
    google_invite_sent = False

    pre_meet_link = (form.meet_link.data or "").strip()
    pre_meet_event_id = (form.meet_event_id.data or "").strip()
    if pre_meet_link and pre_meet_event_id:
        cached = _get_precreated_meet(pre_meet_event_id, pre_meet_link)
        if cached:
            meet_link = pre_meet_link
            meet_event_id = pre_meet_event_id
            cached_start = cached.get("start") if isinstance(cached, dict) else None
            if cached_start:
                meet_start_resolved = _parse_os_datetime(cached_start) or meet_start

    attendees = _split_emails(form.email.data, form.meet_extra_emails.data)
    if meet_link and meet_event_id and not is_collective and attendees:
        try:
            google_invite_sent = update_meet_event(
                event_id=meet_event_id,
                attendees=attendees,
                send_updates=True,
            )
            if not google_invite_sent:
                send_meet_email = True
        except Exception:
            current_app.logger.exception("Falha ao atualizar convidados do Meet.")
            send_meet_email = True
    if is_collective and meet_link and attendees:
        send_meet_email = True
    if not meet_link and is_collective and meet_session_key:
        existing = (
            AtendimentoSuporte.query.filter(
                AtendimentoSuporte.meet_session_key == meet_session_key,
                AtendimentoSuporte.meet_link.isnot(None),
            )
            .order_by(AtendimentoSuporte.id.desc())
            .first()
        )
        if existing:
            meet_link = existing.meet_link
            meet_event_id = existing.meet_event_id
            meet_start_resolved = existing.meet_start or meet_start
            if attendees:
                send_meet_email = True
        elif meet_start:
            try:
                meet_link, meet_event_id = _create_support_meet(
                    cliente=form.cliente.data.strip(),
                    tipo_atendimento=form.tipo_atendimento.data,
                    os_entrada=form.os_entrada.data,
                    criado_por=getattr(current_user, "nome_completo", None) or current_user.email,
                    start_dt=meet_start,
                    attendees=[],
                    send_updates=False,
                )
                if meet_link and attendees:
                    send_meet_email = True
            except Exception:
                current_app.logger.exception("Falha ao criar link do Meet para treinamento coletivo.")
                flash("Não foi possível gerar o link do Meet.", "warning")
    elif not meet_link and meet_start:
        try:
            meet_link, meet_event_id = _create_support_meet(
                cliente=form.cliente.data.strip(),
                tipo_atendimento=form.tipo_atendimento.data,
                os_entrada=form.os_entrada.data,
                criado_por=getattr(current_user, "nome_completo", None) or current_user.email,
                start_dt=meet_start,
                attendees=attendees if not is_collective else [],
                send_updates=not is_collective,
            )
            if meet_link and attendees:
                if is_collective:
                    send_meet_email = True
                else:
                    google_invite_sent = True
        except Exception:
            current_app.logger.exception("Falha ao criar link do Meet para atendimento.")
            flash("Não foi possível gerar o link do Meet.", "warning")

    entry = AtendimentoSuporte(
        cliente=form.cliente.data.strip(),
        cnpj=normalize_cnpj(form.cnpj.data),
        data_entrada=form.data_entrada.data,
        tipo_atendimento=form.tipo_atendimento.data.strip(),
        status=form.status.data,
        descricao=form.descricao.data,
        observacoes=form.observacoes.data,
        observacoes_alerta=form.observacoes_alerta.data,
        os_entrada=form.os_entrada.data.strip(),
        sistema=form.sistema.data,
        quantidade_pessoas=form.quantidade_pessoas.data,
        texto_mobile=form.texto_mobile.data,
        email=form.email.data,
        usuario_designado=form.usuario_designado.data or None,
        criado_por=getattr(current_user, "nome_completo", None) or current_user.email,
        meet_link=meet_link,
        meet_event_id=meet_event_id,
        meet_session_key=meet_session_key,
        meet_start=meet_start_resolved,
    )
    if entry.usuario_designado:
        _touch_last_assignment(entry.usuario_designado)
    if form.arquivo_entrada.data:
        entry.arq_entrada = save_support_file(form.arquivo_entrada.data, entry.os_entrada, "entrada")
    if entry.cnpj:
        try:
            receita_data = fetch_receita_data(entry.cnpj)
            upsert_empresa_from_receita(entry.cnpj, receita_data)
        except ReceitaAPIError as exc:
            db.session.rollback()
            flash(f"Aviso da ReceitaWS: {exc}", "warning")
        except Exception as exc:
            db.session.rollback()
            current_app.logger.warning("Falha ao consultar ReceitaWS: %s", exc)
    db.session.add(entry)
    db.session.commit()
    meet_email_sent = None
    if send_meet_email and meet_link and attendees:
        meet_email_sent = send_atendimento_meet_email(entry, attendees)
    flash("Atendimento criado com sucesso.", "success")
    if meet_link and attendees:
        if google_invite_sent:
            flash("Convite do Meet enviado pelo Google Calendar.", "info")
        elif send_meet_email:
            if meet_email_sent:
                flash("Convite do Meet enviado por e-mail.", "info")
            else:
                flash("Não foi possível enviar o e-mail do Meet. Verifique as configuracoes de email.", "warning")
        else:
            flash("Link do Meet gerado, mas nenhum envio foi registrado.", "warning")
    elif meet_link and not attendees:
        flash("Link do Meet gerado, mas nenhum e-mail foi informado.", "warning")
    return redirect(_redirect_back(status=form.status.data.lower()))


@support_bp.route("/atendimentos/<int:atendimento_id>/editar", methods=["POST"])
@login_required
def editar_atendimento(atendimento_id: int):
    entry = AtendimentoSuporte.query.get_or_404(atendimento_id)
    form = EditarAtendimentoForm()
    form.usuario_designado.choices = _technician_choices()
    try:
        tipo_choices = _distinct_tipo_choices()
        sistema_choices = _distinct_sistema_choices()
        form.tipo_atendimento.choices = tipo_choices
        form.sistema.choices = sistema_choices
    except Exception:
        current_app.logger.exception("Falha ao carregar choices para tipo/sistema")
        # Fallback: garante que o valor atual do registro seja aceito pelo form
        tipo_val = entry.tipo_atendimento or ""
        form.tipo_atendimento.choices = [(tipo_val, tipo_val)] if tipo_val else [("", "")]
        sistema_val = entry.sistema or ""
        form.sistema.choices = [(sistema_val, sistema_val)] if sistema_val else [("", "")]

    try:
        form_entry_id = int(form.atendimento_id.data or 0)
    except (ValueError, TypeError):
        form_entry_id = -1

    if not form.validate_on_submit() or form_entry_id != entry.id:
        current_app.logger.warning("FORM VALIDATION FAILED: errors=%s, form_id=%s, entry_id=%s", form.errors, form.atendimento_id.data, entry.id)
        flash("Não foi possível atualizar o atendimento.", "danger")
        return redirect(_redirect_back())

    before = entry.to_dict()
    if form.cliente.data:
        entry.cliente = form.cliente.data.strip()
    if form.cnpj.data is not None:
        entry.cnpj = normalize_cnpj(form.cnpj.data)
    if form.tipo_atendimento.data:
        entry.tipo_atendimento = form.tipo_atendimento.data.strip()
    if form.status.data:
        entry.status = form.status.data
    entry.descricao = form.descricao.data if form.descricao.data is not None else entry.descricao
    entry.resumo_atendimento = form.resumo_atendimento.data if form.resumo_atendimento.data is not None else entry.resumo_atendimento
    if form.os_entrada.data:
        entry.os_entrada = form.os_entrada.data.strip()
    if form.os_saida.data:
        entry.os_saida = form.os_saida.data.strip()
    if form.data_entrada.data:
        entry.data_entrada = form.data_entrada.data
    if form.data_atendimento.data:
        entry.data_atendimento = form.data_atendimento.data
    entry.usuario_designado = form.usuario_designado.data or None
    entry.observacoes = form.observacoes.data
    entry.observacoes_alerta = form.observacoes_alerta.data
    entry.sistema = form.sistema.data
    entry.quantidade_pessoas = form.quantidade_pessoas.data
    entry.texto_mobile = form.texto_mobile.data
    entry.email = form.email.data

    if form.arquivo_entrada.data:
        delete_support_file(entry.arq_entrada)
        entry.arq_entrada = save_support_file(form.arquivo_entrada.data, entry.os_entrada, "entrada")
    if form.arquivo_saida.data:
        delete_support_file(entry.arq_saida)
        entry.arq_saida = save_support_file(form.arquivo_saida.data, entry.os_entrada or entry.os_saida or entry.cliente, "saida")

    after = entry.to_dict()
    log_changes(entry.id, before, after, ("status", "usuario_designado", "descricao", "resumo_atendimento", "os_entrada", "os_saida", "data_entrada", "data_atendimento", "observacoes", "observacoes_alerta", "sistema", "quantidade_pessoas", "texto_mobile", "email", "criado_por"))
    db.session.commit()

    if entry.usuario_designado and entry.usuario_designado != before.get("usuario_designado"):
        _touch_last_assignment(entry.usuario_designado)
    if entry.status == "Concluido" and before.get("status") != "Concluido":
        send_atendimento_concluido_email(entry)

    flash("Atendimento atualizado.", "success")
    return redirect(_redirect_back(status=form.status.data.lower()))


@support_bp.route("/atendimentos/<int:atendimento_id>/assumir", methods=["POST"])
@login_required
def assumir_atendimento(atendimento_id: int):
    entry = AtendimentoSuporte.query.get_or_404(atendimento_id)
    entry.usuario_designado = current_user.id
    db.session.commit()
    _touch_last_assignment(entry.usuario_designado)
    flash("Atendimento atribuído a você.", "success")
    return redirect(_redirect_back())


@support_bp.route("/atendimentos/designar", methods=["POST"])
@login_required
def designar_tecnico():
    atendimento_id = request.form.get("atendimento_id", type=int)
    if not atendimento_id:
        flash("Atendimento não encontrado.", "warning")
        return redirect(_redirect_back())
    entry = AtendimentoSuporte.query.get_or_404(atendimento_id)
    raw_value = request.form.get("usuario_designado")
    new_value = int(raw_value) if raw_value not in (None, "") else 0
    entry.usuario_designado = new_value or None
    db.session.commit()
    _touch_last_assignment(entry.usuario_designado)
    flash("Técnico designado com sucesso.", "success")
    return redirect(_redirect_back(request.form.get("status") or entry.status))


@support_bp.route("/atendimentos/<int:atendimento_id>/excluir", methods=["POST"])
@login_required
def excluir_atendimento(atendimento_id: int):
    entry = AtendimentoSuporte.query.get_or_404(atendimento_id)
    AtendimentoSuporteLog.query.filter_by(atendimento_suporte_id=entry.id).delete(synchronize_session=False)
    delete_support_file(entry.arq_entrada)
    delete_support_file(entry.arq_saida)
    db.session.delete(entry)
    db.session.commit()
    flash("Atendimento excluído.", "success")
    return redirect(_redirect_back())


@support_bp.route("/atendimentos/<int:atendimento_id>/json")
@login_required
def atendimento_json(atendimento_id: int):
    entry = AtendimentoSuporte.query.get_or_404(atendimento_id)
    payload = entry.to_dict()
    if entry.assigned_user:
        payload["assigned_user"] = {"id": entry.assigned_user.id, "nome": entry.assigned_user.nome_completo}
    return jsonify(payload)


@support_bp.route("/atendimentos/<int:atendimento_id>/logs")
@login_required
def atendimento_logs(atendimento_id: int):
    logs = AtendimentoSuporteLog.query.filter_by(atendimento_suporte_id=atendimento_id).order_by(AtendimentoSuporteLog.created_at.desc()).all()
    return jsonify([{ "campo": log.campo, "valor_antigo": log.valor_antigo, "valor_novo": log.valor_novo, "modificado_por": log.modificado_por, "created_at": log.created_at.isoformat() if log.created_at else None } for log in logs])


@support_bp.route("/atendimentos/<int:atendimento_id>/arquivo/<string:kind>")
@login_required
def download_arquivo(atendimento_id: int, kind: str):
    entry = AtendimentoSuporte.query.get_or_404(atendimento_id)
    stored = entry.arq_entrada if kind == "entrada" else entry.arq_saida
    path = resolve_support_file(stored)
    if not path: abort(404)
    return send_file(path, as_attachment=True, download_name=path.name)


@support_bp.route("/api/cnpj")
@login_required
def api_cnpj():
    cnpj = request.args.get("cnpj", "")
    try:
        data = fetch_receita_data(cnpj)
        empresa = upsert_empresa_from_receita(cnpj, data)
        db.session.commit()
        response = {"cliente": empresa.cliente, "cnpj": empresa.cnpj, "observacoes": empresa.observacoes, "observacoes_alerta": empresa.observacoes_alerta, "email": data.get("email")}
    except ReceitaAPIError as exc:
        db.session.rollback()
        response = {"error": str(exc)}
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Erro ao buscar dados do CNPJ: %s", exc)
        response = {"error": "Erro interno ao consultar CNPJ"}
    return jsonify(response)


def _redirect_back(status: str | None = None) -> str:
    target_status = status or request.args.get("status") or request.form.get("status") or "entrada"
    return url_for("support_bp.atendimentos_dashboard", status=target_status)


def _is_support_user(user: User) -> bool:
    if not user or not user.is_active:
        return False
    primary_dept = getattr(user, "department", None)
    if primary_dept and _normalize_dept_name(getattr(primary_dept, "name", "")) == "SUPORTE":
        return True
    for dept in getattr(user, "departments", []) or []:
        if _normalize_dept_name(getattr(dept, "name", "")) == "SUPORTE":
            return True
    return False


def _load_technicians():
    query = User.query.filter(User.is_active.is_(True)).options(
        joinedload(User.department), joinedload(User.departments)
    )
    users = query.order_by(User.nome_completo.asc(), User.email.asc()).all()
    return [user for user in users if _is_support_user(user)]


def _technician_choices(default_label: str = "Não atribuído", technicians: List[User] | None = None):
    techs = technicians if technicians is not None else _load_technicians()
    return [(0, default_label)] + [(tech.id, tech.nome_completo or tech.email) for tech in techs]


def _distinct_tipo_choices(default_label: str = ""):
    rows = db.session.query(AtendimentoSuporte.tipo_atendimento).filter(AtendimentoSuporte.tipo_atendimento.isnot(None)).filter(AtendimentoSuporte.tipo_atendimento != "").distinct().order_by(AtendimentoSuporte.tipo_atendimento.asc()).all()
    choices = [("", default_label or "")] if default_label is not None else []
    choices.extend([(r[0], r[0]) for r in rows if r[0]])
    return choices


def _distinct_sistema_choices(default_label: str = ""):
    rows = db.session.query(AtendimentoSuporte.sistema).filter(AtendimentoSuporte.sistema.isnot(None)).filter(AtendimentoSuporte.sistema != "").distinct().order_by(AtendimentoSuporte.sistema.asc()).all()
    choices = [("", default_label or "")] if default_label is not None else []
    # Add IDSecure to the list
    if ("IDSecure", "IDSecure") not in choices:
        choices.append(("IDSecure", "IDSecure"))
    choices.extend([(r[0], r[0]) for r in rows if r[0] and r[0] != "IDSecure"])
    return choices


_ENUM_VALUE_RE = re.compile(r"'([^']*)'")
_CHAMADO_TIPO_FALLBACK = [
    ("ENTREGA", "ENTREGA"),
    ("INSTALACAO", "INSTALACAO"),
    ("CHAMADO", "CHAMADO"),
    ("MANUNTENCAO", "MANUNTENCAO"),
]
_CHAMADO_CONTRATO_FALLBACK = [
    ("SIM", "SIM"),
    ("NAO", "NAO"),
]


def _enum_choices_for(table_name: str, column_name: str) -> list[tuple[str, str]]:
    try:
        result = db.session.execute(
            text(f"SHOW COLUMNS FROM {table_name} LIKE :column"),
            {"column": column_name},
        ).first()
    except Exception:
        db.session.rollback()
        return []
    if not result:
        return []
    mapping = getattr(result, "_mapping", None)
    type_value = mapping.get("Type") if mapping else (result[1] if len(result) > 1 else None)
    if not type_value or "enum" not in str(type_value).lower():
        return []
    values = [item for item in _ENUM_VALUE_RE.findall(str(type_value)) if item]
    return [(value, value) for value in values]


def _is_chamados_technician(user: User) -> bool:
    if not user or not user.is_active:
        return False
    role_key = (getattr(user, "tipo", None) or "").strip().lower()
    if role_key in {"tecnico", "técnico", "oficina"}:
        return True
    dept_names = getattr(user, "department_names", []) or []
    for dept_name in dept_names:
        normalized = _normalize_dept_name(dept_name)
        if normalized in {"OFICINA", "TECNICO", "TÉCNICO"}:
            return True
    return False


def _chamado_technician_choices(default_label: str = "Selecione") -> list[tuple[str, str]]:
    users = (
        User.query.filter(User.is_active.is_(True))
        .order_by(User.nome_completo.asc(), User.email.asc())
        .all()
    )
    choices: list[tuple[str, str]] = [("", default_label)]
    for user in users:
        if not _is_chamados_technician(user):
            continue
        label = user.nome_completo or user.email
        if not label:
            continue
        choices.append((label, label))
    return choices


def _distinct_chamado_choices(region, column_name: str, default_label: str = "Selecione", for_filter: bool = False) -> list[tuple[str, str]]:
    if not region:
        return [("", default_label)]
    try:
        rows = db.session.execute(
            text(
                f"SELECT DISTINCT {column_name} "
                f"FROM {region.table_name} "
                f"WHERE {column_name} IS NOT NULL AND {column_name} != '' "
                f"ORDER BY {column_name} ASC"
            )
        ).fetchall()
    except Exception:
        db.session.rollback()
        current_app.logger.exception(f"Falha ao carregar choices para {column_name} na tabela {region.table_name if region else 'None'}")
        return [("", default_label)]

    raw_names = [row[0] for row in rows if row[0]]
    if not raw_names:
        return [("", default_label)]

    # Dynamic deduplication: group by overlaps (e.g. 'Rodolfo' inside 'RODOLFO DANTAS')
    sorted_raw = sorted(list(set(raw_names)), key=len, reverse=True)
    mapping = {}
    used = set()

    for name in sorted_raw:
        if name in used: continue
        variants = [name]
        used.add(name)
        for other in sorted_raw:
            if other in used: continue
            if other.lower() in name.lower() or name.lower() in other.lower():
                variants.append(other)
                used.add(other)
        mapping[name] = variants

    choices = [("", default_label)]
    for canonical in sorted(mapping.keys()):
        variants = mapping[canonical]
        # For filters, we want to include all variants in the 'IN' clause
        # For forms (create/edit), we use the canonical name to standardize
        value = "|".join(variants) if for_filter else canonical
        choices.append((value, canonical))

    return choices


def _ensure_default_choice(choices: list[tuple[str, str]], default_label: str) -> list[tuple[str, str]]:
    if not choices:
        return [("", default_label)]
    if choices[0][0] == "":
        return choices
    return [("", default_label)] + choices


def _populate_chamado_form_choices(
    region,
    *,
    create_form: CriarChamadoForm | None = None,
    edit_form: EditarChamadoForm | None = None,
    close_form: FecharChamadoForm | None = None,
) -> None:
    if not region:
        return
    tipo_choices = _enum_choices_for(region.table_name, "tipo_atendimento")
    if not tipo_choices:
        tipo_choices = _distinct_chamado_choices(region, "tipo_atendimento")
    if not tipo_choices or len(tipo_choices) <= 1:
        tipo_choices = _CHAMADO_TIPO_FALLBACK
    tipo_choices = _ensure_default_choice(tipo_choices, "Selecione")

    contrato_choices = _enum_choices_for(region.table_name, "contrato") or _CHAMADO_CONTRATO_FALLBACK
    contrato_choices = _ensure_default_choice(contrato_choices, "Selecione")
    if create_form:
        create_form.tipo_atendimento.choices = tipo_choices
        create_form.contrato.choices = contrato_choices
        create_form.tecnico.choices = _chamado_technician_choices("Selecione")
    if edit_form:
        edit_form.tipo_atendimento.choices = tipo_choices
        edit_form.tecnico.choices = _chamado_technician_choices("Selecione")
    if close_form:
        close_form.tecnico.choices = _chamado_technician_choices("Selecione")


def _set_region_choices(form):
    regions = list_regions()
    form.region.choices = [(region.slug, region.label) for region in regions]
    return regions


def _normalize_os_created(value):
    if not value: return None
    if isinstance(value, datetime): return value
    if isinstance(value, date): return datetime.combine(value, datetime.now().time().replace(microsecond=0))
    return _parse_os_datetime(value)


def _append_unidade_suffix(ordem_servico: str, unidade: str | None) -> str:
    os_value = str(ordem_servico or "").strip()
    unidade_value = str(unidade or "").strip()
    if not os_value or not unidade_value:
        return os_value
    if os_value.endswith(f" {unidade_value}") or os_value.endswith(unidade_value):
        return os_value
    return f"{os_value} {unidade_value}".strip()


def _ordem_servico_exists(region, ordem_servico: str, *, exclude_id: int | None = None) -> bool:
    if not region or not ordem_servico:
        return False
    try:
        row = db.session.execute(
            text(f"SELECT id FROM {region.table_name} WHERE ordem_servico = :os LIMIT 1"),
            {"os": ordem_servico},
        ).first()
    except Exception:
        db.session.rollback()
        return False
    if not row:
        return False
    try:
        found_id = row[0]
    except Exception:
        found_id = None
    return found_id != exclude_id


def _safe_chamado_redirect(region_slug: str | None = None, regions=None):
    try:
        return redirect(_redirect_chamados(region_slug, regions))
    except Exception:
        current_app.logger.exception("Falha ao redirecionar chamados.")
        try:
            return redirect(url_for("tech_bp.chamados_dashboard"))
        except Exception:
            return redirect("/admin/tecnica/chamados")


def _write_chamado_debug_log(context: str, exc: Exception, *, payload=None, form_errors=None) -> None:
    """Grava erro em arquivo porque em alguns servidores o console/journal não mostra o traceback."""
    try:
        Path(current_app.instance_path).mkdir(parents=True, exist_ok=True)
        path = Path(current_app.instance_path) / "chamados_debug_errors.log"
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n" + "=" * 80 + "\n")
            fh.write(f"{datetime.now().isoformat()} - {context}\n")
            fh.write(f"Erro: {type(exc).__name__}: {exc}\n")
            if payload is not None:
                fh.write(f"Payload: {payload}\n")
            if form_errors is not None:
                fh.write(f"Form errors: {form_errors}\n")
            fh.write(traceback.format_exc())
            fh.write("\n")
    except Exception:
        current_app.logger.exception("Falha ao gravar chamados_debug_errors.log")




def _insert_pesquisa_satisfacao(
    *,
    ordem_servico: str | None,
    tecnico: str | None,
    cliente: str | None,
) -> int | None:
    if not ordem_servico:
        return None
    try:
        inspector = inspect(db.engine)
        if not inspector.has_table("pesquisa_satisfacao"):
            return None
    except Exception:
        db.session.rollback()
        return None
    try:
        existing = db.session.execute(
            text("SELECT id FROM pesquisa_satisfacao WHERE ordem_servico = :os LIMIT 1"),
            {"os": ordem_servico},
        ).first()
        if existing:
            return int(existing[0]) if existing[0] is not None else None
    except Exception:
        db.session.rollback()
        return None

    sigla_os = (str(ordem_servico or "").strip()[-1:] if ordem_servico else "").upper()
    unidade_map = {
        "T": "TECHNO SOLLUS RJ",
        "S": "SOLLUS RJ",
    }
    unidade = unidade_map.get(sigla_os, "Desconhecido")

    try:
        result = db.session.execute(
            text(
                "INSERT INTO pesquisa_satisfacao "
                "(ordem_servico, nome_usuario, sigla_os, cliente, unidade, status) "
                "VALUES (:ordem_servico, :nome_usuario, :sigla_os, :cliente, :unidade, 'enviada')"
            ),
            {
                "ordem_servico": ordem_servico,
                "nome_usuario": tecnico or "",
                "sigla_os": sigla_os,
                "cliente": cliente or "",
                "unidade": unidade,
            },
        )
        db.session.commit()
        inserted_id = getattr(result, "lastrowid", None)
        if inserted_id:
            return int(inserted_id)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Falha ao inserir pesquisa de satisfação.")
        return None

    try:
        fallback = db.session.execute(
            text(
                "SELECT id FROM pesquisa_satisfacao WHERE ordem_servico = :os "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"os": ordem_servico},
        ).first()
        return int(fallback[0]) if fallback else None
    except Exception:
        db.session.rollback()
        return None


def _update_novos_contratos_on_close(
    *,
    numero_proposta: str | None,
    usuario: str,
) -> None:
    if not numero_proposta:
        return
    try:
        inspector = inspect(db.engine)
        if not inspector.has_table("novos_contratos"):
            return
    except Exception:
        db.session.rollback()
        return
    try:
        db.session.execute(
            text(
                "UPDATE novos_contratos "
                "SET conclusao = 1, data_conclusao = :data, solicitado_conclusao = :usuario "
                "WHERE proposta_contrato = :numero_proposta"
            ),
            {
                "data": datetime.now(),
                "usuario": usuario,
                "numero_proposta": numero_proposta,
            },
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Falha ao atualizar novos_contratos.")


def _form_field_data(form, field_name: str, default=None):
    """Retorna o .data de um campo WTForms de forma segura.

    Importante: WTForms já possui a propriedade form.data, que é um dict com
    todos os campos do formulário. Por isso, um campo chamado "data" não pode
    ser lido com form.data.data. Quando o campo tiver esse nome, ele precisa
    ser acessado por form._fields["data"].data.
    """
    fields = getattr(form, "_fields", {}) or {}
    field = fields.get(field_name)
    if field is None:
        return default
    return field.data


def _clean_form_text_value(value, *, default=None):
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        return value or default
    return value


def _build_chamado_payload(form):
    payload = {
        "cliente": _clean_form_text_value(_form_field_data(form, "cliente"), default=""),
        "bairro": _clean_form_text_value(_form_field_data(form, "bairro")),
        "ordem_servico": _clean_form_text_value(_form_field_data(form, "ordem_servico"), default=""),
        "tipo_atendimento": _clean_form_text_value(_form_field_data(form, "tipo_atendimento")),
        "cnpj": _clean_form_text_value(_form_field_data(form, "cnpj")),
        "email_responsavel": _clean_form_text_value(_form_field_data(form, "email_responsavel")),
    }

    data_value = _form_field_data(form, "data")
    if data_value is not None:
        payload["data"] = data_value

    data_os_criada = _form_field_data(form, "data_os_criada")
    if data_os_criada is not None:
        payload["data_os_criada"] = _normalize_os_created(data_os_criada) or datetime.now()

    tecnico = _clean_form_text_value(_form_field_data(form, "tecnico"))
    if tecnico is not None:
        payload["tecnico"] = tecnico

    contrato = _clean_form_text_value(_form_field_data(form, "contrato"))
    if contrato is not None:
        payload["contrato"] = contrato

    cep = _clean_form_text_value(_form_field_data(form, "cep"))
    if cep is not None:
        payload["cep"] = cep

    numero_proposta = _clean_form_text_value(_form_field_data(form, "numero_proposta"))
    if numero_proposta is not None:
        payload["numero_proposta"] = numero_proposta

    numero_manutencao = _clean_form_text_value(_form_field_data(form, "numero_manutencao"))
    if numero_manutencao is not None:
        payload["numero_manutencao"] = numero_manutencao

    novo_cliente = _clean_form_text_value(_form_field_data(form, "novo_cliente"))
    if novo_cliente is not None:
        payload["novo_cliente"] = novo_cliente

    return payload


def _set_chamado_file_payload(payload: Dict[str, Any], *, entrada: str | None = None, saida: str | None = None) -> None:
    if entrada:
        payload["arquivo_entrada"] = entrada
        payload["arq_entrada"] = entrada
    if saida:
        payload["arquivo_saida"] = saida
        payload["arq_saida"] = saida


def _normalize_chamado_time(value: str | None) -> str | None:
    if not value:
        return None
    parsed = _parse_os_datetime(value)
    if parsed:
        return parsed.strftime("%H:%M:%S")
    return value


def _build_chamado_close_payload(form: FecharChamadoForm):
    data_atendimento = form.data_atendimento.data
    hora_entrada = _normalize_chamado_time(form.hora_entrada.data)
    hora_saida = _normalize_chamado_time(form.hora_saida.data)
    data_field = None
    if data_atendimento:
        data_field = _parse_os_datetime(hora_entrada, date_hint=data_atendimento) or data_atendimento

    payload = {
        "data": data_field,
        "hora_entrada": hora_entrada,
        "hora_saida": hora_saida,
        "retorno": (form.retorno.data or "FECHADO").strip(),
        "quem_atendeu": (form.quem_atendeu.data or "").strip() or None,
        "descricao": form.descricao.data,
        "tecnico": (form.tecnico.data or "").strip() or None,
        "email_responsavel": (form.email_responsavel.data or "").strip() or None,
    }
    return payload


def _redirect_chamados(region_slug: str | None = None, regions=None) -> str:
    slug = region_slug or (regions[0].slug if regions else None)
    namespace = _current_chamados_namespace()
    return url_for(f"{namespace}.chamados_dashboard", region=slug) if slug else url_for(f"{namespace}.chamados_dashboard")


def _snapshot_payload(region, payload, chamado_id=None):
    snapshot = dict(payload) if not isinstance(payload, dict) else payload
    if chamado_id is not None: snapshot["id"] = chamado_id
    snapshot.setdefault("region_label", getattr(region, "label", None))
    snapshot.setdefault("region_slug", getattr(region, "slug", None))
    return snapshot


def _fetch_chamado_snapshot(region, chamado_id):
    row = get_chamado(region, chamado_id)
    return _snapshot_payload(region, row, chamado_id) if row else None


def _log_chamado_audit(action, region, *, chamado_id=None, before=None, after=None, message=None):
    try: return write_audit(entity_type="support_chamado", action=action, entity_id=chamado_id, before=before, after=after, message=message or f"Chamado {action} em {getattr(region, 'label', '')}")
    except Exception: current_app.logger.exception("Não foi possível registrar auditoria dos chamados.")


def _format_csv_value(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _fetch_concluded_entries(form: ConcluidoFilterForm):
    query = AtendimentoSuporte.query.filter(AtendimentoSuporte.status == "Concluido")
    if form.usuario_designado.data: query = query.filter(AtendimentoSuporte.usuario_designado == form.usuario_designado.data)
    if form.data_inicial.data: query = query.filter(AtendimentoSuporte.data_atendimento >= datetime.combine(form.data_inicial.data, datetime.min.time()))
    if form.data_final.data: query = query.filter(AtendimentoSuporte.data_atendimento <= datetime.combine(form.data_final.data, datetime.max.time()))
    return query.order_by(AtendimentoSuporte.data_atendimento.desc()).all()


def _touch_last_assignment(user_id: int | None) -> None:
    if not user_id: return
    record = UltimoAtendimento.query.get(user_id)
    if not record:
        record = UltimoAtendimento(tecnico_id=user_id)
        db.session.add(record)
    record.ultimo_atendimento = datetime.now()


def _register_tecnica_routes():
    routes = [
        ("/api/chamados", chamados_api, None),
        ("/api/cnpj", api_cnpj, None),
        ("/chamados", chamados_dashboard, None),
        ("/chamados/concluidos", chamados_concluidos, None),
        ("/chamados/export", exportar_chamados, None),
        ("/chamados/export_pdf", exportar_chamados_pdf, None),
        ("/chamados/criar", criar_chamado, ["POST"]),
        ("/chamados/<string:region_slug>/<int:chamado_id>/editar", editar_chamado, ["POST"]),
        ("/chamados/<string:region_slug>/<int:chamado_id>/fechar", fechar_chamado, ["POST"]),
        ("/chamados/<string:region_slug>/<int:chamado_id>/arquivo/<string:kind>", download_chamado_arquivo, None),
        ("/chamados/<string:region_slug>/<int:chamado_id>/excluir", excluir_chamado, ["POST"]),
    ]
    for rule, view, methods in routes:
        tech_bp.add_url_rule(rule, view_func=view, methods=methods) if methods else tech_bp.add_url_rule(rule, view_func=view)

_register_tecnica_routes()
