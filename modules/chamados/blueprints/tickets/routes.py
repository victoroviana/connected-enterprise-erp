from __future__ import annotations



import os

import secrets

import mimetypes

import logging

from datetime import datetime

from pathlib import Path

from typing import List, Optional, Iterable



from flask import (
    current_app, render_template, request, redirect, url_for,
    flash, abort, send_file, session, jsonify
)
from utils.helpers import (
    wants_json as _wants_json,
)

from flask_login import login_required, current_user

from werkzeug.utils import secure_filename



from . import tickets_bp

from extensions import db

from modules.propostas.models import User
from modules.propostas.blueprints.auth.permissions_utils import normalize_role_key, raw_permissions, current_permissions

from modules.chamados.models import Ticket, Attachment, TicketMessage

from modules.chamados.mailer import enviar_email  # envio SMTP direto

from modules.chamados.utils.audit import write_audit  # <<< AUDITORIA



# ============================

# Helpers

# ============================



_ALLOWED_EXTS = {

    ".png", ".jpg", ".jpeg", ".gif", ".webp",

    ".pdf", ".txt", ".log", ".csv",

    ".doc", ".docx", ".xls", ".xlsx"

}





def _allowed_file(filename: str) -> bool:

    ext = os.path.splitext(filename)[1].lower()

    return bool(ext) and (ext in _ALLOWED_EXTS)




def _deny_access(area_label: str):
    from flask import request
    if "/api/" in getattr(request, "path", "") or _wants_json():
        return jsonify({
            "error": "Access denied",
            "success": False,
            "message": f"Você não tem permissão para acessar esta área ({area_label})."
        }), 403
    flash(
        "Você não tem permissão para acessar esta área. Procure seu superior caso precise de acesso.",
        "warning",
    )
    return redirect(url_for("sem_permissao", area=area_label))


@tickets_bp.before_request
def _check_chamados_access():
    from flask import request
    endpoint = getattr(request, "endpoint", "") or ""
    if endpoint and not endpoint.startswith("tickets."):
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
    role_key = normalize_role_key(
        getattr(current_user, "tipo", None)
        or getattr(current_user, "role", None)
        or session.get("tipo")
    )
    if role_key in ("admin", "gestor", "agent"):
        return
    if current_permissions().get("chamados"):
        return
    return _deny_access("Chamados")





def _agents_query() -> List[User]:
    """
    Retorna usuários ativos que podem ser técnicos/atendentes nos chamados.
    Restringe a usuários ativos que pertencem ao departamento OFICINA
    ou são técnicos legados ativos da ASSISTENCIA TECNICA com role=agent.
    """
    from modules.propostas.models import Department
    from sqlalchemy import or_, exists
    from modules.propostas.models import user_departments as _user_dept_table

    oficina_dept = Department.query.filter_by(slug="oficina").first()
    oficina_id = oficina_dept.id if oficina_dept else 3  # fallback para ID conhecido

    # Subquery: usuário está na oficina via tabela N:N user_departments
    in_oficina_via_many = exists().where(
        (_user_dept_table.c.user_id == User.id)
        & (_user_dept_table.c.department_id == oficina_id)
    )

    return (
        User.query
        .filter(
            User.is_active.is_(True),
            or_(
                # Pertence ao departamento OFICINA (FK direto)
                User.department_id == oficina_id,
                # Pertence ao departamento OFICINA (relação N:N)
                in_oficina_via_many,
            ),
        )
        .order_by(User.nome_completo.asc(), User.email.asc())
        .all()
    )





def _file_size_of_upload(file_storage) -> int:

    """

    Tenta obter o tamanho do upload sem quebrar o stream.

    """

    size = 0

    try:

        stream = getattr(file_storage, "stream", None) or file_storage

        cur = stream.tell()

        stream.seek(0, os.SEEK_END)

        size = stream.tell()

        stream.seek(cur)

    except Exception:

        try:

            file_storage.seek(0, os.SEEK_END)

            size = file_storage.tell()

            file_storage.seek(0)

        except Exception:

            size = 0

    return int(size or 0)





