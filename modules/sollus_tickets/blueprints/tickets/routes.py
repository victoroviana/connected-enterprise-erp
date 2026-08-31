from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import abort, current_app, flash, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from extensions import db
from modules.propostas.blueprints.auth.permissions_utils import normalize_role_key, raw_permissions, current_permissions

from utils.helpers import (
    wants_json as _wants_json,
)

from ...importer import import_osticket, import_osticket_attachments, import_osticket_mailboxes, import_osticket_settings, parse_ost_config
from ...email_ingest import sync_enabled_mailboxes, sync_mailbox
from ...models import (
    SollusTicket,
    SollusTicketAttachment,
    SollusTicketBanlist,
    SollusTicketCannedResponse,
    SollusTicketCollaborator,
    SollusTicketCustomQueueColumn,
    SollusTicketCustomQueueSort,
    SollusTicketContact,
    SollusTicketDepartmentAccess,
    SollusTicketDepartment,
    SollusTicketEmailTemplate,
    SollusTicketEmailTemplateGroup,
    SollusTicketFieldValue,
    SollusTicketFilterRule,
    SollusTicketFormField,
    SollusTicketImportRun,
    SollusTicketMailbox,
    SollusTicketPriority,
    SollusTicketQueue,
    SollusTicketRolePermission,
    SollusTicketSLA,
    SollusTicketStatus,
    SollusTicketSystemLog,
    SollusTicketTask,
    SollusTicketTeam,
    SollusTicketTeamMember,
    SollusTicketTopic,
    SollusTicketLock,
)
from ...advanced import (
    acquire_ticket_lock,
    add_task_entry,
    advanced_report,
    close_task,
    create_task,
    link_tickets,
    merge_ticket,
    release_ticket_lock,
    transfer_ticket,
    unlink_tickets,
)
from ...services import (
    add_thread_entry,
    agents_query,
    assign_ticket,
    create_ticket,
    permission_for_user,
    priority_map,
    save_ticket_attachment,
    status_map,
    ticket_visible_query,
    update_status,
    update_sla_overdue,
    slugify,
)
from ...ticket_mailer import _render_template_str
from . import sollus_tickets_bp




def _deny_access():
    from flask import request, jsonify
    if "/api/" in getattr(request, "path", "") or _wants_json():
        return jsonify({"error": "Access denied", "success": False, "message": "Sem permissão para Sollus Tickets."}), 403
    flash("Você não tem permissão para acessar o Sollus Tickets.", "warning")
    return redirect(url_for("sem_permissao", area="Sollus Tickets"))


def _is_staff() -> bool:
    role_key = normalize_role_key(
        getattr(current_user, "tipo", None)
        or getattr(current_user, "role", None)
        or session.get("tipo")
    )
    return role_key in {"admin", "gestor", "agent"}


def _can_manage() -> bool:
    return bool(permission_for_user(current_user).can_manage_admin or current_permissions().get("chamados"))


def _can_assign() -> bool:
    return bool(permission_for_user(current_user).can_assign or _can_manage())


def _can_close() -> bool:
    return bool(permission_for_user(current_user).can_close or _can_manage())


def _can_reopen() -> bool:
    return bool(permission_for_user(current_user).can_reopen or _can_manage())


def _can_transfer() -> bool:
    return bool(getattr(permission_for_user(current_user), "can_transfer", False) or _can_manage())


def _can_merge() -> bool:
    return bool(getattr(permission_for_user(current_user), "can_merge", False) or _can_manage())


def _can_link() -> bool:
    return bool(getattr(permission_for_user(current_user), "can_link", False) or _can_manage())


def _can_tasks() -> bool:
    return bool(getattr(permission_for_user(current_user), "can_manage_tasks", False) or _can_manage())


def _can_delete() -> bool:
    return bool(getattr(permission_for_user(current_user), "can_delete", False) or _can_manage())


def _can_internal_note() -> bool:
    return bool(getattr(permission_for_user(current_user), "can_internal_note", False) or _can_manage())


def _ensure_editable(ticket: SollusTicket) -> None:
    lock = SollusTicketLock.query.filter_by(ticket_id=ticket.id).first()
    if lock and lock.expires_at and lock.expires_at > datetime.utcnow() and lock.user_id != current_user.id:
        abort(409)


def _can_use_tickets() -> bool:
    perm = permission_for_user(current_user)
    if _can_manage() or perm.can_view_all or perm.can_assign or perm.can_close or perm.can_reopen:
        return True
    if SollusTicketDepartmentAccess.query.filter_by(user_id=current_user.id).first():
        return True
    if SollusTicketTeamMember.query.filter_by(user_id=current_user.id).first():
        return True
    return bool(current_permissions().get("chamados"))


@sollus_tickets_bp.before_request
def _check_access():
    from flask import request, jsonify
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
    if _can_use_tickets():
        return
    return _deny_access()


