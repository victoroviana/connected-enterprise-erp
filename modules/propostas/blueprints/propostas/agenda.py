"""Rotas da Agenda dos Consultores Comerciais."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_, and_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from extensions import db
from modules.propostas.models import CommercialAgendaEntry, Department, User
from modules.audit.utils import write_audit
from . import propostas_bp

TIPO_COMPROMISSO_CHOICES = {
    "visita": {"label": "Visita Comercial", "color": "#0d6efd", "badge_class": "bg-primary"},
    "demonstracao": {"label": "Demonstração", "color": "#6f42c1", "badge_class": "bg-purple text-white"},
    "reuniao_interna": {"label": "Reunião Interna", "color": "#198754", "badge_class": "bg-success"},
    "atividade_externa": {"label": "Atividade Externa", "color": "#0dcaf0", "badge_class": "bg-info text-dark"},
    "ferias": {"label": "Férias / Ausência", "color": "#fd7e14", "badge_class": "bg-warning text-dark"},
    "disponivel": {"label": "Disponível na Empresa", "color": "#20c997", "badge_class": "bg-teal text-white"},
    "outro": {"label": "Outro", "color": "#6c757d", "badge_class": "bg-secondary"},
}

STATUS_CHOICES = {
    "agendado": {"label": "Agendado", "badge_class": "badge-soft-primary"},
    "realizado": {"label": "Realizado", "badge_class": "badge-soft-success"},
    "cancelado": {"label": "Cancelado", "badge_class": "badge-soft-danger"},
}


def _can_access_agenda() -> bool:
    if not current_user or not current_user.is_authenticated:
        return False
    if getattr(current_user, "role", "") == "admin" or getattr(current_user, "tipo", "") == "admin":
        return True
    perms = getattr(current_user, "permissions", {}) or {}
    if perms.get("comercial_agenda") or perms.get("propostas"):
        return True
    if getattr(current_user, "tipo", "") in ["gestor", "consultor", "consultorsp"]:
        return True
    if hasattr(current_user, "department") and current_user.department and current_user.department.name == "COMERCIAL":
        return True
    return False


def _is_manager() -> bool:
    if not current_user or not current_user.is_authenticated:
        return False
    if getattr(current_user, "role", "") in ["admin", "gestor"]:
        return True
    if getattr(current_user, "tipo", "") in ["admin", "gestor"]:
        return True
    return False


def _get_consultants() -> list[User]:
    """Retorna lista de consultores e gestores comerciais ativos."""
    try:
        dept_comercial = Department.query.filter(
            func_lower(Department.name).in_(["comercial", "comercial & vendas", "vendas"])
        ).first()
        dept_id = dept_comercial.id if dept_comercial else None

        query = User.query.filter(User.is_active.is_(True))
        filters = [
            User.tipo.in_(["consultor", "consultorsp", "gestor"]),
            User.role.in_(["consultor", "gestor"]),
        ]
        if dept_id:
            filters.append(User.department_id == dept_id)
            filters.append(User.departments.any(Department.id == dept_id))

        consultants = query.filter(or_(*filters)).order_by(User.nome_completo.asc()).all()
        if not consultants:
            consultants = User.query.filter(
                User.is_active.is_(True),
                ~User.tipo.in_(["tecnico", "técnico", "suporte", "oficina"])
            ).order_by(User.nome_completo.asc()).all()
        return consultants
    except Exception:
        return User.query.filter(User.is_active.is_(True)).order_by(User.nome_completo.asc()).all()


def func_lower(col):
    from sqlalchemy import func
    return func.lower(col)


@propostas_bp.route("/comercial/agenda", methods=["GET"])
@login_required
def agenda_comercial():
    if not _can_access_agenda():
        flash("Acesso restrito à agenda comercial.", "warning")
        return redirect(url_for("home"))

    consultants = _get_consultants()
    hoje = date.today()

    # Estatísticas do dia
    try:
        entries_today = CommercialAgendaEntry.query.filter(
            CommercialAgendaEntry.data_inicio <= hoje,
            or_(
                CommercialAgendaEntry.data_fim.is_(None),
                CommercialAgendaEntry.data_fim >= hoje,
            ),
            CommercialAgendaEntry.status != "cancelado",
        ).all()

        em_visita_uids = {
            e.usuario_id for e in entries_today
            if e.tipo_compromisso in ["visita", "demonstracao", "atividade_externa"]
        }
        em_ferias_uids = {
            e.usuario_id for e in entries_today
            if e.tipo_compromisso == "ferias"
        }
        total_consultores = len(consultants)
        em_visita_count = len(em_visita_uids)
        em_ferias_count = len(em_ferias_uids)
        disponiveis_count = max(0, total_consultores - em_visita_count - em_ferias_count)
    except Exception:
        total_consultores = len(consultants)
        em_visita_count = 0
        em_ferias_count = 0
        disponiveis_count = total_consultores

    return render_template(
        "propostas/agenda_comercial.html",
        consultants=consultants,
        tipos_compromisso=TIPO_COMPROMISSO_CHOICES,
        status_choices=STATUS_CHOICES,
        is_manager=_is_manager(),
        hoje=hoje,
        stats={
            "total_consultores": total_consultores,
            "disponiveis_hoje": disponiveis_count,
            "em_visita_hoje": em_visita_count,
            "em_ferias_hoje": em_ferias_count,
        },
    )


@propostas_bp.route("/comercial/api/agenda", methods=["GET"])
@login_required
def agenda_comercial_api():
    if not _can_access_agenda():
        return jsonify({"error": "Acesso não autorizado"}), 403

    start_str = request.args.get("start")
    end_str = request.args.get("end")
    usuario_id = request.args.get("usuario_id", type=int)
    tipo = request.args.get("tipo")
    search = (request.args.get("search") or "").strip().lower()
    view_mode = request.args.get("view_mode", "calendar")  # calendar ou table
    page = max(1, request.args.get("page", 1, type=int))
    per_page = request.args.get("per_page", 20, type=int)

    query = CommercialAgendaEntry.query.options(joinedload(CommercialAgendaEntry.consultor))

    if usuario_id:
        query = query.filter(CommercialAgendaEntry.usuario_id == usuario_id)

    if tipo and tipo in TIPO_COMPROMISSO_CHOICES:
        query = query.filter(CommercialAgendaEntry.tipo_compromisso == tipo)

    if search:
        query = query.filter(
            or_(
                CommercialAgendaEntry.cliente.ilike(f"%{search}%"),
                CommercialAgendaEntry.local.ilike(f"%{search}%"),
                CommercialAgendaEntry.observacoes.ilike(f"%{search}%"),
                CommercialAgendaEntry.consultor.has(User.nome_completo.ilike(f"%{search}%")),
            )
        )

    # Filtro de datas para FullCalendar
    if start_str and end_str and view_mode == "calendar":
        try:
            start_date = datetime.fromisoformat(start_str[:10]).date()
            end_date = datetime.fromisoformat(end_str[:10]).date()
            query = query.filter(
                CommercialAgendaEntry.data_inicio <= end_date,
                or_(
                    CommercialAgendaEntry.data_fim.is_(None),
                    CommercialAgendaEntry.data_fim >= start_date,
                ),
            )
        except Exception:
            pass

    query = query.order_by(CommercialAgendaEntry.data_inicio.desc(), CommercialAgendaEntry.id.desc())

    if view_mode == "table":
        total = query.count()
        entries = query.offset((page - 1) * per_page).limit(per_page).all()
        items = []
        for e in entries:
            tipo_meta = TIPO_COMPROMISSO_CHOICES.get(e.tipo_compromisso, TIPO_COMPROMISSO_CHOICES["outro"])
            status_meta = STATUS_CHOICES.get(e.status, STATUS_CHOICES["agendado"])
            item = e.to_dict()
            item["tipo_label"] = tipo_meta["label"]
            item["tipo_color"] = tipo_meta["color"]
            item["tipo_badge_class"] = tipo_meta["badge_class"]
            item["status_label"] = status_meta["label"]
            item["status_badge_class"] = status_meta["badge_class"]
            item["can_edit"] = _is_manager() or e.usuario_id == current_user.id
            items.append(item)

        total_pages = (total + per_page - 1) // per_page if per_page else 1
        return jsonify({
            "items": items,
            "total": total,
            "page": page,
            "pages": total_pages,
        })

    # Modo Calendário (FullCalendar format)
    entries = query.limit(500).all()
    events = []
    for e in entries:
        tipo_meta = TIPO_COMPROMISSO_CHOICES.get(e.tipo_compromisso, TIPO_COMPROMISSO_CHOICES["outro"])
        consultor_nome = e.consultor.nome_completo.split()[0] if (e.consultor and e.consultor.nome_completo) else f"Usuário {e.usuario_id}"
        title = f"{consultor_nome}: {e.cliente or tipo_meta['label']}"
        if e.periodo and e.periodo != "Dia todo":
            title = f"[{e.periodo}] {title}"

        end_val = None
        if e.data_fim and e.data_fim > e.data_inicio:
            end_val = (e.data_fim + timedelta(days=1)).isoformat()
        elif e.data_fim:
            end_val = e.data_fim.isoformat()
        else:
            end_val = e.data_inicio.isoformat()

        events.append({
            "id": str(e.id),
            "title": title,
            "start": e.data_inicio.isoformat(),
            "end": end_val,
            "allDay": True,
            "backgroundColor": tipo_meta["color"],
            "borderColor": tipo_meta["color"],
            "textColor": "#ffffff" if e.tipo_compromisso not in ["atividade_externa", "ferias"] else "#000000",
            "extendedProps": {
                **e.to_dict(),
                "tipo_label": tipo_meta["label"],
                "tipo_badge_class": tipo_meta["badge_class"],
                "status_label": STATUS_CHOICES.get(e.status, {}).get("label", e.status),
                "can_edit": _is_manager() or e.usuario_id == current_user.id,
            },
        })

    return jsonify(events)


@propostas_bp.route("/comercial/agenda/novo", methods=["POST"])
@login_required
def agenda_comercial_novo():
    if not _can_access_agenda():
        flash("Permissão negada.", "danger")
        return redirect(url_for("home"))

    usuario_id = request.form.get("usuario_id", type=int)
    if not _is_manager() or not usuario_id:
        usuario_id = current_user.id

    tipo_compromisso = (request.form.get("tipo_compromisso") or "visita").strip().lower()
    cliente = (request.form.get("cliente") or "").strip()
    local = (request.form.get("local") or "").strip()
    data_inicio_raw = (request.form.get("data_inicio") or "").strip()
    data_fim_raw = (request.form.get("data_fim") or "").strip()
    periodo = (request.form.get("periodo") or "Dia todo").strip()
    status = (request.form.get("status") or "agendado").strip().lower()
    observacoes = (request.form.get("observacoes") or "").strip()

    if not data_inicio_raw:
        flash("A data de início é obrigatória.", "warning")
        return redirect(url_for("propostas_bp.agenda_comercial"))

    try:
        data_inicio = datetime.strptime(data_inicio_raw, "%Y-%m-%d").date()
    except ValueError:
        flash("Data de início em formato inválido.", "warning")
        return redirect(url_for("propostas_bp.agenda_comercial"))

    data_fim = None
    if data_fim_raw:
        try:
            data_fim = datetime.strptime(data_fim_raw, "%Y-%m-%d").date()
            if data_fim < data_inicio:
                data_fim = data_inicio
        except ValueError:
            data_fim = None

    try:
        entry = CommercialAgendaEntry(
            usuario_id=usuario_id,
            tipo_compromisso=tipo_compromisso,
            cliente=cliente,
            local=local,
            data_inicio=data_inicio,
            data_fim=data_fim,
            periodo=periodo,
            status=status,
            observacoes=observacoes,
        )
        db.session.add(entry)
        db.session.commit()

        write_audit(
            entity_type="CommercialAgendaEntry",
            entity_id=entry.id,
            action="create",
            message=f"Compromisso comercial ({tipo_compromisso}) criado para usuário ID {usuario_id} em {data_inicio}.",
            after=entry.to_dict(),
            commit=True,
        )
        flash("Compromisso registrado com sucesso na agenda comercial.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao criar compromisso comercial")
        flash("Erro interno ao gravar agendamento.", "danger")

    return redirect(url_for("propostas_bp.agenda_comercial"))


@propostas_bp.route("/comercial/agenda/<int:entry_id>/editar", methods=["POST"])
@login_required
def agenda_comercial_editar(entry_id: int):
    if not _can_access_agenda():
        flash("Permissão negada.", "danger")
        return redirect(url_for("home"))

    entry = CommercialAgendaEntry.query.get_or_404(entry_id)
    if not _is_manager() and entry.usuario_id != current_user.id:
        flash("Você só pode editar compromissos da sua própria agenda.", "danger")
        return redirect(url_for("propostas_bp.agenda_comercial"))

    if _is_manager() and request.form.get("usuario_id"):
        entry.usuario_id = request.form.get("usuario_id", type=int)

    entry.tipo_compromisso = (request.form.get("tipo_compromisso") or entry.tipo_compromisso).strip().lower()
    entry.cliente = (request.form.get("cliente") or "").strip()
    entry.local = (request.form.get("local") or "").strip()
    entry.periodo = (request.form.get("periodo") or "Dia todo").strip()
    entry.status = (request.form.get("status") or entry.status).strip().lower()
    entry.observacoes = (request.form.get("observacoes") or "").strip()

    data_inicio_raw = (request.form.get("data_inicio") or "").strip()
    if data_inicio_raw:
        try:
            entry.data_inicio = datetime.strptime(data_inicio_raw, "%Y-%m-%d").date()
        except ValueError:
            pass

    data_fim_raw = (request.form.get("data_fim") or "").strip()
    if data_fim_raw:
        try:
            data_fim = datetime.strptime(data_fim_raw, "%Y-%m-%d").date()
            if data_fim >= entry.data_inicio:
                entry.data_fim = data_fim
            else:
                entry.data_fim = entry.data_inicio
        except ValueError:
            entry.data_fim = None
    else:
        entry.data_fim = None

    try:
        db.session.commit()
        write_audit(
            entity_type="CommercialAgendaEntry",
            entity_id=entry.id,
            action="update",
            message=f"Compromisso comercial #{entry.id} atualizado.",
            after=entry.to_dict(),
            commit=True,
        )
        flash("Compromisso atualizado com sucesso.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao editar compromisso comercial")
        flash("Erro ao salvar alterações do compromisso.", "danger")

    return redirect(url_for("propostas_bp.agenda_comercial"))


@propostas_bp.route("/comercial/agenda/<int:entry_id>/status", methods=["POST"])
@login_required
def agenda_comercial_status(entry_id: int):
    if not _can_access_agenda():
        return jsonify({"success": False, "message": "Acesso não autorizado."}), 403

    entry = CommercialAgendaEntry.query.get_or_404(entry_id)
    if not _is_manager() and entry.usuario_id != current_user.id:
        return jsonify({"success": False, "message": "Sem permissão para alterar este compromisso."}), 403

    novo_status = (request.form.get("status") or "").strip().lower()
    if novo_status not in STATUS_CHOICES:
        return jsonify({"success": False, "message": "Status inválido."}), 400

    try:
        entry.status = novo_status
        db.session.commit()
        write_audit(
            entity_type="CommercialAgendaEntry",
            entity_id=entry.id,
            action="update_status",
            message=f"Status do compromisso #{entry.id} alterado para {novo_status}.",
            commit=True,
        )
        return jsonify({"success": True, "status": novo_status, "label": STATUS_CHOICES[novo_status]["label"]})
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"success": False, "message": "Erro ao atualizar status."}), 500


@propostas_bp.route("/comercial/agenda/<int:entry_id>/excluir", methods=["POST"])
@login_required
def agenda_comercial_excluir(entry_id: int):
    if not _can_access_agenda():
        flash("Permissão negada.", "danger")
        return redirect(url_for("home"))

    entry = CommercialAgendaEntry.query.get_or_404(entry_id)
    if not _is_manager() and entry.usuario_id != current_user.id:
        flash("Você só pode excluir compromissos da sua própria agenda.", "danger")
        return redirect(url_for("propostas_bp.agenda_comercial"))

    try:
        payload_before = entry.to_dict()
        db.session.delete(entry)
        db.session.commit()

        write_audit(
            entity_type="CommercialAgendaEntry",
            entity_id=entry_id,
            action="delete",
            message=f"Compromisso comercial #{entry_id} excluído.",
            before=payload_before,
            commit=True,
        )
        flash("Compromisso excluído da agenda.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao excluir compromisso comercial")
        flash("Erro ao excluir compromisso.", "danger")

    return redirect(url_for("propostas_bp.agenda_comercial"))