def _save_file_for_ticket(ticket: Ticket, f) -> Optional[Attachment]:

    """

    Salva o upload em /uploads/tickets/<ticket_id>/ e cria Attachment (pendente de commit).

    Suporta modelos que usem 'uploaded_by' ou 'uploader_id'.

    """

    if not f or not getattr(f, "filename", ""):

        return None



    original_name = f.filename or ""

    filename = secure_filename(original_name)

    if not filename:

        return None



    if not _allowed_file(filename):

        flash(f"Extenso no permitida para {filename}.", "warning")

        return None



    size = _file_size_of_upload(f)

    max_mb = current_app.config.get("MAX_CONTENT_MB", 20)

    if size and size > max_mb * 1024 * 1024:

        flash(f"{filename} excede {max_mb}MB.", "warning")

        return None



    ext = os.path.splitext(filename)[1].lower()

    stored = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(6)}{ext}"



    base = Path(current_app.config.get("UPLOADS_DIR", "uploads"))

    folder = base / "tickets" / str(ticket.id)

    folder.mkdir(parents=True, exist_ok=True)



    dst = folder / stored

    f.save(dst)



    ctype = getattr(f, "mimetype", None) or mimetypes.guess_type(filename)[0]



    # Monta kwargs compatvel com o seu modelo (uploaded_by x uploader_id)

    att_kwargs = dict(

        ticket_id=ticket.id,

        original_name=filename,   # mantm histrico do nome enviado

        filename=filename,        # compatibilidade com schema antigo

        stored_name=stored,

        content_type=ctype,

        size=size,

    )

    if hasattr(Attachment, "uploaded_by"):

        att_kwargs["uploaded_by"] = current_user.id

    elif hasattr(Attachment, "uploader_id"):

        att_kwargs["uploader_id"] = current_user.id



    att = Attachment(**att_kwargs)

    db.session.add(att)

    return att





def _collect_uploads_from_request() -> List:

    """

    Coleta arquivos do request, aceitando mltiplas chaves comuns.

    """

    files: List = []

    for key in ("attachments", "attachments[]", "file", "files"):

        if key in request.files:

            items = request.files.getlist(key)

            if items:

                files.extend(items)

    return files





def _user_can_edit_ticket(ticket: Ticket) -> bool:

    role = (getattr(current_user, "role", "") or "").lower()

    return (ticket.user_id == current_user.id) or (role in ("agent", "gestor", "admin"))





def _user_can_assign() -> bool:

    role = (getattr(current_user, "role", "") or "").lower()

    return role in ("agent", "gestor", "admin")





def _user_can_reply(ticket: Ticket) -> bool:

    role = (getattr(current_user, "role", "") or "").lower()

    assignee_id = getattr(ticket, "assignee_id", None) or getattr(ticket, "agent_id", None)

    return (role in ("agent", "gestor", "admin")) or (assignee_id == current_user.id)





# ============================

# Helpers de URL / textos PT-BR

# ============================



def _abs_url(endpoint: str, **values) -> str:

    """URL absoluta mesmo sem SERVER_NAME corretamente definido."""

    try:

        return url_for(endpoint, _external=True, **values)

    except Exception:

        base = (current_app.config.get("MAIL_BASE_URL") or request.url_root).rstrip("/")

        return f"{base}{url_for(endpoint, **values)}"





def _str_pt_status(status: str) -> str:

    s = (status or "").lower()

    return "Finalizado" if s == "closed" else ("Em andamento" if s == "in_progress" else "Aberto")





def _str_pt_priority(priority: str) -> str:

    p = (priority or "").lower()

    if p == "low": return "Baixa"

    if p == "medium": return "Mdia"

    if p == "high": return "Alta"

    if p == "urgent": return "Urgente"

    return ""





# ============================

# Notificaes por e-mail (HTML com template)

# ============================



def _resolve_assignee_label(ticket: Ticket) -> Optional[str]:

    """

    Retorna o nome/e-mail do atendente, mesmo que s exista *_id.

    Suporta 'assignee'/'assignee_id' ou 'agent'/'agent_id'.

    """

    user_obj = getattr(ticket, "assignee", None) or getattr(ticket, "agent", None)

    if not user_obj:

        uid = getattr(ticket, "assignee_id", None) or getattr(ticket, "agent_id", None)

        if uid:

            user_obj = User.query.get(uid)

    if user_obj:

        return user_obj.name or user_obj.email

    return None