@sollus_tickets_bp.route("/", endpoint="dashboard")
@login_required
def dashboard():
    update_sla_overdue()
    query = ticket_visible_query(current_user)
    search = (request.args.get("q") or "").strip()
    status_raw = request.args.get("status")
    if status_raw is None:
        status = "open"
    else:
        status = status_raw.strip()
    department_id = (request.args.get("department_id") or "").strip()
    priority_key = (request.args.get("priority_key") or "").strip()
    assignee_id = (request.args.get("assignee_id") or "").strip()
    team_id = (request.args.get("team_id") or "").strip()
    queue_id = (request.args.get("queue_id") or "").strip()
    overdue = (request.args.get("overdue") or "").strip()
    created_from = (request.args.get("created_from") or "").strip()
    created_to = (request.args.get("created_to") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 10

    if search:
        like = f"%{search}%"
        from ...models import SollusTicketContact, SollusTicketThreadEntry
        contact_ids = (
            db.session.query(SollusTicketContact.id)
            .filter(or_(
                SollusTicketContact.name.ilike(like),
                SollusTicketContact.email.ilike(like),
            ))
            .subquery()
        )
        thread_ticket_ids = (
            db.session.query(SollusTicketThreadEntry.ticket_id)
            .filter(SollusTicketThreadEntry.body.ilike(like))
            .subquery()
        )
        query = query.filter(or_(
            SollusTicket.subject.ilike(like),
            SollusTicket.number.ilike(like),
            SollusTicket.contact_id.in_(contact_ids),
            SollusTicket.id.in_(thread_ticket_ids),
        ))
    if status:
        # Treat 'open' as the full open-group and 'closed' as closed-group
        if status == "open":
            query = query.filter(SollusTicket.status_key.in_(("open", "in_progress", "waiting_user")))
        elif status == "closed":
            query = query.filter(SollusTicket.status_key.in_(("closed", "resolved")))
        else:
            query = query.filter(SollusTicket.status_key == status)
    if department_id.isdigit():
        query = query.filter(SollusTicket.department_id == int(department_id))
    if priority_key:
        query = query.filter(SollusTicket.priority_key == priority_key)
    if assignee_id.isdigit():
        query = query.filter(SollusTicket.assignee_id == int(assignee_id))
    elif assignee_id == "none":
        query = query.filter(SollusTicket.assignee_id.is_(None))
    if team_id.isdigit():
        query = query.filter(SollusTicket.team_id == int(team_id))
    if queue_id.isdigit():
        query = query.filter(SollusTicket.queue_id == int(queue_id))
    if overdue == "1":
        query = query.filter(SollusTicket.overdue_at.isnot(None))
    if created_from:
        query = query.filter(SollusTicket.created_at >= created_from)
    if created_to:
        query = query.filter(SollusTicket.created_at <= f"{created_to} 23:59:59")

    custom_columns = []
    custom_sorts = []
    if queue_id.isdigit():
        selected_queue_id = int(queue_id)
        custom_columns = (
            SollusTicketCustomQueueColumn.query.filter_by(queue_id=selected_queue_id, is_visible=True)
            .order_by(SollusTicketCustomQueueColumn.sort_order, SollusTicketCustomQueueColumn.id)
            .all()
        )
        custom_sorts = (
            SollusTicketCustomQueueSort.query.filter_by(queue_id=selected_queue_id)
            .order_by(SollusTicketCustomQueueSort.sort_order, SollusTicketCustomQueueSort.id)
            .all()
        )
    for sort in custom_sorts:
        column = getattr(SollusTicket, sort.field_key, None)
        if column is not None:
            query = query.order_by(column.asc() if sort.direction == "asc" else column.desc())
    if not custom_sorts:
        query = query.order_by(SollusTicket.updated_at.desc())

    total_count = query.count()
    tickets = query.offset((page - 1) * per_page).limit(per_page).all()
    statuses = status_map()
    priorities = priority_map()
    departments = SollusTicketDepartment.query.order_by(SollusTicketDepartment.name.asc()).all()
    # Otimização: Agregações diretas no banco de dados para evitar carregar objetos em memória
    counts = {
        "open": ticket_visible_query(current_user).filter(SollusTicket.status_key.in_(("open", "in_progress", "waiting_user"))).with_entities(func.count(SollusTicket.id)).scalar() or 0,
        "closed": ticket_visible_query(current_user).filter(SollusTicket.status_key.in_(("closed", "resolved"))).with_entities(func.count(SollusTicket.id)).scalar() or 0,
        "unassigned": ticket_visible_query(current_user).filter(SollusTicket.assignee_id.is_(None)).with_entities(func.count(SollusTicket.id)).scalar() or 0,
        "total": ticket_visible_query(current_user).with_entities(func.count(SollusTicket.id)).scalar() or 0,
    }
    
    # Hero stats with colors for the premium layout
    hero_stats = [
        {"label": "Total", "value": counts["total"], "icon": "bi-collection", "bg": "rgba(14, 165, 233, 0.1)", "color": "#0ea5e9"},
        {"label": "Em aberto", "value": counts["open"], "icon": "bi-envelope-paper", "bg": "rgba(99, 102, 241, 0.1)", "color": "#6366f1"},
        {"label": "Sem atendente", "value": counts["unassigned"], "icon": "bi-person-dash", "bg": "rgba(139, 92, 246, 0.1)", "color": "#8b5cf6"},
        {"label": "Fechados", "value": counts["closed"], "icon": "bi-check2-all", "bg": "rgba(34, 197, 94, 0.1)", "color": "#22c55e"},
    ]
    return render_template(
        "sollus_tickets/dashboard.html",
        tickets=tickets,
        statuses=statuses,
        priorities=priorities,
        departments=departments,
        teams=SollusTicketTeam.query.filter_by(is_active=True).order_by(SollusTicketTeam.name).all(),
        queues=SollusTicketQueue.query.filter_by(is_active=True).order_by(SollusTicketQueue.sort_order, SollusTicketQueue.name).all(),
        agents=agents_query(),
        custom_columns=custom_columns,
        counts=counts,
        filters={
            "q": search,
            "status": status,
            "department_id": department_id,
            "priority_key": priority_key,
            "assignee_id": assignee_id,
            "team_id": team_id,
            "queue_id": queue_id,
            "overdue": overdue,
            "created_from": created_from,
            "created_to": created_to,
        },
        pagination={
            "page": page,
            "per_page": per_page,
            "total": total_count,
            "pages": (total_count + per_page - 1) // per_page,
        }
    )


@sollus_tickets_bp.route("/novo", methods=["GET"], endpoint="new_ticket")
@login_required
def new_ticket():
    return render_template(
        "sollus_tickets/new.html",
        departments=SollusTicketDepartment.query.filter_by(is_active=True).order_by(SollusTicketDepartment.name).all(),
        topics=SollusTicketTopic.query.filter_by(is_active=True).order_by(SollusTicketTopic.name).all(),
        priorities=SollusTicketPriority.query.order_by(SollusTicketPriority.level).all(),
        queues=SollusTicketQueue.query.filter_by(is_active=True).order_by(SollusTicketQueue.sort_order, SollusTicketQueue.name).all(),
        teams=SollusTicketTeam.query.filter_by(is_active=True).order_by(SollusTicketTeam.name).all(),
        slas=SollusTicketSLA.query.filter_by(is_active=True).order_by(SollusTicketSLA.name).all(),
        fields=SollusTicketFormField.query.filter_by(is_active=True).order_by(SollusTicketFormField.sort_order, SollusTicketFormField.label).all(),
    )


@sollus_tickets_bp.route("/criar", methods=["POST"], endpoint="create_ticket")
@login_required
def create_ticket_route():
    subject = (request.form.get("subject") or "").strip()
    body = (request.form.get("body") or "").strip()
    if not subject or not body:
        flash("Informe assunto e descricao.", "warning")
        return redirect(url_for("sollus_tickets.new_ticket"))

    department_id = _as_int(request.form.get("department_id"))
    topic_id = _as_int(request.form.get("topic_id"))
    queue_id = _as_int(request.form.get("queue_id"))
    team_id = _as_int(request.form.get("team_id"))
    sla_id = _as_int(request.form.get("sla_id"))
    priority_key = (request.form.get("priority_key") or "normal").strip()
    valid_priorities = {item.key for item in SollusTicketPriority.query.all()}
    if priority_key not in valid_priorities:
        priority_key = "normal"

    field_values = {}
    for field in SollusTicketFormField.query.filter_by(is_active=True).all():
        value = (request.form.get(f"field_{field.id}") or "").strip()
        if field.required and not value:
            flash(f"Preencha o campo obrigatorio: {field.label}.", "warning")
            return redirect(url_for("sollus_tickets.new_ticket"))
        if value:
            field_values[field.id] = value

    ticket = create_ticket(
        subject=subject,
        body=body,
        requester_id=current_user.id,
        department_id=department_id,
        topic_id=topic_id,
        queue_id=queue_id,
        team_id=team_id,
        sla_id=sla_id,
        priority_key=priority_key,
        field_values=field_values,
        notify=False,
    )
    # Associa os anexos à entrada inicial do ticket
    initial_entry = ticket.entries[0] if ticket.entries else None
    for uploaded in request.files.getlist("attachments"):
        if uploaded and uploaded.filename:
            try:
                save_ticket_attachment(ticket, uploaded, entry=initial_entry, uploader_id=current_user.id)
            except ValueError as exc:
                flash(str(exc), "warning")
    
    # Envia e-mail de notificação de ticket criado após os anexos estarem vinculados
    from modules.sollus_tickets.services import notify_ticket
    notify_ticket(ticket, "created", body, initial_entry)

    flash("Ticket criado com sucesso.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/<int:ticket_id>", endpoint="detail")
@login_required
def detail(ticket_id: int):
    ticket = ticket_visible_query(current_user).filter(SollusTicket.id == ticket_id).first_or_404()
    lock_ok, lock = acquire_ticket_lock(ticket, current_user, purpose="view", minutes=10)
    return render_template(
        "sollus_tickets/detail.html",
        ticket=ticket,
        ticket_lock=lock,
        lock_ok=lock_ok,
        agents=agents_query(department_id=ticket.department_id),
        all_agents=agents_query(),
        department_access=SollusTicketDepartmentAccess.query.all(),
        team_members=SollusTicketTeamMember.query.all(),
        statuses=SollusTicketStatus.query.order_by(SollusTicketStatus.sort_order).all(),
        priorities=priority_map(),
        departments=SollusTicketDepartment.query.filter_by(is_active=True).order_by(SollusTicketDepartment.name).all(),
        teams=SollusTicketTeam.query.filter_by(is_active=True).order_by(SollusTicketTeam.name).all(),
        queues=SollusTicketQueue.query.filter_by(is_active=True).order_by(SollusTicketQueue.sort_order, SollusTicketQueue.name).all(),
        canned_responses=SollusTicketCannedResponse.query.filter_by(is_active=True).order_by(SollusTicketCannedResponse.title).all(),
        can_manage=_can_manage(),
        can_assign=_can_assign(),
        can_close=_can_close(),
        can_reopen=_can_reopen(),
        can_transfer=_can_transfer(),
        can_merge=_can_merge(),
        can_link=_can_link(),
        can_tasks=_can_tasks(),
        can_delete=_can_delete(),
        can_internal_note=_can_internal_note(),
    )


@sollus_tickets_bp.route("/<int:ticket_id>/responder", methods=["POST"], endpoint="reply")
@login_required
def reply(ticket_id: int):
    ticket = ticket_visible_query(current_user).filter(SollusTicket.id == ticket_id).first_or_404()
    _ensure_editable(ticket)
    body = (request.form.get("body") or "").strip()
    visibility = (request.form.get("visibility") or "public").strip()
    entry_type = "note" if visibility == "internal" else "reply"
    if not body:
        flash("Escreva uma resposta.", "warning")
        return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))
    if visibility == "internal" and not _can_internal_note():
        abort(403)
    entry = add_thread_entry(ticket, body=body, actor_id=current_user.id, entry_type=entry_type, visibility=visibility, notify=False)
    
    # Salva arquivos anexados à resposta, se houver
    for uploaded in request.files.getlist("attachments"):
        if uploaded and uploaded.filename:
            try:
                save_ticket_attachment(ticket, uploaded, entry=entry, uploader_id=current_user.id)
            except ValueError as exc:
                flash(f"{uploaded.filename}: {str(exc)}", "warning")

    if visibility == "public":
        from modules.sollus_tickets.services import notify_ticket
        notify_ticket(ticket, "reply", body, entry)

    flash("Interacao registrada.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/<int:ticket_id>/upload-anexo", methods=["POST"], endpoint="direct_upload")
