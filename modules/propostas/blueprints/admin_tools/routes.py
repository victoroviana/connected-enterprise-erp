"""Rotas administrativas herdadas do sistema legado."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List
from uuid import uuid4
import math
from types import SimpleNamespace
import unicodedata

from flask import current_app, flash, redirect, render_template, request, url_for, session, jsonify
from flask_login import current_user
from werkzeug.utils import secure_filename

from sqlalchemy import func
from extensions import db
from ...models import AgendaEntry, Birthday, User, VacationEntry
from ..auth import login_required
from modules.audit.models import AuditLog
from modules.sollus_tickets.models import SollusTicketEvent, SollusTicketThreadEntry
from ..auth.permissions_utils import normalize_role_key, raw_permissions, current_permissions
from . import admin_tools_bp

from utils.helpers import (
    wants_json as _wants_json,
)

MONTH_LABELS = [
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
]

VACATION_UNITS = [
    "Solus RJ",
    "Technosollus RJ",
    "Technosollus ES",
    "SS Santos",
]

UNIT_DISPLAY_OVERRIDES = {
    'solus rj': 'Sollus Tecnologia',
    'sollus tecnologia': 'Sollus Tecnologia',
}

AGENDA_PERIODS = [
    "Manhã",
    "Tarde",
    "Dia todo",
]

PERMISSION_MAP = {
    "birthdays": "admin_aniversariantes",
    "vacations": "admin_ferias",
    "agenda": "admin_agenda_tecnica",
    "gallery": "admin_galeria",
    "monitoring": "admin_monitoramento",
}

SUPPORT_DEPTS = {"SUPORTE"}
ASSIST_DEPTS = {"ASSISTENCIA TECNICA", "ESTOQUE", "OFICINA"}
HR_DEPTS = {"RH"}
GALLERY_DIRNAME = "galeria"
GALLERY_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _role_key() -> str:
    return normalize_role_key(getattr(current_user, "tipo", None) or session.get("tipo"))


def _dept_names() -> set[str]:
    names: set[str] = set()
    try:
        for name in getattr(current_user, "department_names", []) or []:
            cleaned = (name or "").strip()
            if cleaned:
                normalized = unicodedata.normalize("NFKD", cleaned)
                normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
                names.add(normalized.upper())
    except Exception:
        return set()
    return names


def _gallery_root() -> Path:
    return Path(current_app.static_folder) / GALLERY_DIRNAME


def _list_gallery_images(limit: int | None = None) -> list[str]:
    root = _gallery_root()
    if not root.exists():
        return []
    files = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in GALLERY_EXTENSIONS]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if limit:
        files = files[:limit]
    return [p.name for p in files]


def _is_allowed_gallery_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in GALLERY_EXTENSIONS


def _resolve_gallery_file(filename: str) -> Path | None:
    if not filename:
        return None
    if "/" in filename or "\\" in filename:
        return None
    if not _is_allowed_gallery_file(filename):
        return None
    root = _gallery_root().resolve()
    target = (root / filename).resolve()
    if target == root or root not in target.parents:
        return None
    return target


def _has_access(flag: str, *, allowed_depts: set[str] | None = None) -> bool:
    role_key = _role_key()
    if role_key in ("admin", "gestor"):
        return True
    if current_permissions().get(flag, False):
        return True
    if allowed_depts and (_dept_names() & allowed_depts):
        return True
    return False




def _deny_access(area_label: str):
    from flask import request
    if "/api/" in getattr(request, "path", "") or _wants_json():
        return jsonify({"error": "Access denied", "success": False, "message": f"Você não tem permissão para acessar {area_label}."}), 403
    flash(
        "Você não tem permissão para acessar esta área. Procure seu superior caso precise de acesso.",
        "warning",
    )
    return redirect(url_for("sem_permissao", area=area_label))


@admin_tools_bp.before_request
def _check_admin_tools_access():
    from flask import request
    endpoint = getattr(request, "endpoint", "") or ""
    if endpoint and not endpoint.startswith("admin_tools_bp."):
        return
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
    role_key = _role_key()
    if role_key in ("admin", "gestor"):
        return
    perms = current_permissions()
    if any(
        perms.get(key, False)
        for key in (
            "usuarios_acesso",
            "usuarios_gerenciar",
            "permissoes_gerenciar",
            "admin_aniversariantes",
            "admin_ferias",
            "admin_agenda_tecnica",
            "admin_galeria",
            "admin_assistencia",
            "admin_suporte",
        )
    ):
        return
    if _dept_names() & (SUPPORT_DEPTS | ASSIST_DEPTS | HR_DEPTS):
        return
    return _deny_access("Administração")


def _technician_role_slugs() -> list[str]:
    raw = current_app.config.get("TECHNICIAN_ROLE_SLUGS") or ["tecnico"]
    if isinstance(raw, str):
        raw = [value.strip().lower() for value in raw.split(",") if value.strip()]
    return [value.strip().lower() for value in raw if value]


def _format_unit_label(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip()
    return UNIT_DISPLAY_OVERRIDES.get(normalized.casefold(), normalized)


def _chunk_entries(entries, size):
    chunk = []
    for entry in entries:
        chunk.append(entry)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk

def _unit_from_user(user: User | None, fallback: str | None = None) -> str:
    if user and getattr(user, 'unit_code', None):
        return user.unit_code
    return fallback or VACATION_UNITS[0]


@admin_tools_bp.route("/")
@login_required
def admin_hub():
    permissions = current_permissions()
    role_key = _role_key()

    can_manage_users = role_key in ("admin", "gestor") or permissions.get("usuarios_acesso") or permissions.get("permissoes_gerenciar")
    can_manage_permissions = role_key == "admin" or permissions.get("permissoes_gerenciar")
    can_view_birthdays = _has_access(PERMISSION_MAP["birthdays"])
    can_view_vacations = _has_access(PERMISSION_MAP["vacations"], allowed_depts=HR_DEPTS)
    can_view_agenda = _has_access(PERMISSION_MAP["agenda"], allowed_depts=ASSIST_DEPTS)
    can_view_galeria = _has_access(PERMISSION_MAP["gallery"], allowed_depts=HR_DEPTS)
    can_view_support = _has_access("admin_suporte", allowed_depts=SUPPORT_DEPTS)
    can_view_assistencia = _has_access("admin_assistencia", allowed_depts=ASSIST_DEPTS)
    can_view_audit = role_key in ("admin", "gestor") or permissions.get("permissoes_gerenciar") or permissions.get("usuarios_acesso")
    can_view_monitoring = role_key == "admin" or permissions.get("admin_monitoramento", False)

    cards: list[dict[str, str]] = []
    if can_manage_users:
        cards.append({
            "title": "Usuários",
            "description": "Cadastre, edite ou desative contas da equipe.",
            "icon": "fa-solid fa-users-gear",
            "url": url_for("auth_bp.gerenciar_usuarios"),
        })
        cards.append({
            "title": "Usuários Online",
            "description": "Veja quem está online no momento no sistema.",
            "icon": "fa-solid fa-user-clock",
            "url": url_for("admin_tools_bp.online_users"),
        })
        cards.append({
            "title": "Manutenção do Sistema",
            "description": "Dispare avisos com contagem regressiva antes de reiniciar o servidor.",
            "icon": "fa-solid fa-screwdriver-wrench",
            "url": url_for("admin_tools_bp.manutencao_sistema"),
        })
    if can_manage_permissions:
        cards.append({
            "title": "Permissões",
            "description": "Controle os tipos de acesso e os departamentos.",
            "icon": "fa-solid fa-user-shield",
            "url": url_for("auth_bp.gerenciar_permissoes"),
        })
    if can_view_birthdays:
        cards.append({
            "title": "Aniversariantes",
            "description": "Organize a agenda de comemorações e envie lembretes.",
            "icon": "fa-solid fa-cake-candles",
            "url": url_for("admin_tools_bp.aniversariantes_dashboard"),
        })
    if can_view_vacations:
        cards.append({
            "title": "Mapa de Férias",
            "description": "Gerencie períodos aprovados e prossiga com ajustes.",
            "icon": "fa-solid fa-umbrella-beach",
            "url": url_for("admin_tools_bp.ferias_dashboard"),
        })
    if can_view_galeria:
        cards.append({
            "title": "Galeria de fotos",
            "description": "Atualize as imagens do carrossel exibido na tela inicial.",
            "icon": "fa-solid fa-camera-retro",
            "url": url_for("admin_tools_bp.galeria_dashboard"),
        })
    if can_view_support:
        cards.append({
            "title": "Atendimentos de Suporte",
            "description": "Acompanhe chamados, atribua técnicos e visualize o histórico.",
            "icon": "fa-solid fa-headset",
            "url": url_for("support_bp.atendimentos_dashboard"),
        })
    if can_view_assistencia:
        cards.append({
            "title": "Assistência técnica",
            "description": "Fluxo legado convertido: OS internas/fábrica, anexos e retornos.",
            "icon": "fa-solid fa-screwdriver-wrench",
            "url": url_for("assist_bp.assistencia_dashboard"),
        })
    if can_view_audit:
        cards.append({
            "title": "Auditoria",
            "description": "Consulte o histórico detalhado de acessos e ações.",
            "icon": "fa-solid fa-shield-halved",
            "url": url_for("audit.page"),
        })
    if can_view_monitoring:
        cards.append({
            "title": "Monitoramento de Atrasos",
            "description": "Visualize e acompanhe todas as tarefas pendentes e em atraso de todos os setores.",
            "icon": "fa-solid fa-clock-rotate-left",
            "url": url_for("admin_tools_bp.monitoramento_atrasos"),
        })

    hero_stats = [
        {
            "label": "Ferramentas liberadas",
            "value": len(cards),
            "hint": "Exibidas conforme o seu perfil",
        }
    ]

    return render_template(
        "admin/hub.html",
        admin_cards=cards,
        hero_stats=hero_stats,
        can_manage_users=can_manage_users,
    )


@admin_tools_bp.route("/galeria")
@login_required
def galeria_dashboard():
    guard = _require_permission(PERMISSION_MAP["gallery"])
    if guard:
        return guard

    images = _list_gallery_images()
    return render_template(
        "admin/galeria.html",
        gallery_images=images,
        total_images=len(images),
    )


@admin_tools_bp.route("/galeria/upload", methods=["POST"])
@login_required
def galeria_upload():
    guard = _require_permission(PERMISSION_MAP["gallery"])
    if guard:
        return guard

    files = request.files.getlist("photos") if request.files else []
    if not files:
        flash("Selecione ao menos uma imagem.", "warning")
        return redirect(url_for("admin_tools_bp.galeria_dashboard"))

    saved = 0
    errors = 0
    skipped = 0
    root = _gallery_root()
    root.mkdir(parents=True, exist_ok=True)

    for file_storage in files:
        if not file_storage or not getattr(file_storage, "filename", ""):
            skipped += 1
            continue
        safe_name = secure_filename(file_storage.filename or "")
        if not safe_name:
            errors += 1
            continue
        if not _is_allowed_gallery_file(safe_name):
            errors += 1
            continue
        ext = Path(safe_name).suffix.lower()
        target = root / f"{uuid4().hex}{ext}"
        try:
            file_storage.save(target)
        except Exception:
            current_app.logger.exception("Failed to save gallery image: %s", safe_name)
            errors += 1
            continue
        saved += 1

    if saved:
        flash(f"{saved} foto(s) adicionada(s) com sucesso.", "success")
    if errors or skipped:
        flash("Algumas imagens não puderam ser enviadas.", "warning")
    if not saved and not errors:
        flash("Nenhuma imagem válida foi enviada.", "warning")
    return redirect(url_for("admin_tools_bp.galeria_dashboard"))


@admin_tools_bp.route("/galeria/excluir", methods=["POST"])
@login_required
def galeria_excluir():
    guard = _require_permission(PERMISSION_MAP["gallery"])
    if guard:
        return guard

    filename = (request.form.get("filename") or "").strip()
    target = _resolve_gallery_file(filename)
    if not target or not target.exists() or not target.is_file():
        flash("Imagem não encontrada.", "warning")
        return redirect(url_for("admin_tools_bp.galeria_dashboard"))

    try:
        target.unlink()
    except Exception:
        current_app.logger.exception("Failed to delete gallery image: %s", filename)
        flash("Não foi possível remover a imagem.", "danger")
        return redirect(url_for("admin_tools_bp.galeria_dashboard"))

    flash("Imagem removida com sucesso.", "success")
    return redirect(url_for("admin_tools_bp.galeria_dashboard"))


def _active_users_query():
    return User.query.filter(User.is_active.is_(True)).order_by(User.nome_completo.asc())


def _normalize_name(value: str | None) -> str:
    return (value or "").strip().casefold()


def _require_permission(flag: str):
    allowed_depts = None
    if flag == PERMISSION_MAP["agenda"]:
        allowed_depts = ASSIST_DEPTS
    if flag in (PERMISSION_MAP["vacations"], PERMISSION_MAP["gallery"]):
        allowed_depts = HR_DEPTS
    if _has_access(flag, allowed_depts=allowed_depts):
        return None
    return _deny_access("Administração")


def _parse_iso_date(raw_value: str | None) -> date:
    if not raw_value:
        raise ValueError("Data inválida")
    return datetime.strptime(raw_value, "%Y-%m-%d").date()


# -------------------- ANIVERSARIANTES -------------------- #
@admin_tools_bp.route("/aniversariantes")
@login_required
def aniversariantes_dashboard():
    guard = _require_permission(PERMISSION_MAP["birthdays"])
    if guard:
        return guard

    page = request.args.get("page", type=int) or 1
    per_page = 5

    base_query = Birthday.query.order_by(Birthday.data_nascimento.asc())
    pagination = base_query.paginate(page=page, per_page=per_page, error_out=False)
    page_entries = pagination.items

    ordered_page = sorted(page_entries, key=_birthday_order_key)
    groups = _group_birthdays_by_month(ordered_page)

    all_entries = base_query.all()
    upcoming = _upcoming_birthdays(all_entries)
    users = _active_users_query().all()
    name_lookup = {_normalize_name(user.nome_completo): user.id for user in users if user.nome_completo}
    birthday_user_map = {entry.id: name_lookup.get(_normalize_name(entry.nome)) for entry in page_entries}

    birthday_pagination = SimpleNamespace(
        page=pagination.page,
        per_page=pagination.per_page,
        total=pagination.total,
        pages=pagination.pages,
        has_prev=pagination.has_prev,
        has_next=pagination.has_next,
        prev_num=pagination.prev_num,
        next_num=pagination.next_num,
    )
    birthday_page_numbers = [
        p for p in pagination.iter_pages(left_edge=1, right_edge=1, left_current=2, right_current=2) if p
    ]

    return render_template(
        "admin/aniversariantes.html",
        grouped_birthdays=groups,
        upcoming_birthdays=upcoming,
        total_birthdays=pagination.total,
        today=date.today(),
        users=users,
        birthday_user_map=birthday_user_map,
        birthday_pagination=birthday_pagination,
        birthday_page_numbers=birthday_page_numbers,
    )


@admin_tools_bp.route("/aniversariantes/criar", methods=["POST"])
@login_required
def criar_aniversariante():
    guard = _require_permission(PERMISSION_MAP["birthdays"])
    if guard:
        return guard

    usuario_id = request.form.get("usuario_id", type=int)
    user = User.query.get(usuario_id) if usuario_id else None
    data_str = request.form.get("data_nascimento")

    if not usuario_id or not data_str:
        flash("Preencha colaborador e data de nascimento.", "warning")
        return redirect(url_for("admin_tools_bp.aniversariantes_dashboard"))

    usuario = User.query.get(usuario_id)
    if not usuario:
        flash("Colaborador inválido.", "danger")
        return redirect(url_for("admin_tools_bp.aniversariantes_dashboard"))()

    try:
        nascimento = _parse_iso_date(data_str)
    except ValueError:
        flash("Formato de data inválido.", "danger")
        return redirect(url_for("admin_tools_bp.aniversariantes_dashboard"))

    db.session.add(Birthday(nome=usuario.nome_completo, data_nascimento=nascimento))
    db.session.commit()
    flash("Aniversariante cadastrado com sucesso.", "success")
    return redirect(url_for("admin_tools_bp.aniversariantes_dashboard"))


@admin_tools_bp.route("/aniversariantes/<int:birthday_id>/atualizar", methods=["POST"])
@login_required
def atualizar_aniversariante(birthday_id: int):
    guard = _require_permission(PERMISSION_MAP["birthdays"])
    if guard:
        return guard

    entry = Birthday.query.get_or_404(birthday_id)
    
    try:
        dia = int(request.form.get("dia") or 0)
        mes = int(request.form.get("mes") or 0)
        # Mantém o ano original do registro para não quebrar a data
        ano_original = entry.data_nascimento.year if entry.data_nascimento else date.today().year
        
        entry.data_nascimento = date(ano_original, mes, dia)
        # O nome não é alterado na edição, apenas a data
    except ValueError:
        flash("Data inválida.", "danger")
        return redirect(url_for("admin_tools_bp.aniversariantes_dashboard"))

    db.session.commit()
    flash("Aniversariante atualizado.", "success")
    return redirect(url_for("admin_tools_bp.aniversariantes_dashboard"))


@admin_tools_bp.route("/aniversariantes/<int:birthday_id>/excluir", methods=["POST"])
@login_required
def excluir_aniversariante(birthday_id: int):
    guard = _require_permission(PERMISSION_MAP["birthdays"])
    if guard:
        return guard

    entry = Birthday.query.get_or_404(birthday_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Registro removido com sucesso.", "success")
    return redirect(url_for("admin_tools_bp.aniversariantes_dashboard"))


# -------------------- férias -------------------- #
@admin_tools_bp.route("/ferias")
@login_required
def ferias_dashboard():
    guard = _require_permission(PERMISSION_MAP["vacations"])
    if guard:
        return guard

    today = date.today()
    selected_year = request.args.get("ano", type=int) or today.year
    page = request.args.get("page", type=int) or 1
    per_page = 5

    ferias_query = (
        VacationEntry.query.filter_by(referente_ano=selected_year)
        .order_by(VacationEntry.data_inicial.asc())
    )
    ferias_all = ferias_query.all()
    for entry in ferias_all:
        entry.display_unit = _format_unit_label(entry.unidade)

    available_years = [
        value[0]
        for value in db.session.query(VacationEntry.referente_ano)
        .distinct()
        .order_by(VacationEntry.referente_ano.desc())
        .all()
    ]
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years.sort(reverse=True)

    total_entries = len(ferias_all)
    future_vacations = [entry for entry in ferias_all if entry.data_final >= today]
    upcoming_groups = list(_chunk_entries(future_vacations, 3))
    total_days = sum(entry.duration_days for entry in ferias_all)

    pages = math.ceil(total_entries / per_page) if total_entries else 1
    if page < 1:
        page = 1
    if page > pages:
        page = pages
    start_idx = (page - 1) * per_page
    ferias_entries = ferias_all[start_idx:start_idx + per_page]

    users = _active_users_query().all()
    id_lookup = {user.id: user for user in users}
    name_lookup = {_normalize_name(user.nome_completo): user for user in users if user.nome_completo}

    def _resolve_user(entry):
        value = (entry.usuario_id or '').strip()
        if value.isdigit():
            return id_lookup.get(int(value))
        return name_lookup.get(_normalize_name(value))

    vacation_user_map = {entry.id: _resolve_user(entry) for entry in ferias_all}

    ferias_pagination = SimpleNamespace(
        page=page,
        per_page=per_page,
        total=total_entries,
        pages=pages,
        has_prev=page > 1,
        has_next=page < pages,
        prev_num=page - 1 if page > 1 else None,
        next_num=page + 1 if page < pages else None,
    )
    pagination_numbers = list(range(1, pages + 1)) if pages else [1]

    return render_template(
        "admin/ferias.html",
        ferias=ferias_entries,
        ferias_total=total_entries,
        ferias_pagination=ferias_pagination,
        selected_year=selected_year,
        available_years=available_years,
        upcoming_ferias_groups=upcoming_groups,
        total_days=total_days,
        users=users,
        vacation_user_map=vacation_user_map,
        ferias_page_numbers=pagination_numbers,
    )


@admin_tools_bp.route("/ferias/criar", methods=["POST"])
@login_required
def criar_ferias():
    guard = _require_permission(PERMISSION_MAP["vacations"])
    if guard:
        return guard

    ano = request.form.get("ano_referencia", type=int)
    usuario_ids = request.form.getlist("usuario_id[]")
    datas_iniciais = request.form.getlist("data_inicial[]")
    datas_finais = request.form.getlist("data_final[]")

    created = 0
    for usuario_id, inicio, fim in zip(usuario_ids, datas_iniciais, datas_finais):
        usuario = User.query.get(int(usuario_id)) if usuario_id else None
        if not usuario or not inicio or not fim:
            continue
        try:
            data_inicial = _parse_iso_date(inicio)
            data_final = _parse_iso_date(fim)
        except ValueError:
            continue
        if data_final < data_inicial:
            continue
        unit_value = _unit_from_user(usuario)
        db.session.add(
            VacationEntry(
                usuario_id=str(usuario.id),
                data_inicial=data_inicial,
                data_final=data_final,
                referente_ano=ano,
                unidade=unit_value,
            )
        )
        created += 1

    if created:
        db.session.commit()
        flash(f"{created} período(s) cadastrados.", "success")
    else:
        flash("Nenhum registro vlido informado.", "warning")
    return redirect(url_for("admin_tools_bp.ferias_dashboard", ano=ano or date.today().year))


@admin_tools_bp.route("/ferias/<int:ferias_id>/atualizar", methods=["POST"])
@login_required
def atualizar_ferias(ferias_id: int):
    guard = _require_permission(PERMISSION_MAP["vacations"])
    if guard:
        return guard

    entry = VacationEntry.query.get_or_404(ferias_id)
    usuario_id = request.form.get("usuario_id", type=int)
    if not usuario_id:
        flash("Informe o colaborador.", "warning")
        return redirect(url_for("admin_tools_bp.ferias_dashboard", ano=entry.referente_ano))

    usuario = User.query.get(usuario_id)
    if not usuario:
        flash("Colaborador inválido.", "danger")
        return redirect(url_for("admin_tools_bp.ferias_dashboard", ano=entry.referente_ano))

    try:
        data_inicial = _parse_iso_date(request.form.get("data_inicial"))
        data_final = _parse_iso_date(request.form.get("data_final"))
    except ValueError:
        flash("Datas inválidas.", "danger")
        return redirect(url_for("admin_tools_bp.ferias_dashboard", ano=entry.referente_ano))

    if data_final < data_inicial:
        flash("A data final deve ser igual ou posterior  inicial.", "warning")
        return redirect(url_for("admin_tools_bp.ferias_dashboard", ano=entry.referente_ano))

    entry.usuario_id = str(usuario.id)
    entry.data_inicial = data_inicial
    entry.data_final = data_final
    entry.unidade = _unit_from_user(usuario, entry.unidade)
    db.session.commit()
    flash("Perodo atualizado.", "success")
    return redirect(url_for("admin_tools_bp.ferias_dashboard", ano=entry.referente_ano))


@admin_tools_bp.route("/ferias/<int:ferias_id>/excluir", methods=["POST"])
@login_required
def excluir_ferias(ferias_id: int):
    guard = _require_permission(PERMISSION_MAP["vacations"])
    if guard:
        return guard

    entry = VacationEntry.query.get_or_404(ferias_id)
    year = entry.referente_ano
    db.session.delete(entry)
    db.session.commit()
    flash("Registro de férias removido.", "success")
    return redirect(url_for("admin_tools_bp.ferias_dashboard", ano=year))


# -------------------- AGENDA -------------------- #
@admin_tools_bp.route("/agenda-tecnica")
@login_required
def agenda_tecnica():
    return redirect(url_for("assist_bp.agenda_tecnica"))


@admin_tools_bp.route("/agenda-tecnica/criar", methods=["POST"])
@login_required
def criar_agendamento():
    return redirect(url_for("assist_bp.criar_agendamento"))


@admin_tools_bp.route("/agenda-tecnica/<int:agenda_id>/atualizar", methods=["POST"])
@login_required
def atualizar_agendamento(agenda_id: int):
    return redirect(url_for("assist_bp.atualizar_agendamento", entry_id=agenda_id))


@admin_tools_bp.route("/agenda-tecnica/<int:agenda_id>/excluir", methods=["POST"])
@login_required
def excluir_agendamento(agenda_id: int):
    return redirect(url_for("assist_bp.excluir_agendamento", entry_id=agenda_id))


# -------------------- HELPERS -------------------- #

def _birthday_order_key(entry: Birthday) -> tuple[int, int, str]:
    if not entry.data_nascimento:
        return (13, 32, entry.nome.lower())
    return (
        entry.data_nascimento.month,
        entry.data_nascimento.day,
        entry.nome.lower(),
    )


def _group_birthdays_by_month(entries: Iterable[Birthday]) -> List[dict]:
    grouped: List[dict] = []
    for month in range(1, 13):
        month_entries = [item for item in entries if item.data_nascimento and item.data_nascimento.month == month]
        if not month_entries:
            continue
        grouped.append(
            {
                "month": month,
                "label": MONTH_LABELS[month - 1],
                "entries": month_entries,
            }
        )
    return grouped


def _upcoming_birthdays(entries: Iterable[Birthday], limit: int = 4) -> List[dict]:
    today = date.today()
    ranked: List[tuple[int, Birthday]] = []
    for entry in entries:
        if not entry.data_nascimento:
            continue
        ranked.append((_days_until_next_birthday(entry, today), entry))
    ranked.sort(key=lambda item: (item[0], item[1].nome.lower()))

    upcoming: List[dict] = []
    for delta, entry in ranked[:limit]:
        upcoming.append(
            {
                "entry": entry,
                "days": delta,
                "next_date": _next_birthday_date(entry, today),
            }
        )
    return upcoming


def _days_until_next_birthday(entry: Birthday, reference: date) -> int:
    next_date = _next_birthday_date(entry, reference)
    return (next_date - reference).days


def _next_birthday_date(entry: Birthday, reference: date) -> date:
    try:
        target = entry.data_nascimento.replace(year=reference.year)
    except ValueError:
        target = entry.data_nascimento.replace(month=2, day=28, year=reference.year)

    if target < reference:
        try:
            target = target.replace(year=reference.year + 1)
        except ValueError:
            target = target.replace(month=2, day=28, year=reference.year + 1)
    return target


@admin_tools_bp.route("/monitoramento-atrasos")
@login_required
def monitoramento_atrasos():
    role_key = _role_key()
    if not (role_key == "admin" or current_permissions().get("admin_monitoramento", False)):
        return _deny_access("Administração")

    from modules.suporte.models import AssistenciaTarefa, AtendimentoSuporte
    from modules.sollus_tickets.models import SollusTicket
    from datetime import date, datetime, timedelta
    from sqlalchemy import or_

    today = date.today()
    now = datetime.utcnow()
    two_days_ago = now - timedelta(hours=48)

    class WrappedDelayedItem:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    # 1. Fetch delayed AssistenciaTarefa tasks
    db_tasks = AssistenciaTarefa.query.filter(
        or_(
            AssistenciaTarefa.status.is_(None),
            AssistenciaTarefa.status.notin_(["concluído", "devolucao_sem_reparo", "descarte"])
        ),
        AssistenciaTarefa.data_fim < today
    ).all()

    combined_items = []

    # Map AssistenciaTarefa tasks
    for task in db_tasks:
        delay_days = (today - task.data_fim).days if task.data_fim else 0
        combined_items.append(WrappedDelayedItem(
            id=f"task_{task.id}",
            is_ticket=False,
            is_support=False,
            OS=task.OS,
            nome=task.nome,
            tipo_atendimento=task.tipo_atendimento or "Tipo não informado",
            departamento_responsavel=(task.departamento_responsavel or "Não Definido").upper().strip(),
            usuario_designado=task.usuario_designado or "Não designado",
            data_fim=task.data_fim,
            delay_days=max(0, delay_days),
            unidade=task.unidade or "Não Definido",
            descricao=task.descricao or "Nenhuma descrição fornecida.",
            atualizacoes=task.atualizacoes or "Nenhuma atualização registrada neste chamado."
        ))

    # 2. Fetch delayed SollusTicket records
    open_tickets = SollusTicket.query.filter(
        SollusTicket.status_key.notin_({"closed", "resolved", "archived"})
    ).all()

    for t in open_tickets:
        due_datetime = t.due_at if t.due_at else t.created_at + timedelta(hours=48)
        if due_datetime < now:
            due_date = due_datetime.date()
            delay_days = (today - due_date).days
            
            # Compile conversation history HTML
            parts = []
            for entry in t.entries:
                author_name = entry.author.name or entry.author.email if entry.author else (entry.contact.name or entry.contact.email if entry.contact else "Sistema")
                parts.append(f"<b>{entry.created_at.strftime('%d/%m/%Y %H:%M')} - {author_name}:</b><br>{entry.body}")
            atualizacoes_html = "<br><br>".join(parts) if parts else "Nenhuma atualização registrada."

            first_entry_body = t.entries[0].body if t.entries else t.subject

            combined_items.append(WrappedDelayedItem(
                id=f"ticket_{t.id}",
                is_ticket=True,
                is_support=False,
                ticket_id=t.id,
                OS=t.number,
                nome=t.requester_label,
                tipo_atendimento=t.topic.name if t.topic else "Chamado de Suporte",
                departamento_responsavel=t.department.name.upper().strip() if t.department else "SUPORTE",
                usuario_designado=t.assignee.name or t.assignee.email if t.assignee else "Não designado",
                data_fim=due_date,
                delay_days=max(0, delay_days),
                unidade="Ticket",
                descricao=first_entry_body,
                atualizacoes=atualizacoes_html
            ))

    # 3. Fetch delayed AtendimentoSuporte calls
    # User map for looking up designated users
    from models import User, Department
    user_map = {u.id: u.nome_completo or u.email for u in User.query.all()}

    open_support_calls = AtendimentoSuporte.query.filter(
        or_(
            AtendimentoSuporte.status.is_(None),
            AtendimentoSuporte.status.notin_(["Concluido", "concluido"])
        ),
        AtendimentoSuporte.data_entrada < datetime.now() - timedelta(hours=24)
    ).all()

    for s in open_support_calls:
        entry_date = None
        if s.data_entrada:
            if hasattr(s.data_entrada, "date"):
                entry_date = s.data_entrada.date()
            elif isinstance(s.data_entrada, date):
                entry_date = s.data_entrada
            elif isinstance(s.data_entrada, str):
                txt = s.data_entrada.strip()
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
        
        parts = []
        if s.resumo_atendimento:
            parts.append(f"<b>Resumo do Atendimento:</b><br>{s.resumo_atendimento}")
        if s.observacoes:
            parts.append(f"<b>Observações:</b><br>{s.observacoes}")
        if s.observacoes_alerta:
            parts.append(f"<b>Observações de Alerta:</b><br>{s.observacoes_alerta}")
        atualizacoes_html = "<br><br>".join(parts) if parts else "Nenhuma atualização registrada."

        os_number = s.os_entrada if s.os_entrada else f"SUP-{s.id:06d}"

        combined_items.append(WrappedDelayedItem(
            id=f"support_{s.id}",
            is_ticket=False,
            is_support=True,
            support_id=s.id,
            OS=os_number,
            nome=s.cliente or "Cliente não informado",
            tipo_atendimento=s.tipo_atendimento or "Atendimento de Suporte",
            departamento_responsavel="SUPORTE",
            usuario_designado=user_map.get(s.usuario_designado, "Não designado"),
            data_fim=entry_date,
            delay_days=max(0, delay_days),
            unidade="Suporte",
            descricao=s.descricao or "Nenhuma descrição fornecida.",
            atualizacoes=atualizacoes_html
        ))

    # Sort combined items by data_fim ascending (oldest first)
    combined_items.sort(key=lambda x: x.data_fim)

    # Calculate statistics across all combined items
    total_delayed = len(combined_items)
    total_delay_days = 0
    critical_count = 0
    sector_counts = {}

    for item in combined_items:
        dept = item.departamento_responsavel
        sector_counts[dept] = sector_counts.get(dept, 0) + 1
        total_delay_days += item.delay_days
        if item.delay_days > 30:
            critical_count += 1

    avg_delay = round(total_delay_days / total_delayed, 1) if total_delayed else 0

    # Dynamically fetch all departments and distinct task sectors
    dept_names_db = [d.name.upper().strip() for d in Department.query.all()]
    task_depts = [t[0].upper().strip() for t in db.session.query(AssistenciaTarefa.departamento_responsavel).distinct().all() if t[0]]
    all_sectors = sorted(list(set(dept_names_db + task_depts + ["SUPORTE"])))

    for s in all_sectors:
        if s not in sector_counts:
            sector_counts[s] = 0

    hero_stats = [
        {
            "label": "Total em Atraso",
            "value": total_delayed,
            "hint": "Itens pendentes em atraso",
        },
        {
            "label": "Média de Atraso",
            "value": f"{avg_delay} dias",
            "hint": "Média geral do vencimento",
        },
        {
            "label": "Atraso Crítico",
            "value": critical_count,
            "hint": "Vencidas há mais de 30 dias",
        }
    ]

    return render_template(
        "admin/monitoramento.html",
        tasks=combined_items,
        total_delayed=total_delayed,
        sector_counts=sector_counts,
        all_sectors=all_sectors,
        avg_delay=avg_delay,
        critical_count=critical_count,
        hero_stats=hero_stats,
        today=today,
    )


@admin_tools_bp.route("/usuarios-online")
@login_required
def online_users():
    role_key = _role_key()
    permissions = current_permissions()
    can_manage_users = role_key in ("admin", "gestor") or permissions.get("usuarios_acesso") or permissions.get("permissoes_gerenciar")
    if not can_manage_users:
        return _deny_access("Administração")

    from modules.audit.utils import _audit_table_available
    audit_available = _audit_table_available()

    # Track online users using in-memory cache
    import time
    from flask import current_app
    online_cache = getattr(current_app, "online_users_cache", {})
    now = time.time()
    
    # User is considered online if active in the last 60 seconds (1 minute)
    online_user_timestamps = {}
    for uid, t in list(online_cache.items()):
        if now - t <= 60:
            online_user_timestamps[uid] = t

    # Query only active users that are currently online
    if not online_user_timestamps:
        users = []
    else:
        users = User.query.filter(
            User.is_active.is_(True),
            User.id.in_(online_user_timestamps.keys())
        ).all()

    audit_map = {}
    if audit_available and users:
        try:
            sub_audit = db.session.query(
                AuditLog.actor_id,
                func.max(AuditLog.created_at).label("max_created")
            ).filter(AuditLog.actor_id.isnot(None), AuditLog.actor_id.in_(online_user_timestamps.keys())).group_by(AuditLog.actor_id).subquery()
            
            latest_audits = db.session.query(AuditLog).join(
                sub_audit, (AuditLog.actor_id == sub_audit.c.actor_id) & (AuditLog.created_at == sub_audit.c.max_created)
            ).all()
            audit_map = {log.actor_id: log for log in latest_audits}
        except Exception:
            db.session.rollback()

    event_map = {}
    if users:
        try:
            sub_event = db.session.query(
                SollusTicketEvent.actor_user_id,
                func.max(SollusTicketEvent.created_at).label("max_created")
            ).filter(SollusTicketEvent.actor_user_id.isnot(None), SollusTicketEvent.actor_user_id.in_(online_user_timestamps.keys())).group_by(SollusTicketEvent.actor_user_id).subquery()
            
            latest_events = db.session.query(SollusTicketEvent).join(
                sub_event, (SollusTicketEvent.actor_user_id == sub_event.c.actor_user_id) & (SollusTicketEvent.created_at == sub_event.c.max_created)
            ).all()
            event_map = {evt.actor_user_id: evt for evt in latest_events}
        except Exception:
            db.session.rollback()

    entry_map = {}
    if users:
        try:
            sub_entry = db.session.query(
                SollusTicketThreadEntry.author_user_id,
                func.max(SollusTicketThreadEntry.created_at).label("max_created")
            ).filter(SollusTicketThreadEntry.author_user_id.isnot(None), SollusTicketThreadEntry.author_user_id.in_(online_user_timestamps.keys())).group_by(SollusTicketThreadEntry.author_user_id).subquery()
            
            latest_entries = db.session.query(SollusTicketThreadEntry).join(
                sub_entry, (SollusTicketThreadEntry.author_user_id == sub_entry.c.author_user_id) & (SollusTicketThreadEntry.created_at == sub_entry.c.max_created)
            ).all()
            entry_map = {ent.author_user_id: ent for ent in latest_entries}
        except Exception:
            db.session.rollback()

    ACTION_TRANSLATIONS = {
        "create": "Criação",
        "update": "Edição",
        "delete": "Exclusão",
        "link": "Associação",
        "unlink": "Desassociação",
        "assign": "Atribuição",
        "status": "Mudança de status",
        "reply": "Resposta",
        "upload": "Upload de arquivo",
    }

    results = []
    for user in users:
        candidates = []
        if user.id in audit_map:
            log = audit_map[user.id]
            desc = log.message or f"{ACTION_TRANSLATIONS.get(log.action.lower(), log.action.upper())} em {log.entity_type}"
            candidates.append((log.created_at, desc))
        if user.id in event_map:
            evt = event_map[user.id]
            desc = f"Ticket #{evt.ticket.number if evt.ticket else evt.ticket_id}: {evt.action}"
            candidates.append((evt.created_at, desc))
        if user.id in entry_map:
            ent = entry_map[user.id]
            entry_type = "Resposta" if ent.type == "message" else "Nota interna"
            desc = f"{entry_type} no Ticket #{ent.ticket.number if ent.ticket else ent.ticket_id}"
            candidates.append((ent.created_at, desc))

        if candidates:
            last_dt, last_desc = max(candidates, key=lambda x: x[0])
        else:
            last_dt, last_desc = None, "Nenhuma interação recente registrada no banco"
            
        t = online_user_timestamps.get(user.id, now)
        diff = int(now - t)
        if diff < 10:
            online_since_desc = "Ativo agora"
        elif diff < 60:
            online_since_desc = f"Ativo há {diff}s"
        else:
            mins = diff // 60
            online_since_desc = f"Ativo há {mins}m"

        results.append({
            "user": user,
            "last_interaction_at": last_dt,
            "last_interaction_desc": last_desc,
            "online_since_desc": online_since_desc
        })

    # Sort results by last interaction time (descending)
    results.sort(key=lambda x: x["last_interaction_at"] if x["last_interaction_at"] else datetime.min, reverse=True)

    hero_stats = [
        {
            "label": "Usuários Online",
            "value": len(users),
            "hint": "Conectados e ativos nos últimos 3 min",
        },
        {
            "label": "Interagiram Hoje",
            "value": sum(1 for r in results if r["last_interaction_at"] and r["last_interaction_at"].date() == date.today()),
            "hint": "Com atividade hoje no banco",
        }
    ]

    # Search filter
    search_query = request.args.get("q", "").strip()
    if search_query:
        q_lower = search_query.lower()
        results = [
            r for r in results
            if q_lower in (r["user"].nome_completo or "").lower()
            or q_lower in (r["user"].usuario or "").lower()
            or q_lower in (r["user"].email or "").lower()
        ]

    # Pagination
    page = request.args.get("page", 1, type=int)
    total = len(results)
    per_page = 6
    pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, pages))
    
    paginated_results = results[(page - 1) * per_page : page * per_page]
    
    pagination = {
        "page": page,
        "pages": pages,
        "total": total,
        "has_prev": page > 1,
        "prev_num": page - 1,
        "has_next": page < pages,
        "next_num": page + 1,
    }

    def build_url(**updates):
        args = dict(request.args)
        for key, value in updates.items():
            if value in (None, ""):
                args.pop(key, None)
            else:
                args[key] = value
        return url_for("admin_tools_bp.online_users", **args)

    return render_template(
        "admin/usuarios_online.html",
        results=paginated_results,
        hero_stats=hero_stats,
        pagination=pagination,
        search_query=search_query,
        build_url=build_url,
    )


@admin_tools_bp.route("/api/user-offline", methods=["GET"])
@login_required
def user_offline():
    import flask_login
    from flask import current_app, jsonify
    try:
        uid = flask_login.current_user.id
        online_cache = getattr(current_app, "online_users_cache", {})
        if uid in online_cache:
            online_cache.pop(uid, None)
    except Exception:
        pass
    return jsonify({"ok": True})


@admin_tools_bp.route("/api/maintenance-check", methods=["GET"])
@login_required
def maintenance_check():
    import os
    import json
    import time
    from flask import jsonify

    file_path = os.path.join(current_app.instance_path, "maintenance.json")
    if not os.path.exists(file_path):
        return jsonify({"active": False})

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        target = data.get("target_timestamp", 0)
        duration = data.get("duration", 120)
        now = time.time()
        remaining = int(target - now)
        if remaining > 0:
            return jsonify({
                "active": True,
                "remaining": remaining,
                "duration": duration,
                "message": data.get("message", "O sistema será reiniciado para manutenção.")
            })
        else:
            return jsonify({
                "active": True,
                "remaining": 0,
                "duration": duration,
                "message": "O sistema está sendo reiniciado..."
            })
    except Exception:
        return jsonify({"active": False})


@admin_tools_bp.route("/trigger-maintenance", methods=["POST"])
@login_required
def trigger_maintenance():
    role_key = _role_key()
    permissions = current_permissions()
    can_manage_users = role_key in ("admin", "gestor") or permissions.get("usuarios_acesso") or permissions.get("permissoes_gerenciar")
    if not can_manage_users:
        return jsonify({"ok": False, "message": "Sem permissão"}), 403

    import os
    import json
    import time
    file_path = os.path.join(current_app.instance_path, "maintenance.json")

    duration = int(request.form.get("duration", 120))
    message = request.form.get("message", "O sistema será reiniciado para manutenção preventiva. Salve o seu trabalho!").strip()
    if not message:
        message = "O sistema será reiniciado para manutenção preventiva."

    data = {
        "target_timestamp": time.time() + duration,
        "duration": duration,
        "message": message
    }

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        from modules.audit.utils import write_audit_external
        write_audit_external(
            entity_type="system",
            action="maintenance_trigger",
            message=f"Alerta de manutenção disparado: {duration}s."
        )
        return jsonify({"ok": True, "target_timestamp": data["target_timestamp"]})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@admin_tools_bp.route("/cancel-maintenance", methods=["POST"])
@login_required
def cancel_maintenance():
    role_key = _role_key()
    permissions = current_permissions()
    can_manage_users = role_key in ("admin", "gestor") or permissions.get("usuarios_acesso") or permissions.get("permissoes_gerenciar")
    if not can_manage_users:
        return jsonify({"ok": False, "message": "Sem permissão"}), 403

    import os
    file_path = os.path.join(current_app.instance_path, "maintenance.json")
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            from modules.audit.utils import write_audit_external
            write_audit_external(
                entity_type="system",
                action="maintenance_cancel",
                message="Alerta de manutenção cancelado."
            )
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)}), 500

    return jsonify({"ok": True})


@admin_tools_bp.route("/manutencao-sistema")
@login_required
def manutencao_sistema():
    role_key = _role_key()
    permissions = current_permissions()
    can_manage_users = role_key in ("admin", "gestor") or permissions.get("usuarios_acesso") or permissions.get("permissoes_gerenciar")
    if not can_manage_users:
        flash("Sem permissão para acessar esta ferramenta.", "danger")
        return redirect(url_for("admin_tools_bp.admin_hub"))

    return render_template(
        "admin/manutencao.html"
    )