def _ticket_recipients(ticket: Ticket, include_reporter=True, include_assignee=True, extra: Optional[Iterable[str]] = None) -> List[str]:

    emails: List[str] = []



    if include_reporter and getattr(ticket, "user", None) and ticket.user.email:

        emails.append(ticket.user.email)



    # assignee/agente

    assignee_email = None

    assignee_obj = getattr(ticket, "assignee", None) or getattr(ticket, "agent", None)

    if assignee_obj and assignee_obj.email:

        assignee_email = assignee_obj.email

    else:

        uid = getattr(ticket, "assignee_id", None) or getattr(ticket, "agent_id", None)

        if uid:

            u = User.query.get(uid)

            if u and u.email:

                assignee_email = u.email

    if include_assignee and assignee_email:

        emails.append(assignee_email)



    # extras

    if extra:

        emails.extend([e for e in extra if e])



    # unicidade / limpeza

    uniq: List[str] = []

    seen = set()

    for e in emails:

        e2 = (e or "").strip().lower()

        if e2 and e2 not in seen:

            seen.add(e2)

            uniq.append(e)

    return uniq





def _mail_body(event: str, ticket: Ticket, extra: str | None = None) -> str:

    """

    Gera HTML bonito via template Jinja para as notificaes.

    Template: templates/email/notify.html

    """

    base_url = (current_app.config.get("MAIL_BASE_URL") or request.url_root).rstrip("/")

    logo_url = f"{base_url}/static/images/sollus_logo_white.png"

    cta_url = _abs_url('tickets.ticket_detail', ticket_id=ticket.id)



    # PT-BR status/prioridade

    status_pt = _str_pt_status(ticket.status)

    priority_pt = _str_pt_priority(ticket.priority)



    requester = ticket.user.name if (ticket.user and ticket.user.name) else (ticket.user.email if ticket.user else "-")

    assignee = _resolve_assignee_label(ticket)



    created_at = ticket.created_at.strftime("%d/%m/%Y %H:%M") if getattr(ticket, "created_at", None) else None

    updated_at = ticket.updated_at.strftime("%d/%m/%Y %H:%M") if getattr(ticket, "updated_at", None) else None



    titles = {

        "created": ("Chamado criado", "Um novo chamado foi aberto."),

        "assigned": ("Chamado atribudo", "O chamado foi atribudo a um atendente."),

        "status": (f"Status alterado para {status_pt}", "O status do chamado foi atualizado."),

        "reply": ("Nova resposta no chamado", "Uma nova mensagem foi adicionada ao chamado."),

    }

    title, subtitle = titles.get(event, ("Atualizao no chamado", None))



    last_message = (extra or "").strip() or None



    return render_template(
        "chamados/email/notify.html",
        title=f"[Chamado #{ticket.id}] {title}  {ticket.title}",

        subtitle=subtitle,

        env_label=current_app.config.get("FLASK_ENV", "ticket").capitalize(),

        logo_url=logo_url,

        cta_url=cta_url,

        cta_label="Abrir Chamado",

        ticket=ticket,

        status_pt=status_pt,

        priority_pt=priority_pt,

        requester=requester,

        assignee=assignee,

        created_at=created_at,

        updated_at=updated_at,

        description=ticket.description,

        last_message=last_message,

    )





def _mail_subject(event: str, ticket: Ticket) -> str:

    """

    Assunto padronizado.

    """

    if event == "created":

        mid = "Criado"

    elif event == "assigned":

        mid = "Atribudo"

    elif event == "status":

        mid = f"Status alterado para {_str_pt_status(ticket.status)}"

    elif event == "reply":

        mid = "Nova resposta"

    else:

        mid = "Atualizao"

    return f"[Chamado #{ticket.id}] {mid}  {ticket.title}"





def _notify_event(event: str, ticket: Ticket, destinatarios: List[str], extra: str = "") -> None:

    """

    Dispara e-mail usando mailer.enviar_email. No quebra o fluxo em caso de erro.

    event: created | assigned | status | reply

    """

    if not destinatarios:

        return

    assunto = _mail_subject(event, ticket)

    html = _mail_body(event, ticket, extra)

    ok = enviar_email(destinatarios, assunto, html)

    if not ok:

        logging.warning(f"[mail] falha ao enviar '{assunto}' para {destinatarios}")





# ============================

# Rotas de criao

# ============================



@tickets_bp.route('/new', methods=['GET'], endpoint='new')

@login_required

def new_ticket():

    agents = _agents_query()

    return render_template('chamados/tickets/new.html', agents=agents)





@tickets_bp.route('/create', methods=['GET', 'POST'], endpoint='create_ticket')

@login_required