@login_required
def direct_upload(ticket_id: int):
    ticket = ticket_visible_query(current_user).filter(SollusTicket.id == ticket_id).first_or_404()
    _ensure_editable(ticket)

    uploaded_files = request.files.getlist("attachments")
    success_count = 0
    error_messages = []
    # Associa ao último entry do ticket, se existir
    last_entry = ticket.entries[-1] if ticket.entries else None

    for uploaded in uploaded_files:
        if uploaded and uploaded.filename:
            try:
                save_ticket_attachment(ticket, uploaded, entry=last_entry, uploader_id=current_user.id)
                success_count += 1
            except ValueError as exc:
                error_messages.append(f"{uploaded.filename}: {str(exc)}")

    if success_count > 0:
        flash(f"{success_count} anexo(s) enviado(s) com sucesso.", "success")
    for msg in error_messages:
        flash(msg, "warning")

    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/<int:ticket_id>/entrada/<int:entry_id>/editar", methods=["POST"], endpoint="edit_entry")
@login_required
def edit_entry(ticket_id: int, entry_id: int):
    """Edita o texto de uma entrada já enviada no thread do ticket.

    Regras:
    - Somente o autor original da entrada OU um usuário com can_manage podem editar.
    - Não é possível editar entradas em tickets fechados.
    - O texto anterior é salvo na tabela de histórico antes de sobrescrever.
    - Novos anexos podem ser adicionados junto com a edição.
    """
    from ...models import SollusTicketThreadEntry, SollusTicketThreadEntryHistory

    ticket = ticket_visible_query(current_user).filter(SollusTicket.id == ticket_id).first_or_404()

    # Bloqueia edição em tickets fechados
    if ticket.is_closed:
        if _wants_json():
            return {"ok": False, "error": "Chamado encerrado. Não é possível editar."}, 403
        flash("Chamado encerrado. Não é possível editar.", "warning")
        return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))

    entry = SollusTicketThreadEntry.query.filter_by(id=entry_id, ticket_id=ticket_id).first_or_404()

    # Controle de permissão: somente o autor original ou um gestor/admin
    is_author = (entry.author_user_id is not None and entry.author_user_id == current_user.id)
    if not is_author and not _can_manage():
        if _wants_json():
            return {"ok": False, "error": "Sem permissão para editar esta mensagem."}, 403
        flash("Sem permissão para editar esta mensagem.", "danger")
        return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))

    new_body = (request.form.get("body") or "").strip()
    if not new_body:
        if _wants_json():
            return {"ok": False, "error": "O texto da mensagem não pode estar vazio."}, 400
        flash("O texto da mensagem não pode estar vazio.", "warning")
        return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))

    # Salva o histórico (texto anterior) antes de modificar
    history = SollusTicketThreadEntryHistory(
        entry_id=entry.id,
        body_before=entry.body,
        edited_by_id=current_user.id,
    )
    db.session.add(history)

    # Atualiza o texto e os metadados de edição
    entry.body = new_body
    entry.edited_at = datetime.utcnow()
    entry.edited_by_id = current_user.id

    # Processa novos anexos enviados junto com a edição
    new_attachments = []
    for uploaded in request.files.getlist("attachments"):
        if uploaded and uploaded.filename:
            try:
                att = save_ticket_attachment(ticket, uploaded, entry=entry, uploader_id=current_user.id)
                new_attachments.append(att)
            except ValueError as exc:
                if _wants_json():
                    db.session.rollback()
                    return {"ok": False, "error": f"{uploaded.filename}: {str(exc)}"}, 400
                flash(f"{uploaded.filename}: {str(exc)}", "warning")

    db.session.commit()

    if entry.visibility == "public":
        from ...services import notify_ticket
        notify_ticket(ticket, "reply", new_body, entry)

    if _wants_json():
        return {
            "ok": True,
            "entry_id": entry.id,
            "body": new_body,
            "edited_at": entry.edited_at.strftime("%d/%m/%Y %H:%M"),
            "editor_name": current_user.name or current_user.email,
            "new_attachments": [
                {
                    "id": a.id,
                    "name": a.original_name,
                    "content_type": a.content_type or "",
                    "download_url": url_for(
                        "sollus_tickets.download_attachment",
                        ticket_id=ticket.id,
                        attachment_id=a.id,
                    ),
                }
                for a in new_attachments
            ],
        }

    flash("Mensagem editada com sucesso.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/<int:ticket_id>/entrada/<int:entry_id>/historico", methods=["GET"], endpoint="entry_history")
@login_required
def entry_history(ticket_id: int, entry_id: int):
    """Retorna o histórico de edições de uma entrada de thread (JSON)."""
    from ...models import SollusTicketThreadEntry, SollusTicketThreadEntryHistory

    ticket = ticket_visible_query(current_user).filter(SollusTicket.id == ticket_id).first_or_404()
    entry = SollusTicketThreadEntry.query.filter_by(id=entry_id, ticket_id=ticket_id).first_or_404()

    history = SollusTicketThreadEntryHistory.query.filter_by(entry_id=entry.id).order_by(
        SollusTicketThreadEntryHistory.created_at.asc()
    ).all()

    return {
        "entry_id": entry.id,
        "current_body": entry.body,
        "history": [
            {
                "id": h.id,
                "body_before": h.body_before,
                "edited_at": h.created_at.strftime("%d/%m/%Y %H:%M"),
                "editor": h.editor.name or h.editor.email if h.editor else "Sistema",
            }
            for h in history
        ],
    }


@sollus_tickets_bp.route("/<int:ticket_id>/excluir", methods=["POST"], endpoint="delete_ticket")
@login_required
def delete_ticket(ticket_id: int):
    """Exclui permanentemente um ticket e todos os seus dados relacionados."""
    if not _can_delete():
        abort(403)
    ticket = SollusTicket.query.get_or_404(ticket_id)
    ticket_number = ticket.number or f"#{ticket.id}"
    try:
        db.session.delete(ticket)
        db.session.commit()
        try:
            from modules.audit.utils import write_audit_external
            write_audit_external(
                entity_type="sollus_ticket",
                action="delete",
                message=f"Ticket {ticket_number} excluído permanentemente.",
            )
        except Exception:
            pass
        flash(f"Ticket {ticket_number} excluído com sucesso.", "success")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Erro ao excluir ticket %s: %s", ticket_id, exc)
        flash(f"Erro ao excluir o ticket: {exc}", "danger")
    return redirect(url_for("sollus_tickets.dashboard"))


@sollus_tickets_bp.route("/<int:ticket_id>/atribuir", methods=["POST"], endpoint="assign")
@login_required
def assign(ticket_id: int):
    if not _can_assign():
        abort(403)
    ticket = SollusTicket.query.get_or_404(ticket_id)
    assign_ticket(ticket, _as_int(request.form.get("assignee_id")), current_user.id)
    flash("Atendente atualizado.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/<int:ticket_id>/status", methods=["POST"], endpoint="status")
@login_required
def status(ticket_id: int):
    ticket = SollusTicket.query.get_or_404(ticket_id)
    status_key = (request.form.get("status_key") or "").strip()
    if not SollusTicketStatus.query.filter_by(key=status_key).first():
        flash("Status invalido.", "warning")
        return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))
    if status_key in {"closed", "resolved"} and not _can_close():
        abort(403)
    if ticket.status_key in {"closed", "resolved"} and status_key not in {"closed", "resolved"} and not _can_reopen():
        abort(403)
    if status_key not in {"closed", "resolved"} and ticket.status_key not in {"closed", "resolved"} and not (_can_close() or _can_reopen() or _can_manage()):
        abort(403)
    update_status(ticket, status_key, current_user.id, request.form.get("reason"))
    flash("Status atualizado.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/<int:ticket_id>/transferir", methods=["POST"], endpoint="transfer")
