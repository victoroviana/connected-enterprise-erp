"""Lógica compartilhada da Agenda Técnica para múltiplos blueprints."""
from __future__ import annotations

from datetime import date, datetime
from flask import (
    Blueprint,
    current_app,
    jsonify,
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
    except Exception:
        return set()
    return names


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
            usuario_id = data.get("usuario_id") or current_user.id
            entry = AgendaEntry(
                usuario_id=int(usuario_id),
                unidade=data.get("unidade") or "",
                data_atendimento=datetime.strptime(data["data_atendimento"], "%Y-%m-%d").date(),
                periodo=data.get("periodo") or "Dia todo",
                obs=data.get("obs") or "",
            )
            db.session.add(entry)
            db.session.commit()
            return db.session.get(AgendaEntry, entry.id) and __import__("flask").redirect(
                __import__("flask").request.referrer or url_for(f"{bp.name}.agenda_tecnica")
            )
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("Erro ao criar agendamento")
            return __import__("flask").redirect(
                __import__("flask").request.referrer or url_for(f"{bp.name}.agenda_tecnica")
            )

    @bp.route("/api/agenda/<int:entry_id>/atualizar", methods=["POST"])
    @login_required
    def atualizar_agendamento(entry_id):
        entry = AgendaEntry.query.get_or_404(entry_id)
        data = request.form
        try:
            if "usuario_id" in data and data["usuario_id"]:
                entry.usuario_id = int(data["usuario_id"])
            if "data_atendimento" in data and data["data_atendimento"]:
                entry.data_atendimento = datetime.strptime(data["data_atendimento"], "%Y-%m-%d").date()
            if "periodo" in data:
                entry.periodo = data["periodo"]
            if "obs" in data:
                entry.obs = data["obs"]
            if "unidade" in data:
                entry.unidade = data["unidade"]
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ao atualizar agendamento %s", entry_id)
        return __import__("flask").redirect(
            __import__("flask").request.referrer or url_for(f"{bp.name}.agenda_tecnica")
        )

    @bp.route("/api/agenda/<int:entry_id>/excluir", methods=["POST"])
    @login_required
    def excluir_agendamento(entry_id):
        entry = AgendaEntry.query.get_or_404(entry_id)
        try:
            db.session.delete(entry)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ao excluir agendamento %s", entry_id)
        return __import__("flask").redirect(
            __import__("flask").request.referrer or url_for(f"{bp.name}.agenda_tecnica")
        )