def create_ticket():

    if request.method == 'GET':

        return redirect(url_for('tickets.new'))



    title = (request.form.get('title') or '').strip()

    description = (request.form.get('description') or '').strip()

    priority = (request.form.get('priority') or 'medium').strip().lower()

    if priority not in ('low', 'medium', 'high', 'urgent'):

        priority = 'medium'



    if not title:

        flash('Ttulo  obrigatrio.', 'warning')

        return redirect(url_for('tickets.new'))



    ticket = Ticket(

        title=title,

        description=description,

        priority=priority,

        status='open',

        user_id=current_user.id

    )

    db.session.add(ticket)

    db.session.flush()  # garante ticket.id



    # atribuio inicial opcional

    assignee_raw = (request.form.get('assignee_id') or '').strip()

    if assignee_raw.isdigit():

        assignee_id = int(assignee_raw)

        if hasattr(ticket, 'assignee_id'):

            ticket.assignee_id = assignee_id

        elif hasattr(ticket, 'agent_id'):

            ticket.agent_id = assignee_id



    # aceita 1 ou vrios arquivos (file, files, attachments, attachments[])

    for f in _collect_uploads_from_request():

        _save_file_for_ticket(ticket, f)



    # AUDIT: criao do chamado (no mesmo commit)

    write_audit(

        entity_type="Ticket",

        entity_id=ticket.id,

        action="create",

        message=f"Criado '{ticket.title}'",

        after={

            "id": ticket.id, "title": ticket.title, "status": ticket.status, "priority": ticket.priority,

            "user_id": ticket.user_id, "assignee_id": getattr(ticket, 'assignee_id', None) or getattr(ticket, 'agent_id', None)

        }

    )



    db.session.commit()

    flash('Chamado criado com sucesso.', 'success')



    # Notificao: criado (para solicitante + atendente, se houver)

    dest = _ticket_recipients(ticket, include_reporter=True, include_assignee=True)

    _notify_event("created", ticket, dest)



    return redirect(url_for('tickets.ticket_detail', ticket_id=ticket.id))





# ============================

# Detalhe / Resposta / Atribuio / Status

# ============================



@tickets_bp.route('/<int:ticket_id>', methods=['GET'], endpoint='ticket_detail')

@login_required

def ticket_detail(ticket_id: int):

    """

    Mostra todos os dados do chamado, respostas e anexos.

    """

    ticket = Ticket.query.get_or_404(ticket_id)



    can_edit = _user_can_edit_ticket(ticket)

    can_assign = _user_can_assign()

    can_reply = _user_can_reply(ticket)

    agents = _agents_query()



    current_assignee_id = getattr(ticket, 'assignee_id', None) or getattr(ticket, 'agent_id', None)

    current_assignee = next((u for u in agents if u.id == current_assignee_id), None)

    current_assignee_label = None

    if current_assignee:

        current_assignee_label = current_assignee.name or getattr(current_assignee, 'username', None) or current_assignee.email



    # mensagens do chamado (pblicas), mais antigas primeiro

    messages = (

        TicketMessage.query

        .filter_by(ticket_id=ticket.id, public=True)

        .order_by(TicketMessage.created_at.asc())

        .all()

    )



    # materializa anexos (compatvel com lazy="dynamic")

    attachments_rel = getattr(ticket, "attachments", None)

    if attachments_rel is None:

        attachments = []

    else:

        attachments = attachments_rel.all() if hasattr(attachments_rel, "all") else list(attachments_rel)



    reply_url = url_for('tickets.reply', ticket_id=ticket.id)



    return render_template(
        'chamados/tickets/detail.html',
        ticket=ticket,

        agents=agents,

        can_edit=can_edit,

        can_assign=can_assign,

        can_reply=can_reply,

        messages=messages,

        attachments=attachments,  # <<--- PASSA A LISTA PRONTA

        current_assignee_id=current_assignee_id,

        current_assignee_label=current_assignee_label,

        reply_url=reply_url,

    )





@tickets_bp.route('/<int:ticket_id>/reply', methods=['POST'], endpoint='reply')

@login_required