@login_required
def transfer(ticket_id: int):
    if not _can_transfer():
        abort(403)
    ticket = SollusTicket.query.get_or_404(ticket_id)
    transfer_ticket(
        ticket,
        actor_id=current_user.id,
        department_id=_as_int(request.form.get("department_id")),
        team_id=_as_int(request.form.get("team_id")),
        queue_id=_as_int(request.form.get("queue_id")),
        assignee_id=_as_int(request.form.get("assignee_id")),
        reason=(request.form.get("reason") or "").strip(),
    )
    flash("Ticket transferido.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/<int:ticket_id>/relacionar", methods=["POST"], endpoint="relate")
@login_required
def relate(ticket_id: int):
    ticket = SollusTicket.query.get_or_404(ticket_id)
    target_number = (request.form.get("target") or "").strip()
    target = _find_ticket_by_token(target_number)
    if not target:
        flash("Ticket relacionado nao encontrado.", "warning")
        return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))
    relation_type = (request.form.get("relation_type") or "linked").strip()
    if relation_type == "merged":
        if not _can_merge():
            abort(403)
        merge_ticket(ticket, target, current_user.id)
        flash("Ticket mesclado.", "success")
    else:
        if not _can_link():
            abort(403)
        link_tickets(ticket, target, relation_type, current_user.id)
        flash("Tickets relacionados.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/relacionar/<int:relation_id>/excluir", methods=["POST"], endpoint="unrelate")
@login_required
def unrelate(relation_id: int):
    if not _can_link() and not _can_merge():
        abort(403)
    back_id = request.args.get("back_id")
    try:
        back_id = int(back_id) if back_id else None
    except (TypeError, ValueError):
        back_id = None
    try:
        source_id = unlink_tickets(relation_id, current_user.id)
        flash("Relação desfeita com sucesso.", "success")
        redirect_id = back_id or source_id
        return redirect(url_for("sollus_tickets.detail", ticket_id=redirect_id))
    except Exception as exc:
        flash(str(exc), "danger")
        if back_id:
            return redirect(url_for("sollus_tickets.detail", ticket_id=back_id))
        return redirect(url_for("sollus_tickets.dashboard"))



@sollus_tickets_bp.route("/<int:ticket_id>/tarefas", methods=["POST"], endpoint="create_task")
@login_required
def create_task_route(ticket_id: int):
    if not _can_tasks():
        abort(403)
    ticket = SollusTicket.query.get_or_404(ticket_id)
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("Informe o titulo da tarefa.", "warning")
        return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))
    create_task(
        ticket,
        title=title,
        body=(request.form.get("body") or "").strip(),
        actor_id=current_user.id,
        assignee_id=_as_int(request.form.get("assignee_id")),
        department_id=_as_int(request.form.get("department_id")),
        team_id=_as_int(request.form.get("team_id")),
    )
    flash("Tarefa criada.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/tarefas/<int:task_id>/comentar", methods=["POST"], endpoint="task_entry")
@login_required
def task_entry(task_id: int):
    if not _can_tasks():
        abort(403)
    task = SollusTicketTask.query.get_or_404(task_id)
    body = (request.form.get("body") or "").strip()
    if body:
        add_task_entry(task, body, current_user.id)
    return redirect(url_for("sollus_tickets.detail", ticket_id=task.ticket_id))


@sollus_tickets_bp.route("/tarefas/<int:task_id>/fechar", methods=["POST"], endpoint="close_task")
@login_required
def close_task_route(task_id: int):
    if not _can_tasks():
        abort(403)
    task = SollusTicketTask.query.get_or_404(task_id)
    close_task(task, current_user.id)
    flash("Tarefa fechada.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=task.ticket_id))


@sollus_tickets_bp.route("/tarefas", endpoint="tasks")
@login_required
def tasks():
    if not _can_tasks():
        abort(403)
    status = (request.args.get("status") or "open").strip()
    assignee_id = (request.args.get("assignee_id") or "").strip()
    query = SollusTicketTask.query
    if status:
        query = query.filter(SollusTicketTask.status_key == status)
    if assignee_id.isdigit():
        query = query.filter(SollusTicketTask.assignee_id == int(assignee_id))
    elif assignee_id == "me":
        query = query.filter(SollusTicketTask.assignee_id == current_user.id)
    tasks = query.order_by(SollusTicketTask.updated_at.desc()).limit(300).all()
    return render_template(
        "sollus_tickets/tasks.html",
        tasks=tasks,
        agents=agents_query(),
        filters={"status": status, "assignee_id": assignee_id},
    )


@sollus_tickets_bp.route("/fechados", endpoint="closed_tickets")
@login_required
def closed_tickets():
    page = request.args.get("page", 1, type=int)
    per_page = 10
    query = ticket_visible_query(current_user).filter(
        SollusTicket.status_key.in_(("closed", "resolved"))
    ).order_by(SollusTicket.closed_at.desc(), SollusTicket.updated_at.desc())
    
    total_count = query.count()
    tickets = query.offset((page - 1) * per_page).limit(per_page).all()
    
    return render_template(
        "sollus_tickets/closed.html", 
        tickets=tickets, 
        statuses=status_map(), 
        priorities=priority_map(),
        pagination={
            "page": page,
            "per_page": per_page,
            "total": total_count,
            "pages": (total_count + per_page - 1) // per_page,
        }
    )


@sollus_tickets_bp.route("/relatorios", endpoint="reports")
@login_required
def reports():
    try:
        from datetime import date, timedelta
        start_raw = (request.args.get("start") or "").strip()
        end_raw = (request.args.get("end") or "").strip()
        
        start = _parse_date(start_raw)
        end = _parse_date(end_raw, end_of_day=True)
    
        query = ticket_visible_query(current_user)
        if start:
            query = query.filter(SollusTicket.created_at >= start)
        if end:
            query = query.filter(SollusTicket.created_at <= end)
        status_rows = db.session.query(SollusTicket.status_key, func.count(SollusTicket.id)).group_by(SollusTicket.status_key).all()
        if start or end:
            status_query = db.session.query(SollusTicket.status_key, func.count(SollusTicket.id))
            if start:
                status_query = status_query.filter(SollusTicket.created_at >= start)
            if end:
                status_query = status_query.filter(SollusTicket.created_at <= end)
            status_rows = status_query.group_by(SollusTicket.status_key).all()
        department_rows = (
            db.session.query(SollusTicketDepartment.name, func.count(SollusTicket.id))
            .join(SollusTicket, SollusTicket.department_id == SollusTicketDepartment.id)
            .group_by(SollusTicketDepartment.name)
            .order_by(func.count(SollusTicket.id).desc())
            .all()
        )
        advanced = advanced_report(start=start, end=end)
        dept_lookup = {item.id: item.name for item in SollusTicketDepartment.query.all()}
        agent_lookup = {item.id: (item.name or item.email) for item in agents_query()}
        return render_template(
            "sollus_tickets/reports.html",
            total=query.with_entities(func.count(SollusTicket.id)).scalar() or 0,
            status_rows=status_rows,
            department_rows=department_rows,
            advanced=advanced,
            dept_lookup=dept_lookup,
            agent_lookup=agent_lookup,
            filters={"start": start_raw, "end": end_raw},
            statuses=status_map(),
        )
    except Exception as exc:
        db.session.rollback()
        flash(f"Erro ao gerar relatórios: {exc}", "danger")
        return redirect(url_for("sollus_tickets.dashboard"))


@sollus_tickets_bp.route("/admin/auto-assign", methods=["GET", "POST"], endpoint="auto_assign")
@login_required
def auto_assign():
    if not _can_manage():
        abort(403)
    if request.method == "POST":
        enabled = set(request.form.getlist("department_ids"))
        departments = SollusTicketDepartment.query.all()
        for dept in departments:
            dept.auto_assign_enabled = str(dept.id) in enabled
        db.session.commit()
        from modules.audit.utils import write_audit_external
        write_audit_external(
            entity_type="ticket_admin",
            action="auto_assign",
            message="Configuracao de auto-atribuicao de tickets atualizada."
        )
        flash("Configuracao de auto-atribuicao atualizada.", "success")
        return redirect(url_for("sollus_tickets.auto_assign"))
    return render_template(
        "sollus_tickets/auto_assign.html",
        departments=SollusTicketDepartment.query.order_by(SollusTicketDepartment.name).all(),
    )


@sollus_tickets_bp.route("/admin/importar-osticket", methods=["POST"], endpoint="import_osticket")
@login_required
def import_osticket_route():
    if not _can_manage():
        abort(403)
    config_path = (request.form.get("config_path") or "").strip()
    limit = _as_int(request.form.get("limit"))
    if not config_path:
        flash("Informe o caminho do ost-config.php.", "warning")
        return redirect(url_for("sollus_tickets.auto_assign"))
    config = parse_ost_config(config_path)
    stats = import_osticket(config, limit=limit)
    flash(f"Importacao concluida: {stats.get('tickets', 0)} tickets importados.", "success")
    return redirect(url_for("sollus_tickets.dashboard"))


@sollus_tickets_bp.route("/admin/importar-caixas-osticket", methods=["POST"], endpoint="import_osticket_mailboxes")
@login_required
def import_osticket_mailboxes_route():
    if not _can_manage():
        abort(403)
    config_path = (request.form.get("config_path") or "").strip()
    if not config_path:
        flash("Informe o caminho do ost-config.php.", "warning")
        return redirect(url_for("sollus_tickets.admin_settings"))
    stats = import_osticket_mailboxes(parse_ost_config(config_path))
    flash(f"Caixas importadas: {stats.get('created', 0)} novas, {stats.get('updated', 0)} atualizadas.", "success")
    return redirect(url_for("sollus_tickets.admin_settings"))


@sollus_tickets_bp.route("/admin/importar-configuracoes-osticket", methods=["POST"], endpoint="import_osticket_settings")
@login_required
def import_osticket_settings_route():
    if not _can_manage():
        abort(403)
    config_path = (request.form.get("config_path") or "").strip()
    if not config_path:
        flash("Informe o caminho do ost-config.php.", "warning")
        return redirect(url_for("sollus_tickets.admin_settings"))
    stats = import_osticket_settings(parse_ost_config(config_path))
    flash(f"Configuracoes importadas: {stats.get('templates', 0)} templates, {stats.get('queue_columns', 0)} colunas de fila.", "success")
    return redirect(url_for("sollus_tickets.admin_settings"))


@sollus_tickets_bp.route("/admin/importar-anexos-osticket", methods=["POST"], endpoint="import_osticket_attachments")
@login_required
def import_osticket_attachments_route():
    if not _can_manage():
        abort(403)
    config_path = (request.form.get("config_path") or "").strip()
    limit = _as_int(request.form.get("limit"))
    if not config_path:
        flash("Informe o caminho do ost-config.php.", "warning")
        return redirect(url_for("sollus_tickets.admin_settings"))
    stats = import_osticket_attachments(parse_ost_config(config_path), limit=limit)
    flash(
        f"Anexos importados: {stats.get('attachments', 0)} novos, "
        f"{stats.get('skipped_attachments', 0)} ignorados.",
        "success",
    )
    return redirect(url_for("sollus_tickets.admin_settings"))


@sollus_tickets_bp.route("/admin/importacoes", endpoint="import_runs")
@login_required
def import_runs():
    if not _can_manage():
        abort(403)
    runs = SollusTicketImportRun.query.order_by(SollusTicketImportRun.started_at.desc()).limit(50).all()
    return render_template("sollus_tickets/import_runs.html", runs=runs)


@sollus_tickets_bp.route("/<int:ticket_id>/anexos", methods=["POST"], endpoint="upload_attachment")
@login_required
def upload_attachment(ticket_id: int):
    ticket = ticket_visible_query(current_user).filter(SollusTicket.id == ticket_id).first_or_404()
    files = request.files.getlist("attachments") or request.files.getlist("file")
    if not files:
        flash("Selecione ao menos um arquivo.", "warning")
        return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))
    for uploaded in files:
        if not uploaded or not uploaded.filename:
            continue
        try:
            save_ticket_attachment(ticket, uploaded, uploader_id=current_user.id)
        except ValueError as exc:
            flash(str(exc), "warning")
    flash("Anexos atualizados.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/<int:ticket_id>/anexos/<int:attachment_id>/download", endpoint="download_attachment")
