"""Lógica compartilhada da Agenda Técnica para múltiplos blueprints."""
from __future__ import annotations

from datetime import date, datetime
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    session,
)
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload
import unicodedata

from extensions import db
from modules.propostas.models import AgendaEntry, User
from modules.propostas.blueprints.auth.permissions_utils import normalize_role_key, raw_permissions


def fix_encoding(text):
    """Corrige problemas de encoding (UTF-8 interpretado como Latin-1)."""
    if not text:
        return text
    if not isinstance(text, str):
        return str(text)
    try:
        return text.encode('latin1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _technician_role_slugs() -> list[str]:
    # Aceita 'tecnico' ou 'técnico' em qualquer variação
    raw = current_app.config.get("TECHNICIAN_ROLE_SLUGS") or ["tecnico", "técnico"]
    if isinstance(raw, str):
        raw = [value.strip().lower() for value in raw.split(",") if value.strip()]
    return [value.strip().lower() for value in raw if value]


def _dept_names(user=None) -> set[str]:
    actor = user or current_user
    names: set[str] = set()
    try:
        for name in getattr(actor, "department_names", []) or []:
            cleaned = (name or "").strip()
            if cleaned:
                normalized = unicodedata.normalize("NFKD", cleaned)
                normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
                names.add(normalized.upper())
            elif getattr(actor, "department", None) and getattr(actor.department, "name", None):
                cleaned_dep = (actor.department.name or "").strip()
                if cleaned_dep:
                    normalized = unicodedata.normalize("NFKD", cleaned_dep)
                    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
                    names.add(normalized.upper())
    except Exception:
        return set()
    return names


def _can_manage_agenda_entry(entry: AgendaEntry | None = None, target_user_id: int | None = None) -> bool:
    if not current_user.is_authenticated and not session.get("usuario_id"):
        return False
    role_key = normalize_role_key(
        getattr(current_user, "tipo", None)
        or getattr(current_user, "role", None)
        or session.get("tipo")
    )
    if role_key in ("admin", "gestor"):
        return True
    perms = raw_permissions(current_user)
    if perms.get("admin_agenda_tecnica") or perms.get("admin_assistencia") or perms.get("admin_suporte"):
        return True

    current_uid = int(session.get("usuario_id") or getattr(current_user, "id", None))
    # Standard technicians can only mutate their own records
    if entry is not None:
        if entry.usuario_id != current_uid:
            return False
        if target_user_id is not None and int(target_user_id) != current_uid:
            return False
        return True

    if entry is None and target_user_id is not None:
        return int(target_user_id) == current_uid

    return False


def register_agenda_routes(bp: Blueprint):
    """Registra as rotas da agenda no blueprint fornecido."""

    @bp.route("/agenda")
    @login_required
    def agenda_tecnica():
        try:
            from modules.propostas.models import Department

            # Busca usuários ativos dos departamentos OFICINA e SUPORTE
            allowed_slugs = ["oficina", "suporte"]
            allowed_dept_ids = [
                d.id for d in Department.query.filter(Department.slug.in_(allowed_slugs)).all()
            ]

            if allowed_dept_ids:
                technicians = (
                    User.query
                    .filter(
                        User.is_active.is_(True),
                        db.or_(
                            User.department_id.in_(allowed_dept_ids),
                            User.departments.any(Department.id.in_(allowed_dept_ids)),
                            db.func.lower(User.tipo).in_(['suporte', 'tecnico', 'técnico', 'oficina'])
                        ),
                    )
                    .order_by(User.nome_completo.asc())
                    .all()
                )
            else:
                # Fallback: todos os ativos
                technicians = (
                    User.query.filter(User.is_active.is_(True))
                    .order_by(User.nome_completo.asc())
                    .all()
                )

            periods = ["Manhã", "Tarde", "Dia todo"]
            bp_name = bp.name
            api_url = f"/{bp.url_prefix.strip('/')}/api/agenda" if bp.url_prefix else "/api/agenda"
            return render_template(
                "admin/agenda_tecnica.html",
                api_endpoint=api_url,
                technicians=technicians,
                periods=periods,
                agenda_bp=bp_name,
            )
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("Erro ao renderizar agenda")
            try:
                from modules.sollus_tickets.services import log_system_event
                log_system_event("Agenda Error", str(exc), level="error")
            except ImportError:
                pass
            raise


    @bp.route("/api/agenda")
    @login_required
    def agenda_tecnica_api():
        try:
            search = (request.args.get("search") or "").strip().lower()
            page = max(1, request.args.get("page", type=int) or 1)
            per_page = 20

            # Join com User para poder filtrar e obter nome do técnico
            query = (
                AgendaEntry.query
                .options(joinedload(AgendaEntry.tecnico))
                .order_by(AgendaEntry.data_atendimento.desc(), AgendaEntry.id.desc())
            )

            if search:
                query = query.join(User, AgendaEntry.usuario_id == User.id).filter(
                    db.or_(
                        User.nome_completo.ilike(f"%{search}%"),
                        AgendaEntry.unidade.ilike(f"%{search}%"),
                        AgendaEntry.obs.ilike(f"%{search}%"),
                    )
                )

            total = query.count()
            entries = query.offset((page - 1) * per_page).limit(per_page).all()

            bp_name = bp.name
            items = []
            for e in entries:
                try:
                    update_url = url_for(f"{bp_name}.atualizar_agendamento", entry_id=e.id)
                    delete_url = url_for(f"{bp_name}.excluir_agendamento", entry_id=e.id)
                except Exception:
                    update_url = ""
                    delete_url = ""

                tecnico_nome = ""
                if e.tecnico:
                    tecnico_nome = fix_encoding(e.tecnico.nome_completo or e.tecnico.email or "")
                else:
                    tecnico_nome = f"Usuário {e.usuario_id}"

                items.append({
                    "id": e.id,
                    "tecnico": tecnico_nome,
                    "unidade": fix_encoding(e.unidade) or "",
                    "data_atendimento": e.data_atendimento.isoformat() if e.data_atendimento else None,
                    "periodo": fix_encoding(e.periodo) or "",
                    "obs": fix_encoding(e.obs) or "",
                    "usuario_id": e.usuario_id,
                    "update_url": update_url,
                    "delete_url": delete_url,
                })

            pages = (total + per_page - 1) // per_page if per_page else 1
            return jsonify({
                "items": items,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": total,
                    "pages": pages,
                    "has_prev": page > 1,
                    "has_next": page < pages,
                    "prev_num": page - 1 if page > 1 else None,
                    "next_num": page + 1 if page < pages else None,
                }
            })
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("Erro na API da agenda")
            try:
                from modules.sollus_tickets.services import log_system_event
                log_system_event("Agenda API Error", str(exc), level="error")
            except ImportError:
                pass
            return jsonify({"error": str(exc), "items": []}), 500

    @bp.route("/api/agenda/criar", methods=["POST"])
    @login_required
    def criar_agendamento():
        data = request.form
        try:
            target_user_id = int(data.get("usuario_id") or current_user.id)
            if not _can_manage_agenda_entry(target_user_id=target_user_id):
                if "/api/" in getattr(request, "path", "") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"error": "Access denied", "success": False, "message": "Você não tem permissão para agendar para outro técnico."}), 403
                flash("Você não tem permissão para agendar para outro técnico.", "warning")
                return redirect(request.referrer or url_for(f"{bp.name}.agenda_tecnica"))

            unidade_val = (data.get("unidade") or "").strip()
            if not unidade_val:
                unidade_val = getattr(current_user, "unit_code", None) or "sollus"

            entry = AgendaEntry(
                usuario_id=target_user_id,
                unidade=unidade_val,
                data_atendimento=datetime.strptime(data["data_atendimento"], "%Y-%m-%d").date(),
                periodo=data.get("periodo") or "Dia todo",
                obs=data.get("obs") or "",
            )
            db.session.add(entry)
            db.session.commit()
            return redirect(request.referrer or url_for(f"{bp.name}.agenda_tecnica"))
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("Erro ao criar agendamento")
            return redirect(request.referrer or url_for(f"{bp.name}.agenda_tecnica"))

    @bp.route("/api/agenda/<int:entry_id>/atualizar", methods=["POST"])
    @login_required
    def atualizar_agendamento(entry_id):
        entry = AgendaEntry.query.get_or_404(entry_id)
        data = request.form
        try:
            new_uid = int(data["usuario_id"]) if data.get("usuario_id") else None
            if not _can_manage_agenda_entry(entry=entry, target_user_id=new_uid):
                if "/api/" in getattr(request, "path", "") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"error": "Access denied", "success": False, "message": "Você só pode alterar seus próprios agendamentos."}), 403
                flash("Você só pode alterar seus próprios agendamentos.", "warning")
                return redirect(request.referrer or url_for(f"{bp.name}.agenda_tecnica"))

            if new_uid:
                entry.usuario_id = new_uid
            if "data_atendimento" in data and data["data_atendimento"]:
                entry.data_atendimento = datetime.strptime(data["data_atendimento"], "%Y-%m-%d").date()
            if "periodo" in data:
                entry.periodo = data["periodo"]
            if "obs" in data:
                entry.obs = data["obs"]
            if "unidade" in data:
                u_val = (data["unidade"] or "").strip()
                if not u_val:
                    u_val = getattr(current_user, "unit_code", None) or "sollus"
                entry.unidade = u_val
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ao atualizar agendamento %s", entry_id)
        return redirect(request.referrer or url_for(f"{bp.name}.agenda_tecnica"))

    @bp.route("/api/agenda/<int:entry_id>/excluir", methods=["POST"])
    @login_required
    def excluir_agendamento(entry_id):
        entry = AgendaEntry.query.get_or_404(entry_id)
        try:
            if not _can_manage_agenda_entry(entry=entry):
                if "/api/" in getattr(request, "path", "") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"error": "Access denied", "success": False, "message": "Você só pode excluir seus próprios agendamentos."}), 403
                flash("Você só pode excluir seus próprios agendamentos.", "warning")
                return redirect(request.referrer or url_for(f"{bp.name}.agenda_tecnica"))

            db.session.delete(entry)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ao excluir agendamento %s", entry_id)
        return redirect(request.referrer or url_for(f"{bp.name}.agenda_tecnica"))