def reply(ticket_id: int):

    ticket = Ticket.query.get_or_404(ticket_id)

    if not _user_can_reply(ticket):

        flash('Você não tem permissão para responder este chamado.', 'warning')

        return redirect(url_for('tickets.ticket_detail', ticket_id=ticket.id))



    body = (request.form.get('message') or '').strip()

    if not body:

        flash('Escreva uma mensagem.', 'warning')

        return redirect(url_for('tickets.ticket_detail', ticket_id=ticket.id))



    db.session.add(TicketMessage(ticket_id=ticket.id, author_id=current_user.id, body=body, public=True))

    if hasattr(ticket, 'updated_at'):

        ticket.updated_at = datetime.utcnow()



    # AUDIT: resposta no chamado

    write_audit(

        entity_type="Ticket",

        entity_id=ticket.id,

        action="reply",

        message="Nova resposta adicionada",

        after={"message": body[:500]}  # corta para evitar blobs enormes

    )



    db.session.commit()

    flash('Resposta registrada.', 'success')



    # Notificao: nova resposta (avisa a outra parte)

    is_author_reporter = (current_user.id == ticket.user_id)

    if is_author_reporter:

        dest = _ticket_recipients(ticket, include_reporter=False, include_assignee=True)

    else:

        dest = _ticket_recipients(ticket, include_reporter=True, include_assignee=False)

    _notify_event("reply", ticket, dest, extra=body)



    return redirect(url_for('tickets.ticket_detail', ticket_id=ticket.id))





@tickets_bp.route('/<int:ticket_id>/assign', methods=['POST'], endpoint='assign_agent')

@login_required

def assign_agent(ticket_id: int):

    if not _user_can_assign():

        abort(403)



    ticket = Ticket.query.get_or_404(ticket_id)

    assignee_raw = (request.form.get('assignee_id') or '').strip()

    if not assignee_raw.isdigit():

        flash('Seleo de atendente invlida.', 'warning')

        return redirect(url_for('tickets.ticket_detail', ticket_id=ticket.id))



    before = {

        "assignee_id": getattr(ticket, 'assignee_id', None) or getattr(ticket, 'agent_id', None)

    }



    assignee_id = int(assignee_raw)

    if hasattr(ticket, 'assignee_id'):

        ticket.assignee_id = assignee_id

    elif hasattr(ticket, 'agent_id'):

        ticket.agent_id = assignee_id



    # AUDIT: atribuio

    write_audit(

        entity_type="Ticket",

        entity_id=ticket.id,

        action="assign",

        message=f"Atribudo para usuário #{assignee_id}",

        before=before,

        after={"assignee_id": assignee_id}

    )



    db.session.commit()

    flash('Atendente atribudo com sucesso.', 'success')



    # Notificao: atribudo (para solicitante + novo atendente)

    dest = _ticket_recipients(ticket, include_reporter=True, include_assignee=True)

    _notify_event("assigned", ticket, dest)



    return redirect(url_for('tickets.ticket_detail', ticket_id=ticket.id))





@tickets_bp.route('/<int:ticket_id>/status', methods=['POST'], endpoint='update_status')

@login_required

def update_status(ticket_id: int):

    ticket = Ticket.query.get_or_404(ticket_id)

    if not _user_can_assign():

        abort(403)



    status = (request.form.get('status') or '').strip().lower()

    if status not in ('open', 'in_progress', 'closed'):

        flash('Status invlido.', 'warning')

        return redirect(url_for('tickets.ticket_detail', ticket_id=ticket.id))



    before = {"status": ticket.status}

    ticket.status = status

    if hasattr(ticket, 'updated_at'):

        ticket.updated_at = datetime.utcnow()



    # AUDIT: mudana de status

    write_audit(

        entity_type="Ticket",

        entity_id=ticket.id,

        action="status",

        message=f"Status alterado para {status}",

        before=before,

        after={"status": ticket.status}

    )



    db.session.commit()



    flash('Status atualizado.', 'success')



    # Notificao: mudana de status (para solicitante + atendente)

    dest = _ticket_recipients(ticket, include_reporter=True, include_assignee=True)

    _notify_event("status", ticket, dest)



    if status == 'closed':

        return redirect(url_for('tickets.closed_list'))

    return redirect(url_for('tickets.ticket_detail', ticket_id=ticket.id))





# ============================

# Anexos

# ============================



@tickets_bp.route('/<int:ticket_id>/attachments/upload', methods=['POST'], endpoint='attachments_upload')

@login_required