@login_required
def download_attachment(ticket_id: int, attachment_id: int):
    ticket = ticket_visible_query(current_user).filter(SollusTicket.id == ticket_id).first_or_404()
    attachment = SollusTicketAttachment.query.get_or_404(attachment_id)
    if attachment.ticket_id != ticket.id:
        abort(404)
    storage_path = attachment.storage_path
    if not storage_path:
        abort(404)
    uploads_dir = Path(current_app.config.get("UPLOADS_DIR", "uploads")).resolve()
    path = (uploads_dir / storage_path).resolve()
    try:
        path.relative_to(uploads_dir)
    except ValueError:
        abort(404)
    if not path.is_file():
        abort(404)
    mimetype = (attachment.content_type or "").split(";")[0] or "application/octet-stream"
    return send_file(path, as_attachment=True, download_name=attachment.original_name, mimetype=mimetype)


@sollus_tickets_bp.route("/<int:ticket_id>/anexos/<int:attachment_id>/excluir", methods=["POST"], endpoint="delete_attachment")
@login_required
def delete_attachment(ticket_id: int, attachment_id: int):
    if not _can_delete():
        abort(403)
    ticket = SollusTicket.query.get_or_404(ticket_id)
    attachment = SollusTicketAttachment.query.get_or_404(attachment_id)
    if attachment.ticket_id != ticket.id:
        abort(404)
    storage_path = attachment.storage_path
    if storage_path:
        uploads_dir = Path(current_app.config.get("UPLOADS_DIR", "uploads")).resolve()
        path = (uploads_dir / storage_path).resolve()
        try:
            path.relative_to(uploads_dir)
            if path.is_file():
                path.unlink(missing_ok=True)
        except ValueError:
            pass
    db.session.delete(attachment)
    db.session.commit()
    from modules.audit.utils import write_audit_external
    write_audit_external(
        entity_type="ticket",
        action="delete_attachment",
        entity_id=ticket_id,
        before={"attachment_id": attachment_id, "name": attachment.original_name},
        message=f"Anexo {attachment.original_name} removido do ticket #{ticket_id}."
    )
    flash("Anexo removido.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/<int:ticket_id>/colaboradores", methods=["POST"], endpoint="add_collaborator")