def attachments_upload(ticket_id: int):

    ticket = Ticket.query.get_or_404(ticket_id)

    if not _user_can_edit_ticket(ticket):

        abort(403)



    f = request.files.get('file')

    if not f:

        flash('Nenhum arquivo selecionado.', 'warning')

        return redirect(url_for('tickets.ticket_detail', ticket_id=ticket.id))



    att = _save_file_for_ticket(ticket, f)

    if att:

        # AUDIT: upload de anexo

        write_audit(

            entity_type="TicketAttachment",

            entity_id=att.id,

            action="upload",

            message=f"Arquivo anexado ao ticket #{ticket.id}",

            after={

                "ticket_id": ticket.id,

                "original_name": att.original_name,

                "stored_name": att.stored_name,

                "size": att.size,

                "content_type": att.content_type

            }

        )

        db.session.commit()

        flash('Arquivo enviado.', 'success')

    else:

        db.session.rollback()

    return redirect(url_for('tickets.ticket_detail', ticket_id=ticket.id))





@tickets_bp.route('/<int:ticket_id>/attachments/<int:att_id>/download', methods=['GET'], endpoint='attachments_download')

@login_required

def attachments_download(ticket_id: int, att_id: int):

    ticket = Ticket.query.get_or_404(ticket_id)

    att = Attachment.query.get_or_404(att_id)

    if att.ticket_id != ticket.id:

        abort(404)



    stored_name = att.stored_name
    if not stored_name:
        abort(404)

    base = Path(current_app.config.get('UPLOADS_DIR', 'uploads')).resolve()
    fpath = (base / 'tickets' / str(ticket.id) / stored_name).resolve()
    try:
        fpath.relative_to(base)
    except ValueError:
        abort(404)

    if not fpath.is_file():
        abort(404)

    download_name = att.original_name or att.filename or stored_name
    return send_file(
        fpath,
        as_attachment=True,
        download_name=download_name,
        mimetype=att.content_type or mimetypes.guess_type(download_name)[0]
    )





@tickets_bp.route('/<int:ticket_id>/attachments/<int:att_id>/delete', methods=['POST'], endpoint='attachments_delete')

@login_required

def attachments_delete(ticket_id: int, att_id: int):

    ticket = Ticket.query.get_or_404(ticket_id)

    if not _user_can_edit_ticket(ticket):

        abort(403)



    att = Attachment.query.get_or_404(att_id)

    if att.ticket_id != ticket.id:

        abort(404)



    base = Path(current_app.config.get('UPLOADS_DIR', 'uploads'))

    fpath = base / 'tickets' / str(ticket.id) / att.stored_name

    try:

        if fpath.exists():

            fpath.unlink()

    except Exception:

        pass



    # AUDIT: remoo de anexo

    write_audit(

        entity_type="TicketAttachment",

        entity_id=att.id,

        action="delete",

        message=f"Anexo removido do ticket #{ticket.id}",

        before={

            "ticket_id": ticket.id,

            "original_name": att.original_name,

            "stored_name": att.stored_name,

            "size": att.size,

            "content_type": att.content_type

        },

        after=None

    )



    db.session.delete(att)

    db.session.commit()

    flash('Anexo removido.', 'success')

    return redirect(url_for('tickets.ticket_detail', ticket_id=ticket.id))





# ============================

# Excluso do chamado

# ============================



@tickets_bp.route('/<int:ticket_id>/delete', methods=['POST'], endpoint='delete_ticket')

@login_required

def delete_ticket(ticket_id: int):

    """

    Exclui o chamado e seus arquivos fsicos.

    Necessrio para o boto de excluso no detail.html.

    """

    ticket = Ticket.query.get_or_404(ticket_id)

    if not _user_can_edit_ticket(ticket):

        abort(403)



    # captura dados principais para auditoria antes da deleo

    before = {

        "id": ticket.id,

        "title": ticket.title,

        "status": ticket.status,

        "priority": ticket.priority,

        "user_id": ticket.user_id,

        "assignee_id": getattr(ticket, 'assignee_id', None) or getattr(ticket, 'agent_id', None)

    }



    # tenta apagar arquivos fsicos

    base = Path(current_app.config.get('UPLOADS_DIR', 'uploads'))

    folder = base / 'tickets' / str(ticket.id)

    try:

        if folder.exists() and folder.is_dir():

            for p in folder.iterdir():

                try:

                    p.unlink()

                except Exception:

                    pass

            try:

                folder.rmdir()

            except Exception:

                pass

    except Exception:

        pass



    # AUDIT: deleo do ticket

    write_audit(

        entity_type="Ticket",

        entity_id=ticket.id,

        action="delete",

        message=f"Chamado '{ticket.title}' excludo",

        before=before,

        after=None

    )



    db.session.delete(ticket)

    db.session.commit()

    flash(f'Chamado #{ticket.id} excludo.', 'success')

    return redirect(url_for('tickets.dashboard'))