@login_required
def add_collaborator(ticket_id: int):
    if not _can_manage():
        abort(403)
    ticket = SollusTicket.query.get_or_404(ticket_id)
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    if not email:
        flash("Informe o e-mail do colaborador.", "warning")
        return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))
    contact = SollusTicketContact.query.filter_by(email=email).first()
    if not contact:
        contact = SollusTicketContact(name=name or email, email=email)
        db.session.add(contact)
        db.session.flush()
    if not SollusTicketCollaborator.query.filter_by(ticket_id=ticket.id, contact_id=contact.id).first():
        db.session.add(SollusTicketCollaborator(ticket_id=ticket.id, contact_id=contact.id))
    db.session.commit()
    from modules.audit.utils import write_audit_external
    write_audit_external(
        entity_type="ticket",
        action="add_collaborator",
        entity_id=ticket.id,
        after={"collaborator_email": email},
        message=f"Colaborador {email} adicionado ao ticket {ticket.number or ticket.id}."
    )
    flash("Colaborador adicionado.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket.id))


@sollus_tickets_bp.route("/<int:ticket_id>/colaboradores/<int:collaborator_id>/excluir", methods=["POST"], endpoint="delete_collaborator")
@login_required
def delete_collaborator(ticket_id: int, collaborator_id: int):
    if not _can_delete():
        abort(403)
    collaborator = SollusTicketCollaborator.query.get_or_404(collaborator_id)
    if collaborator.ticket_id != ticket_id:
        abort(404)
    db.session.delete(collaborator)
    db.session.commit()
    from modules.audit.utils import write_audit_external
    write_audit_external(
        entity_type="ticket",
        action="delete_collaborator",
        entity_id=ticket_id,
        before={"collaborator_id": collaborator_id},
        message=f"Colaborador #{collaborator_id} removido do ticket #{ticket_id}."
    )
    flash("Colaborador removido.", "success")
    return redirect(url_for("sollus_tickets.detail", ticket_id=ticket_id))






@sollus_tickets_bp.route("/admin/configuracoes", methods=["GET", "POST"], endpoint="admin_settings")
@login_required
def admin_settings():
    if not _can_manage():
        abort(403)
    if request.method == "POST":
        try:
            action = request.form.get("action")
            if action == "department":
                _upsert_department()
            elif action == "team":
                _upsert_team()
            elif action == "queue":
                _upsert_queue()
            elif action == "sla":
                _upsert_sla()
            elif action == "topic":
                _upsert_topic()
            elif action == "field":
                _upsert_field()
            elif action == "canned":
                _upsert_canned()
            elif action == "role_permission":
                _upsert_role_permission()
            elif action == "mailbox":
                _upsert_mailbox()
            elif action == "banlist":
                _upsert_banlist()
            elif action == "filter_rule":
                _upsert_filter_rule()
            elif action == "template":
                _upsert_template()
            elif action == "department_access":
                _upsert_department_access()
            elif action == "queue_column":
                _upsert_queue_column()
            elif action == "queue_sort":
                _upsert_queue_sort()
            elif action == "delete":
                _delete_record()
            flash("Configuração salva.", "success")
            from modules.audit.utils import write_audit_external
            write_audit_external(
                entity_type="ticket_admin",
                action=action or "save",
                message=f"Alteracao de configuracao de administracao de tickets: {action}."
            )
        except Exception as exc:
            db.session.rollback()
            flash(f"Erro ao salvar configuração: {exc}", "danger")
        return redirect(url_for("sollus_tickets.admin_settings"))
        
    try:
        from modules.propostas.models import User
        all_active_users = User.query.filter(User.is_active.is_(True)).order_by(User.nome_completo.asc()).all()
        return render_template(
            "sollus_tickets/admin_settings.html",
            departments=SollusTicketDepartment.query.order_by(SollusTicketDepartment.name).all(),
            teams=SollusTicketTeam.query.order_by(SollusTicketTeam.name).all(),
            queues=SollusTicketQueue.query.order_by(SollusTicketQueue.sort_order, SollusTicketQueue.name).all(),
            slas=SollusTicketSLA.query.order_by(SollusTicketSLA.name).all(),
            topics=SollusTicketTopic.query.order_by(SollusTicketTopic.name).all(),
            fields=SollusTicketFormField.query.order_by(SollusTicketFormField.sort_order, SollusTicketFormField.label).all(),
            canned=SollusTicketCannedResponse.query.order_by(SollusTicketCannedResponse.title).all(),
            role_permissions=SollusTicketRolePermission.query.order_by(SollusTicketRolePermission.role_key).all(),
            mailboxes=SollusTicketMailbox.query.order_by(SollusTicketMailbox.email).all(),
            banlist=SollusTicketBanlist.query.order_by(SollusTicketBanlist.value).all(),
            filter_rules=SollusTicketFilterRule.query.order_by(SollusTicketFilterRule.sort_order, SollusTicketFilterRule.name).all(),
            template_groups=SollusTicketEmailTemplateGroup.query.order_by(SollusTicketEmailTemplateGroup.name).all(),
            templates=SollusTicketEmailTemplate.query.order_by(SollusTicketEmailTemplate.event_key).all(),
            department_access=SollusTicketDepartmentAccess.query.order_by(SollusTicketDepartmentAccess.department_id, SollusTicketDepartmentAccess.user_id).all(),
            queue_columns=SollusTicketCustomQueueColumn.query.order_by(SollusTicketCustomQueueColumn.queue_id, SollusTicketCustomQueueColumn.sort_order).all(),
            queue_sorts=SollusTicketCustomQueueSort.query.order_by(SollusTicketCustomQueueSort.queue_id, SollusTicketCustomQueueSort.sort_order).all(),
            agents=all_active_users,
            system_logs=SollusTicketSystemLog.query.order_by(SollusTicketSystemLog.created_at.desc()).limit(50).all(),
        )
    except Exception as exc:
        db.session.rollback()
        flash(f"Erro crítico ao carregar página de administração: {exc}", "danger")
        return redirect(url_for("sollus_tickets.dashboard"))


@sollus_tickets_bp.route("/admin/caixas-email/sincronizar", methods=["POST"], endpoint="sync_mailboxes")
@login_required
def sync_mailboxes_route():
    if not _can_manage():
        abort(403)
    stats = sync_enabled_mailboxes(limit=_as_int(request.form.get("limit")), force=True)
    flash(
        f"Sincronizacao concluida: {stats.get('created', 0)} criados, "
        f"{stats.get('replied', 0)} respostas, {stats.get('skipped', 0)} ignorados.",
        "success",
    )
    return redirect(url_for("sollus_tickets.admin_settings"))


@sollus_tickets_bp.route("/admin/caixas-email/<int:mailbox_id>/sincronizar", methods=["POST"], endpoint="sync_mailbox")
@login_required
def sync_mailbox_route(mailbox_id: int):
    if not _can_manage():
        abort(403)
    try:
        stats = sync_mailbox(mailbox_id, limit=_as_int(request.form.get("limit")))
        flash(
            f"Caixa sincronizada: {stats.get('created', 0)} criados, "
            f"{stats.get('replied', 0)} respostas, {stats.get('skipped', 0)} ignorados.",
            "success",
        )
    except Exception as exc:
        flash(f"Falha ao sincronizar caixa: {exc}", "danger")
    return redirect(url_for("sollus_tickets.admin_settings"))


@sollus_tickets_bp.route("/admin/caixas-email/<int:mailbox_id>/toggle-ativo", methods=["POST"], endpoint="toggle_mailbox_active")
@login_required
def toggle_mailbox_active_route(mailbox_id: int):
    if not _can_manage():
        abort(403)
    mailbox = SollusTicketMailbox.query.get_or_404(mailbox_id)
    mailbox.enabled = not mailbox.enabled
    db.session.commit()
    status = "ativada" if mailbox.enabled else "desativada"
    flash(f"Caixa '{mailbox.name}' foi {status}.", "success")
    return redirect(url_for("sollus_tickets.admin_settings"))



def _upsert_department() -> None:
    item_id = _as_int(request.form.get("id"))
    dept = SollusTicketDepartment.query.get(item_id) if item_id else None
    if not dept:
        name = (request.form.get("name") or "Departamento").strip()
        dept = SollusTicketDepartment(name=name, slug=slugify(name))
        db.session.add(dept)
    dept.name = (request.form.get("name") or dept.name).strip()
    dept.slug = (request.form.get("slug") or slugify(dept.name)).strip()
    dept.email = (request.form.get("email") or "").strip() or None
    dept.email_template_group_id = _as_int(request.form.get("email_template_group_id"))
    dept.is_active = request.form.get("is_active") == "on"
    dept.auto_assign_enabled = request.form.get("auto_assign_enabled") == "on"
    db.session.commit()


def _upsert_team() -> None:
    item_id = _as_int(request.form.get("id"))
    team = SollusTicketTeam.query.get(item_id) if item_id else None
    if not team:
        name = (request.form.get("name") or "Equipe").strip()
        team = SollusTicketTeam(name=name, slug=slugify(name))
        db.session.add(team)
        db.session.flush()
    team.name = (request.form.get("name") or team.name).strip()
    team.slug = (request.form.get("slug") or slugify(team.name)).strip()
    team.is_active = request.form.get("is_active") == "on"
    selected = {_as_int(value) for value in request.form.getlist("member_ids")}
    selected.discard(None)
    SollusTicketTeamMember.query.filter_by(team_id=team.id).delete()
    for user_id in selected:
        db.session.add(SollusTicketTeamMember(team_id=team.id, user_id=user_id))
    db.session.commit()


def _upsert_queue() -> None:
    item_id = _as_int(request.form.get("id"))
    name = (request.form.get("name") or "Fila").strip()
    queue = SollusTicketQueue.query.get(item_id) if item_id else None
    if not queue:
        queue = SollusTicketQueue(name=name, slug=slugify(name))
        db.session.add(queue)
    queue.name = name
    queue.slug = (request.form.get("slug") or slugify(name)).strip()
    queue.department_id = _as_int(request.form.get("department_id"))
    queue.team_id = _as_int(request.form.get("team_id"))
    queue.sort_order = _as_int(request.form.get("sort_order")) or 0
    queue.is_active = request.form.get("is_active") == "on"
    db.session.commit()


def _upsert_sla() -> None:
    item_id = _as_int(request.form.get("id"))
    name = (request.form.get("name") or "SLA").strip()
    sla = SollusTicketSLA.query.get(item_id) if item_id else None
    if not sla:
        sla = SollusTicketSLA(name=name, slug=slugify(name))
        db.session.add(sla)
    sla.name = name
    sla.slug = (request.form.get("slug") or slugify(name)).strip()
    sla.grace_period_hours = _as_int(request.form.get("grace_period_hours")) or 48
    sla.is_active = request.form.get("is_active") == "on"
    db.session.commit()


def _upsert_topic() -> None:
    item_id = _as_int(request.form.get("id"))
    name = (request.form.get("name") or "Topico").strip()
    topic = SollusTicketTopic.query.get(item_id) if item_id else None
    if not topic:
        topic = SollusTicketTopic(name=name, slug=slugify(name))
        db.session.add(topic)
    topic.name = name
    topic.slug = (request.form.get("slug") or slugify(name)).strip()
    topic.department_id = _as_int(request.form.get("department_id"))
    topic.is_active = request.form.get("is_active") == "on"
    db.session.commit()


def _upsert_field() -> None:
    item_id = _as_int(request.form.get("id"))
    label = (request.form.get("label") or "Campo").strip()
    field = SollusTicketFormField.query.get(item_id) if item_id else None
    if not field:
        field = SollusTicketFormField(label=label, key=(request.form.get("key") or slugify(label)).strip())
        db.session.add(field)
    field.label = label
    field.key = (request.form.get("key") or field.key or slugify(label)).strip()
    field.field_type = (request.form.get("field_type") or "text").strip()
    field.options_json = [v.strip() for v in (request.form.get("options") or "").splitlines() if v.strip()]
    field.required = request.form.get("required") == "on"
    field.topic_id = _as_int(request.form.get("topic_id"))
    field.sort_order = _as_int(request.form.get("sort_order")) or 0
    field.is_active = request.form.get("is_active") == "on"
    db.session.commit()


def _upsert_canned() -> None:
    item_id = _as_int(request.form.get("id"))
    title = (request.form.get("title") or "Resposta").strip()
    canned = SollusTicketCannedResponse.query.get(item_id) if item_id else None
    if not canned:
        canned = SollusTicketCannedResponse(title=title, slug=slugify(title), created_by_id=current_user.id)
        db.session.add(canned)
    canned.title = title
    canned.slug = (request.form.get("slug") or slugify(title)).strip()
    canned.body = (request.form.get("body") or "").strip()
    canned.department_id = _as_int(request.form.get("department_id"))
    canned.is_active = request.form.get("is_active") == "on"
    db.session.commit()


def _upsert_role_permission() -> None:
    role_key = (request.form.get("role_key") or "").strip().lower()
    if not role_key:
        return
    perm = SollusTicketRolePermission.query.filter_by(role_key=role_key).first()
    if not perm:
        perm = SollusTicketRolePermission(role_key=role_key)
        db.session.add(perm)
    for field in ("can_view_all", "can_assign", "can_manage_admin", "can_close", "can_reopen", "can_internal_note", "can_transfer", "can_delete", "can_merge", "can_link", "can_manage_tasks", "can_manage_queues", "limit_access"):
        setattr(perm, field, request.form.get(field) == "on")
    db.session.commit()


def _upsert_banlist() -> None:
    value = (request.form.get("value") or "").strip().lower()
    if not value:
        return
    item = SollusTicketBanlist.query.filter_by(kind=(request.form.get("kind") or "email").strip(), value=value).first()
    if not item:
        item = SollusTicketBanlist(kind=(request.form.get("kind") or "email").strip(), value=value, created_by_id=current_user.id)
        db.session.add(item)
    item.reason = (request.form.get("reason") or "").strip() or None
    item.is_active = request.form.get("is_active") == "on"
    db.session.commit()


def _upsert_filter_rule() -> None:
    name = (request.form.get("name") or "").strip()
    if not name:
        return
    rule = SollusTicketFilterRule(name=name)
    rule.is_active = request.form.get("is_active") == "on"
    rule.stop_processing = request.form.get("stop_processing") == "on"
    rule.match_all = request.form.get("match_all") == "on"
    rule.sender_contains = (request.form.get("sender_contains") or "").strip() or None
    rule.subject_contains = (request.form.get("subject_contains") or "").strip() or None
    rule.body_contains = (request.form.get("body_contains") or "").strip() or None
    rule.header_contains = (request.form.get("header_contains") or "").strip() or None
    rule.set_priority_key = (request.form.get("set_priority_key") or "").strip() or None
    rule.set_department_id = _as_int(request.form.get("set_department_id"))
    rule.set_topic_id = _as_int(request.form.get("set_topic_id"))
    rule.set_queue_id = _as_int(request.form.get("set_queue_id"))
    rule.set_team_id = _as_int(request.form.get("set_team_id"))
    rule.set_sla_id = _as_int(request.form.get("set_sla_id"))
    rule.assign_user_id = _as_int(request.form.get("assign_user_id"))
    rule.reject_ticket = request.form.get("reject_ticket") == "on"
    rule.sort_order = _as_int(request.form.get("sort_order")) or 0
    db.session.add(rule)
    db.session.commit()


def _upsert_template() -> None:
    group_id = _as_int(request.form.get("group_id"))
    if not group_id:
        group = SollusTicketEmailTemplateGroup.query.filter_by(slug="padrao").first()
        group_id = group.id if group else None
    event_key = (request.form.get("event_key") or "").strip()
    if not group_id or not event_key:
        return
    template = SollusTicketEmailTemplate.query.filter_by(group_id=group_id, event_key=event_key).first()
    if not template:
        template = SollusTicketEmailTemplate(group_id=group_id, event_key=event_key, subject="", body_html="")
        db.session.add(template)
    template.subject = (request.form.get("subject") or "").strip()
    template.body_html = (request.form.get("body_html") or "").strip()
    template.body_text = (request.form.get("body_text") or "").strip() or None
    template.is_active = request.form.get("is_active") == "on"
    template.suppress_autoreply = request.form.get("suppress_autoreply") == "on"
    db.session.commit()


def _upsert_department_access() -> None:
    department_id = _as_int(request.form.get("department_id"))
    user_id = _as_int(request.form.get("user_id"))
    if not department_id or not user_id:
        return
    access = SollusTicketDepartmentAccess.query.filter_by(department_id=department_id, user_id=user_id).first()
    if not access:
        access = SollusTicketDepartmentAccess(department_id=department_id, user_id=user_id)
        db.session.add(access)
    access.role = (request.form.get("role") or "agent").strip()
    access.is_manager = request.form.get("is_manager") == "on"
    db.session.commit()


def _upsert_queue_column() -> None:
    item_id = _as_int(request.form.get("id"))
    queue_id = _as_int(request.form.get("queue_id"))
    field_key = (request.form.get("field_key") or "").strip()
    label = (request.form.get("label") or field_key).strip()
    if not queue_id or not field_key:
        return
    column = SollusTicketCustomQueueColumn.query.get(item_id) if item_id else None
    if not column:
        column = SollusTicketCustomQueueColumn(queue_id=queue_id, field_key=field_key, label=label)
        db.session.add(column)
    column.queue_id = queue_id
    column.field_key = field_key
    column.label = label
    column.sort_order = _as_int(request.form.get("sort_order")) or 0
    column.is_visible = request.form.get("is_visible") == "on"
    db.session.commit()


def _upsert_queue_sort() -> None:
    item_id = _as_int(request.form.get("id"))
    queue_id = _as_int(request.form.get("queue_id"))
    field_key = (request.form.get("field_key") or "").strip()
    if not queue_id or not field_key:
        return
    sort = SollusTicketCustomQueueSort.query.get(item_id) if item_id else None
    if not sort:
        sort = SollusTicketCustomQueueSort(queue_id=queue_id, field_key=field_key)
        db.session.add(sort)
    sort.queue_id = queue_id
    sort.field_key = field_key
    sort.direction = "asc" if request.form.get("direction") == "asc" else "desc"
    sort.sort_order = _as_int(request.form.get("sort_order")) or 0
    db.session.commit()


def _delete_record() -> None:
    model_map = {
        "department": SollusTicketDepartment,
        "team": SollusTicketTeam,
        "mailbox": SollusTicketMailbox,
        "role_permission": SollusTicketRolePermission,
        "template_group": SollusTicketEmailTemplateGroup,
        "department_access": SollusTicketDepartmentAccess,
        "banlist": SollusTicketBanlist,
        "filter_rule": SollusTicketFilterRule,
        "template": SollusTicketEmailTemplate,
        "queue_column": SollusTicketCustomQueueColumn,
        "queue_sort": SollusTicketCustomQueueSort,
        "canned": SollusTicketCannedResponse,
        "field": SollusTicketFormField,
        "topic": SollusTicketTopic,
        "queue": SollusTicketQueue,
        "sla": SollusTicketSLA,
    }
    model = model_map.get((request.form.get("kind") or "").strip())
    item_id = _as_int(request.form.get("id"))
    if not model or not item_id:
        return
    item = model.query.get(item_id)
    if item:
        db.session.delete(item)
        db.session.commit()


def _upsert_mailbox() -> None:
    item_id = _as_int(request.form.get("id"))
    mailbox = SollusTicketMailbox.query.get(item_id) if item_id else None
    if not mailbox:
        mailbox = SollusTicketMailbox(
            name=(request.form.get("name") or request.form.get("email") or "Caixa").strip(),
            email=(request.form.get("email") or "").strip().lower(),
            host=(request.form.get("host") or "").strip(),
            username=(request.form.get("username") or "").strip(),
            password=(request.form.get("password") or "").strip(),
        )
        db.session.add(mailbox)
    mailbox.name = (request.form.get("name") or mailbox.name).strip()
    mailbox.email = (request.form.get("email") or mailbox.email).strip().lower()
    mailbox.protocol = (request.form.get("protocol") or "imap").strip().lower()
    if mailbox.protocol not in {"imap", "pop"}:
        mailbox.protocol = "imap"
    mailbox.host = (request.form.get("host") or mailbox.host).strip()
    mailbox.port = _as_int(request.form.get("port")) or 993
    mailbox.username = (request.form.get("username") or mailbox.username).strip()
    password = (request.form.get("password") or "").strip()
    if password:
        mailbox.password = password
    mailbox.folder = (request.form.get("folder") or "INBOX").strip()
    mailbox.fetch_frequency_minutes = _as_int(request.form.get("fetch_frequency_minutes")) or 5
    mailbox.fetch_max = _as_int(request.form.get("fetch_max")) or 30
    mailbox.postfetch = (request.form.get("postfetch") or "nothing").strip()
    if mailbox.postfetch not in {"nothing", "archive", "delete"}:
        mailbox.postfetch = "nothing"
    mailbox.archive_folder = (request.form.get("archive_folder") or "").strip() or None
    mailbox.use_ssl = request.form.get("use_ssl") == "on"
    mailbox.mark_seen = request.form.get("mark_seen") == "on"
    mailbox.enabled = request.form.get("enabled") == "on"
    mailbox.department_id = _as_int(request.form.get("department_id"))
    mailbox.topic_id = _as_int(request.form.get("topic_id"))
    mailbox.queue_id = _as_int(request.form.get("queue_id"))
    mailbox.team_id = _as_int(request.form.get("team_id"))
    mailbox.sla_id = _as_int(request.form.get("sla_id"))
    db.session.commit()


def _as_int(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def _parse_date(value: str, end_of_day: bool = False):
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    if end_of_day:
        return parsed.replace(hour=23, minute=59, second=59)
    return parsed


def _find_ticket_by_token(value: str) -> SollusTicket | None:
    value = (value or "").strip()
    if not value:
        return None
    filters = [
        SollusTicket.number == value,
        SollusTicket.legacy_number == value
    ]
    if value.isdigit():
        filters.append(SollusTicket.number == value.zfill(6))
        filters.append(SollusTicket.legacy_number == value.zfill(6))
    ticket = SollusTicket.query.filter(or_(*filters)).first()
    if ticket:
        return ticket
    if value.isdigit():
        return SollusTicket.query.get(int(value))
    return None


# ---------------------------------------------------------------------------
# Exportação CSV
# ---------------------------------------------------------------------------

@sollus_tickets_bp.route("/exportar.csv", endpoint="export_csv")
@login_required
def export_csv():
    import csv, io
    from flask import Response

    query = ticket_visible_query(current_user)
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()
    department_id = (request.args.get("department_id") or "").strip()
    priority_key = (request.args.get("priority_key") or "").strip()
    assignee_id = (request.args.get("assignee_id") or "").strip()

    if search:
        like = f"%{search}%"
        query = query.filter(or_(SollusTicket.subject.ilike(like), SollusTicket.number.ilike(like)))
    if status:
        if status == "open":
            query = query.filter(SollusTicket.status_key.in_(("open", "in_progress", "waiting_user")))
        elif status == "closed":
            query = query.filter(SollusTicket.status_key.in_(("closed", "resolved")))
        else:
            query = query.filter(SollusTicket.status_key == status)
    if department_id.isdigit():
        query = query.filter(SollusTicket.department_id == int(department_id))
    if priority_key:
        query = query.filter(SollusTicket.priority_key == priority_key)
    if assignee_id.isdigit():
        query = query.filter(SollusTicket.assignee_id == int(assignee_id))
    elif assignee_id == "none":
        query = query.filter(SollusTicket.assignee_id.is_(None))

    tickets = query.order_by(SollusTicket.created_at.desc()).limit(5000).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Número", "Assunto", "Status", "Prioridade", "Departamento", "Responsável", "Solicitante", "Criado em", "Atualizado em"])
    for t in tickets:
        writer.writerow([
            t.number or t.id,
            t.subject,
            t.status_key,
            t.priority_key,
            t.department.name if t.department else "",
            (t.assignee.nome_completo or t.assignee.email) if t.assignee else "",
            t.requester_label,
            t.created_at.strftime("%d/%m/%Y %H:%M") if t.created_at else "",
            t.updated_at.strftime("%d/%m/%Y %H:%M") if t.updated_at else "",
        ])

    output.seek(0)
    return Response(
        "\ufeff" + output.getvalue(),  # BOM para Excel
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=tickets.csv"},
    )


# ---------------------------------------------------------------------------
# Diretório de Agentes
# ---------------------------------------------------------------------------

@sollus_tickets_bp.route("/agentes", endpoint="agents_directory")
@login_required
def agents_directory():
    from modules.propostas.models import User
    all_agents = agents_query()
    return render_template(
        "sollus_tickets/agents_directory.html",
        agents=all_agents,
        total=len(all_agents),
    )


# ---------------------------------------------------------------------------
# API — Campos por tópico (para formulário dinâmico)
# ---------------------------------------------------------------------------

@sollus_tickets_bp.route("/api/topics/<int:topic_id>/campos", endpoint="api_topic_fields")
@login_required
def api_topic_fields(topic_id: int):
    from flask import jsonify
    fields = (
        SollusTicketFormField.query
        .filter_by(topic_id=topic_id, is_active=True)
        .order_by(SollusTicketFormField.sort_order, SollusTicketFormField.label)
        .all()
    )
    return jsonify([{
        "id": f.id,
        "key": f.key,
        "label": f.label,
        "field_type": f.field_type,
        "required": f.required,
        "options": f.options_json or [],
    } for f in fields])


# ---------------------------------------------------------------------------
# API — Assinatura do agente logado
# ---------------------------------------------------------------------------

@sollus_tickets_bp.route("/api/agent/signature", endpoint="api_agent_signature")
@login_required
def api_agent_signature():
    from flask import jsonify, send_file
    from pathlib import Path
    sig_path = getattr(current_user, "signature_path", None)
    if sig_path:
        full_path = Path(current_app.config.get("UPLOADS_DIR", "uploads")) / sig_path
        if full_path.exists():
            try:
                return jsonify({"ok": True, "signature": full_path.read_text(encoding="utf-8")})
            except Exception:
                pass
    name = getattr(current_user, "nome_completo", None) or getattr(current_user, "email", "")
    return jsonify({"ok": True, "signature": f"\n\n--\n{name}"})


# ---------------------------------------------------------------------------
# API — Preview de template de e-mail
# ---------------------------------------------------------------------------

@sollus_tickets_bp.route("/api/templates/<int:template_id>/preview", methods=["POST"], endpoint="api_template_preview")
@login_required
def api_template_preview(template_id: int):
    from flask import jsonify
    if not _can_manage():
        from flask import abort
        abort(403)
    tmpl = SollusTicketEmailTemplate.query.get_or_404(template_id)
    from ...ticket_mailer import _render_template_str
    fake_vars = {
        "ticket.number": "000123",
        "ticket.subject": "Problema com o sistema de ponto",
        "ticket.status": "open",
        "ticket.priority": "normal",
        "ticket.department": "Suporte Técnico",
        "ticket.created_at": "14/05/2026 10:30",
        "ticket.due_at": "16/05/2026 18:00",
        "requester.name": "João da Silva",
        "requester.email": "joao@empresa.com.br",
        "assignee.name": "Maria Técnica",
        "assignee.email": "maria@sollusgroup.com.br",
        "agent.name": "Maria Técnica",
        "agent.email": "maria@sollusgroup.com.br",
        "reply.body": "Olá João, verificamos o problema e já estamos resolvendo.",
        "sla.overdue_since": "2h em atraso",
    }
    return jsonify({
        "ok": True,
        "subject": _render_template_str(tmpl.subject, fake_vars),
        "body_html": _render_template_str(tmpl.body_html, fake_vars),
    })
