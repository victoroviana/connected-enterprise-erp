# modules/chamados/blueprints/central_conhecimento/routes.py
from __future__ import annotations

from contextlib import suppress
from datetime import datetime, date, timedelta
from pathlib import Path
from time import sleep
from typing import Dict, List
import mimetypes
import os
import secrets

from flask import current_app, render_template, request, jsonify, redirect, url_for, flash, session, send_file
from flask_login import login_required, current_user
from sqlalchemy import func, select, text, or_, case
from sqlalchemy.exc import OperationalError
from werkzeug.utils import secure_filename

from . import central_conhecimento_bp
from extensions import db

from utils.helpers import (
    wants_json as _wants_json,
)
from modules.propostas.models import User, Department
from modules.propostas.blueprints.auth.permissions_utils import (
    normalize_role_key,
    raw_permissions,
    current_permissions,
)
from modules.chamados.models import (
    CentralConhecimentoColumn,
    Task,
    TaskLog,
    TaskComment,
    TaskCommentAttachment,
    Subtask,
    SubtaskFlowNode,
    SubtaskFlowEdge,
)
from modules.chamados.utils.audit import write_audit

ARCHIVE_RETENTION_MINUTES = 10
PUBLIC_SCOPE_KEY = "publico"
COMMENT_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# ---------- helpers ----------


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


@central_conhecimento_bp.before_request
def _check_central_conhecimento_access():
    from flask import request
    endpoint = getattr(request, "endpoint", "") or ""
    if endpoint and not endpoint.startswith("central_conhecimento."):
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
    if role_key in ("admin", "gestor"):
        return
    if current_permissions().get("central_conhecimento"):
        return
    return _deny_access("Central de Conhecimento")


def _has_central_conhecimento_access() -> bool:
    if not current_user.is_authenticated:
        return False
    role_key = normalize_role_key(
        getattr(current_user, "tipo", None)
        or getattr(current_user, "role", None)
        or session.get("tipo")
    )
    if role_key in ("admin", "gestor"):
        return True
    return bool(current_permissions().get("central_conhecimento"))

def _user_list_for_assign() -> List[User]:
    return User.query.filter(User.is_active.is_(True)).order_by(User.nome_completo.asc(), User.email.asc()).all()

def _normalize_status(s: str) -> str:
    s = (s or "").strip().lower()
    return s if s in ("todo", "doing", "done") else "todo"

def _iso_date_or_none(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    try:
        return v.isoformat()
    except Exception:
        return None

def _add_log(task_id: int, text_: str):
    db.session.add(TaskLog(
        task_id=task_id,
        author_id=current_user.id,
        note=text_,
        log_date=date.today()
    ))

def _normalize_sub_status(s: str) -> str:
    s = (s or "").strip().lower()
    return s if s in ("open", "done") else "open"


def _allowed_comment_image(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return bool(ext) and ext in COMMENT_IMAGE_EXTS


def _file_size_of_upload(file_storage) -> int:
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


def _collect_comment_uploads() -> list:
    files = []
    for key in ("images", "images[]", "file", "files"):
        if key in request.files:
            items = request.files.getlist(key)
            if items:
                files.extend(items)
    return files


def _comment_upload_dir(task_id: int, comment_id: int) -> Path:
    base = Path(current_app.config.get("UPLOADS_DIR", "uploads"))
    return base / "central_conhecimento" / "tasks" / str(task_id) / "comments" / str(comment_id)


def _save_comment_image(task: Task, comment: TaskComment, file_storage) -> TaskCommentAttachment | None:
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None
    original_name = file_storage.filename or ""
    filename = secure_filename(original_name)
    if not filename:
        return None
    if not _allowed_comment_image(filename):
        return None

    size = _file_size_of_upload(file_storage)
    max_mb = current_app.config.get("MAX_CONTENT_MB", 20)
    if size and size > max_mb * 1024 * 1024:
        return None

    ext = os.path.splitext(filename)[1].lower()
    stored = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(6)}{ext}"
    folder = _comment_upload_dir(task.id, comment.id)
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / stored
    file_storage.save(dst)

    ctype = getattr(file_storage, "mimetype", None) or mimetypes.guess_type(filename)[0]
    att = TaskCommentAttachment(
        comment_id=comment.id,
        original_name=filename,
        stored_name=stored,
        content_type=ctype,
        size=size,
        uploader_id=current_user.id,
    )
    db.session.add(att)
    return att

def _auto_archive_done_tasks(now: datetime | None = None) -> int:
    """Archive done tasks that passed the retention window. Returns count archived."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(minutes=ARCHIVE_RETENTION_MINUTES)
    rows = (Task.query
            .filter(Task.status == "done")
            .filter(Task.archived_at.is_(None))
            .filter(or_(Task.completed_at.is_(None), Task.completed_at <= cutoff))
            .all())
    archived = 0
    touched = False
    for task in rows:
        if task.completed_at is None:
            task.completed_at = task.updated_at or task.created_at or now
            touched = True
        if task.completed_at and task.completed_at <= cutoff:
            task.archived_at = now
            archived += 1
            touched = True
    if touched:
        db.session.commit()
    return archived


def _department_scope_data() -> tuple[list[str], dict[str, str]]:
    departments = Department.query.order_by(Department.name.asc()).all()
    keys: list[str] = []
    labels: dict[str, str] = {}
    for dept in departments:
        slug = (getattr(dept, "slug", None) or "").strip()
        if not slug:
            continue
        keys.append(slug)
        label = (getattr(dept, "name", None) or "").strip() or slug
        labels[slug] = label
    labels.setdefault(PUBLIC_SCOPE_KEY, "Publico")
    return keys, labels


def _user_department_slugs(user: User) -> list[str]:
    slugs: list[str] = []
    try:
        if getattr(user, "departments", None):
            for dept in user.departments:
                slug = (getattr(dept, "slug", None) or "").strip()
                if slug and slug not in slugs:
                    slugs.append(slug)
    except Exception:
        slugs = []
    if not slugs and getattr(user, "department", None):
        slug = (getattr(user.department, "slug", None) or "").strip()
        if slug:
            slugs.append(slug)
    return slugs


def _allowed_scope_keys(user: User, dept_keys: list[str] | None = None) -> list[str]:
    if dept_keys is None:
        dept_keys, _ = _department_scope_data()
    role_key = normalize_role_key(getattr(user, "tipo", None) or getattr(user, "role", None))
    if role_key in ("admin", "gestor"):
        allowed = list(dept_keys)
    else:
        user_slugs = set(_user_department_slugs(user))
        allowed = [key for key in dept_keys if key in user_slugs]
    if PUBLIC_SCOPE_KEY not in allowed:
        allowed.append(PUBLIC_SCOPE_KEY)
    return allowed


def _default_scope_key(allowed: list[str]) -> str:
    for key in allowed:
        if key != PUBLIC_SCOPE_KEY:
            return key
    return PUBLIC_SCOPE_KEY


def _can_access_task(task: Task, allowed_scopes: list[str], role_key: str) -> bool:
    if role_key == "admin":
        return True
    scope_key = (task.scope_key or "").strip() or PUBLIC_SCOPE_KEY
    if scope_key not in allowed_scopes:
        return False
    visibility = (task.visibility or "public").lower()
    if visibility == "private":
        return task.author_id == current_user.id
    return True


def _resolve_scope_key(requested: str | None, allowed_scopes: list[str], role_key: str) -> str | None:
    candidate = (requested or "").strip()
    if candidate:
        if candidate in allowed_scopes:
            return candidate
    if not allowed_scopes:
        return None
    return _default_scope_key(allowed_scopes)


# ---------- board (HTML) ----------
@central_conhecimento_bp.route("/", methods=["GET"], endpoint="board")
@login_required
def board():
    if not _has_central_conhecimento_access():
        return _deny_access("Central de Conhecimento")
    agents = _user_list_for_assign()
    dept_keys, scope_labels = _department_scope_data()
    allowed_scopes = _allowed_scope_keys(current_user, dept_keys)
    scope_options = [{"key": key, "label": scope_labels.get(key, key)} for key in allowed_scopes]
    default_scope = _default_scope_key(allowed_scopes)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    is_admin = (role_key == "admin")
    return render_template(
        "chamados/central_conhecimento/board.html",
        agents=agents,
        scope_options=scope_options,
        default_scope=default_scope,
        public_scope_key=PUBLIC_SCOPE_KEY,
        can_create=bool(scope_options),
        is_admin=is_admin,
    )

@central_conhecimento_bp.route("/historico", methods=["GET"], endpoint="history")
@login_required
def history():
    if not _has_central_conhecimento_access():
        return _deny_access("Central de Conhecimento")
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    dept_keys, scope_labels = _department_scope_data()
    allowed_scopes = _allowed_scope_keys(current_user, dept_keys)
    query = Task.query.filter(Task.archived_at.isnot(None))
    if role_key != "admin":
        if not allowed_scopes:
            tasks = []
            return render_template("chamados/central_conhecimento/history.html", tasks=tasks, scope_labels=scope_labels)
        if PUBLIC_SCOPE_KEY in allowed_scopes:
            query = query.filter(
                or_(Task.scope_key.in_(allowed_scopes), Task.scope_key.is_(None), Task.scope_key == "")
            )
        else:
            query = query.filter(Task.scope_key.in_(allowed_scopes))
        query = query.filter(
            or_(Task.visibility.is_(None), Task.visibility != "private", Task.author_id == current_user.id)
        )
    tasks = query.order_by(Task.archived_at.desc(), Task.completed_at.desc(), Task.id.desc()).all()
    return render_template(
        "chamados/central_conhecimento/history.html",
        tasks=tasks,
        scope_labels=scope_labels,
    )


# ---------- API: listar tarefas ----------
@central_conhecimento_bp.route("/api/tasks", methods=["GET"], endpoint="api_list_tasks")
@login_required
def api_list_tasks():
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    dept_keys, scope_labels = _department_scope_data()
    allowed_scopes = _allowed_scope_keys(current_user, dept_keys)
    scope_key = _resolve_scope_key(request.args.get("scope_key"), allowed_scopes, role_key)
    if not scope_key:
        return jsonify({"scope_key": None, "columns": []})

    columns = (
        CentralConhecimentoColumn.query.filter(CentralConhecimentoColumn.scope_key == scope_key)
        .order_by(CentralConhecimentoColumn.position.asc(), CentralConhecimentoColumn.id.asc())
        .all()
    )
    if not columns:
        return jsonify({"scope_key": scope_key, "columns": []})

    author_ids = {c.author_id for c in columns if c.author_id}
    author_map = {}
    if author_ids:
        authors = User.query.filter(User.id.in_(author_ids)).all()
        author_map = {
            u.id: (u.nome_completo or u.usuario or u.email)
            for u in authors
        }

    column_ids = [c.id for c in columns]
    if column_ids:
        with suppress(Exception):
            db.session.execute(
                text(
                    "UPDATE tasks SET column_id = :col_id "
                    "WHERE column_id IS NULL AND archived_at IS NULL AND (scope_key = :scope_key OR scope_key IS NULL OR scope_key = '')"
                ),
                {"col_id": column_ids[0], "scope_key": scope_key},
            )
            db.session.commit()

    query = Task.query.filter(Task.archived_at.is_(None), Task.column_id.in_(column_ids))
    if role_key != "admin":
        query = query.filter(
            or_(Task.visibility.is_(None), Task.visibility != "private", Task.author_id == current_user.id)
        )
    rows = query.order_by(Task.column_id.asc(), Task.position.asc(), Task.id.asc()).all()
    task_ids = [r.id for r in rows]

    comment_counts: dict[int, int] = {}
    if task_ids:
        counts = (
            db.session.query(TaskComment.task_id, func.count(TaskComment.id))
            .filter(TaskComment.task_id.in_(task_ids))
            .group_by(TaskComment.task_id)
            .all()
        )
        comment_counts = {task_id: count for task_id, count in counts}

    subtask_counts: dict[int, tuple[int, int]] = {}
    if task_ids:
        s_counts = (
            db.session.query(
                Subtask.task_id,
                func.count(Subtask.id),
                func.sum(case((Subtask.status == 'done', 1), else_=0))
            )
            .filter(Subtask.task_id.in_(task_ids))
            .group_by(Subtask.task_id)
            .all()
        )
        subtask_counts = {tid: (total, int(done or 0)) for tid, total, done in s_counts}

    def dump(t: Task):
        scope_key = (t.scope_key or "").strip() or PUBLIC_SCOPE_KEY
        return {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "position": t.position,
            "due_date": _iso_date_or_none(t.due_date),
            "scope_key": scope_key,
            "scope_label": scope_labels.get(scope_key, scope_key or "Geral"),
            "visibility": (t.visibility or "public"),
            "assignee_id": t.assignee_id,
            "assignee_name": (t.assignee.name if t.assignee and t.assignee.name else (t.assignee.email if t.assignee else None)),
            "author_id": t.author_id,
            "column_id": t.column_id,
            "comment_count": comment_counts.get(t.id, 0),
            "subtask_total": subtask_counts.get(t.id, (0,0))[0],
            "subtask_done": subtask_counts.get(t.id, (0,0))[1],
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }

    tasks_by_column: Dict[int, List[Dict]] = {c.id: [] for c in columns}
    for r in rows:
        tasks_by_column.setdefault(r.column_id or 0, []).append(dump(r))

    payload_columns = []
    for col in columns:
        payload_columns.append(
            {
                "id": col.id,
                "title": col.title,
                "position": col.position,
                "scope_key": col.scope_key,
                "author_id": col.author_id,
                "author_name": author_map.get(col.author_id),
                "tasks": tasks_by_column.get(col.id, []),
            }
        )

    return jsonify({"scope_key": scope_key, "columns": payload_columns})

# ---------- API: criar tarefa ----------
@central_conhecimento_bp.route("/api/tasks", methods=["POST"], endpoint="api_create_task")
@login_required
def api_create_task():
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title é obrigatório"}), 400

    description = (data.get("description") or "").strip() or None
    status = _normalize_status(data.get("status") or "todo")

    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not allowed_scopes:
        return jsonify({"error": "forbidden"}), 403

    column_id = data.get("column_id")
    try:
        column_id = int(column_id) if column_id else None
    except Exception:
        column_id = None
    scope_key = (data.get("scope_key") or data.get("scope") or "").strip()
    column = None
    if column_id:
        column = CentralConhecimentoColumn.query.get(column_id)
        if not column:
            return jsonify({"error": "column_not_found"}), 404
        scope_key = column.scope_key
    if not scope_key:
        scope_key = _default_scope_key(allowed_scopes)

    if role_key != "admin" and scope_key not in allowed_scopes:
        return jsonify({"error": "scope_forbidden"}), 403

    if not column and scope_key:
        column = (
            CentralConhecimentoColumn.query.filter(CentralConhecimentoColumn.scope_key == scope_key)
            .order_by(CentralConhecimentoColumn.position.asc(), CentralConhecimentoColumn.id.asc())
            .first()
        )
    if not column:
        return jsonify({"error": "column_required"}), 400

    visibility = (data.get("visibility") or "public").strip().lower()
    if visibility not in ("public", "private"):
        return jsonify({"error": "visibility inválida"}), 400

    due_date = data.get("due_date")
    if due_date:
        try:
            due_date = datetime.strptime(due_date, "%Y-%m-%d").date()
        except Exception:
            return jsonify({"error": "due_date inválido (use YYYY-MM-DD)"}), 400
    else:
        due_date = None

    assignee_id = data.get("assignee_id")
    try:
        assignee_id = int(assignee_id) if assignee_id else None
    except Exception:
        assignee_id = None

    last_pos = db.session.scalar(
        select(func.coalesce(func.max(Task.position), 0)).where(Task.column_id == column.id)
    ) or 0

    t = Task(
        title=title,
        description=description,
        status=status,
        position=last_pos + 1,
        due_date=due_date,
        assignee_id=assignee_id,
        scope_key=scope_key or column.scope_key,
        visibility=visibility,
        author_id=current_user.id,
        column_id=column.id,
        completed_at=datetime.utcnow() if status == "done" else None,
    )
    db.session.add(t)
    db.session.flush()
    _add_log(t.id, f"created in {status}")
    write_audit(entity_type="Task", entity_id=t.id, action="create",
                message=f"Task criada em {status}", after=t.as_dict())
    db.session.commit()

    return jsonify({"id": t.id}), 201


# ---------- API: comentarios ----------
@central_conhecimento_bp.route("/api/tasks/<int:task_id>/comments", methods=["GET"], endpoint="api_list_comments")
@login_required
def api_list_comments(task_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    task = Task.query.get_or_404(task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403

    rows = (
        TaskComment.query
        .filter(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at.asc(), TaskComment.id.asc())
        .all()
    )
    author_ids = {row.author_id for row in rows if row.author_id}
    author_map = {}
    if author_ids:
        authors = User.query.filter(User.id.in_(author_ids)).all()
        author_map = {
            u.id: (u.nome_completo or u.usuario or u.email)
            for u in authors
        }
    comment_ids = [row.id for row in rows]
    attachments_by_comment: dict[int, list[dict]] = {}
    if comment_ids:
        attachments = (
            TaskCommentAttachment.query
            .filter(TaskCommentAttachment.comment_id.in_(comment_ids))
            .order_by(TaskCommentAttachment.id.asc())
            .all()
        )
        for att in attachments:
            attachments_by_comment.setdefault(att.comment_id, []).append(
                {
                    "id": att.id,
                    "name": att.original_name or att.stored_name,
                    "url": url_for("central_conhecimento.comment_attachment", attachment_id=att.id),
                }
            )

    payload = []
    for row in rows:
        payload.append(
            {
                "id": row.id,
                "task_id": row.task_id,
                "author_id": row.author_id,
                "author_name": author_map.get(row.author_id),
                "body": row.body,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "can_edit": row.author_id == current_user.id,
                "attachments": attachments_by_comment.get(row.id, []),
            }
        )
    return jsonify(payload)


@central_conhecimento_bp.route("/api/tasks/<int:task_id>/comments", methods=["POST"], endpoint="api_create_comment")
@login_required
def api_create_comment(task_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    task = Task.query.get_or_404(task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403

    body = (request.form.get("body") or "").strip()
    uploads = _collect_comment_uploads()
    if not body and not uploads:
        return jsonify({"error": "Informe um comentario ou envie uma imagem."}), 400
    max_mb = current_app.config.get("MAX_CONTENT_MB", 20)
    for f in uploads:
        if not f or not getattr(f, "filename", ""):
            continue
        filename = secure_filename(f.filename or "")
        if not filename or not _allowed_comment_image(filename):
            return jsonify({"error": "Imagem inválida. Use JPG, PNG, GIF ou WEBP."}), 400
        size = _file_size_of_upload(f)
        if size and size > max_mb * 1024 * 1024:
            return jsonify({"error": f"Imagem excede {max_mb}MB."}), 400

    comment = TaskComment(task_id=task.id, author_id=current_user.id, body=body)
    db.session.add(comment)
    db.session.flush()

    saved = 0
    for f in uploads:
        if _save_comment_image(task, comment, f):
            saved += 1

    write_audit(
        entity_type="TaskComment",
        entity_id=comment.id,
        action="create",
        message=f"Comentario criado na task #{task.id}",
        after={"task_id": task.id, "body": (comment.body or "")[:500], "images": saved},
    )
    db.session.commit()

    return jsonify({"id": comment.id}), 201


@central_conhecimento_bp.route("/api/comments/<int:comment_id>", methods=["PUT"], endpoint="api_update_comment")
@login_required
def api_update_comment(comment_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    comment = TaskComment.query.get_or_404(comment_id)
    task = Task.query.get_or_404(comment.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    if comment.author_id != current_user.id:
        return jsonify({"error": "forbidden"}), 403

    data = request.get_json(silent=True) or {}
    new_body = (data.get("body") or "").strip()
    if not new_body:
        return jsonify({"error": "Informe um comentario."}), 400
    if new_body == comment.body:
        return jsonify({"ok": True, "changed": False})

    before = {"body": comment.body}
    comment.body = new_body
    write_audit(
        entity_type="TaskComment",
        entity_id=comment.id,
        action="update",
        message="Comentario atualizado",
        before=before,
        after={"body": (comment.body or "")[:500]},
    )
    db.session.commit()
    return jsonify({"ok": True, "changed": True})


@central_conhecimento_bp.route("/api/comments/<int:comment_id>", methods=["DELETE"], endpoint="api_delete_comment")
@login_required
def api_delete_comment(comment_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    comment = TaskComment.query.get_or_404(comment_id)
    task = Task.query.get_or_404(comment.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    if comment.author_id != current_user.id:
        return jsonify({"error": "forbidden"}), 403

    attachments = TaskCommentAttachment.query.filter_by(comment_id=comment.id).all()
    for att in attachments:
        fpath = _comment_upload_dir(task.id, comment.id) / att.stored_name
        try:
            if fpath.exists():
                fpath.unlink()
        except Exception:
            pass

    before = {"task_id": comment.task_id, "body": (comment.body or "")[:500]}
    db.session.delete(comment)
    write_audit(
        entity_type="TaskComment",
        entity_id=comment_id,
        action="delete",
        message="Comentario removido",
        before=before,
        after=None,
    )
    db.session.commit()
    return jsonify({"ok": True})


@central_conhecimento_bp.route(
    "/api/comment-attachments/<int:attachment_id>", methods=["DELETE"], endpoint="api_delete_comment_attachment"
)
@login_required
def api_delete_comment_attachment(attachment_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    att = TaskCommentAttachment.query.get_or_404(attachment_id)
    comment = TaskComment.query.get_or_404(att.comment_id)
    task = Task.query.get_or_404(comment.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    if comment.author_id != current_user.id:
        return jsonify({"error": "forbidden"}), 403

    fpath = _comment_upload_dir(task.id, comment.id) / att.stored_name
    try:
        if fpath.exists():
            fpath.unlink()
    except Exception:
        pass

    before = {"comment_id": comment.id, "name": att.original_name or att.stored_name}
    db.session.delete(att)
    write_audit(
        entity_type="TaskCommentAttachment",
        entity_id=attachment_id,
        action="delete",
        message="Imagem removida do comentario",
        before=before,
        after=None,
    )
    db.session.commit()
    return jsonify({"ok": True})


@central_conhecimento_bp.route("/comment-attachments/<int:attachment_id>", methods=["GET"], endpoint="comment_attachment")
@login_required
def comment_attachment(attachment_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    att = TaskCommentAttachment.query.get_or_404(attachment_id)
    comment = TaskComment.query.get_or_404(att.comment_id)
    task = Task.query.get_or_404(comment.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403

    stored_name = att.stored_name
    if not stored_name:
        return jsonify({"error": "not_found"}), 404

    base = Path(current_app.config.get("UPLOADS_DIR", "uploads")).resolve()
    fpath = (_comment_upload_dir(task.id, comment.id) / stored_name).resolve()
    try:
        fpath.relative_to(base)
    except ValueError:
        return jsonify({"error": "not_found"}), 404

    if not fpath.is_file():
        return jsonify({"error": "not_found"}), 404

    download_name = att.original_name or stored_name
    return send_file(
        fpath,
        as_attachment=False,
        download_name=download_name,
        mimetype=att.content_type or mimetypes.guess_type(download_name)[0],
    )


# ---------- API: colunas ----------
@central_conhecimento_bp.route("/api/columns", methods=["GET"], endpoint="api_list_columns")
@login_required
def api_list_columns():
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    scope_key = _resolve_scope_key(request.args.get("scope_key"), allowed_scopes, role_key)
    if not scope_key:
        return jsonify({"columns": []})

    cols = (
        CentralConhecimentoColumn.query.filter(CentralConhecimentoColumn.scope_key == scope_key)
        .order_by(CentralConhecimentoColumn.position.asc(), CentralConhecimentoColumn.id.asc())
        .all()
    )
    author_ids = {c.author_id for c in cols if c.author_id}
    author_map = {}
    if author_ids:
        authors = User.query.filter(User.id.in_(author_ids)).all()
        author_map = {
            u.id: (u.nome_completo or u.usuario or u.email)
            for u in authors
        }
    payload = []
    for c in cols:
        data = c.as_dict()
        data["author_name"] = author_map.get(c.author_id)
        payload.append(data)
    return jsonify({"scope_key": scope_key, "columns": payload})


@central_conhecimento_bp.route("/api/columns", methods=["POST"], endpoint="api_create_column")
@login_required
def api_create_column():
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title é obrigatório"}), 400

    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    scope_key = _resolve_scope_key(data.get("scope_key"), allowed_scopes, role_key)
    if not scope_key:
        return jsonify({"error": "scope_forbidden"}), 403

    total = db.session.scalar(
        select(func.count(CentralConhecimentoColumn.id)).where(CentralConhecimentoColumn.scope_key == scope_key)
    ) or 0
    max_pos = db.session.scalar(
        select(func.coalesce(func.max(CentralConhecimentoColumn.position), 0)).where(CentralConhecimentoColumn.scope_key == scope_key)
    ) or 0

    col = CentralConhecimentoColumn(
        title=title,
        scope_key=scope_key,
        position=max_pos + 1,
        visibility="public",
        author_id=current_user.id,
    )
    db.session.add(col)
    db.session.commit()
    return jsonify(col.as_dict()), 201


@central_conhecimento_bp.route("/api/columns/<int:col_id>", methods=["PUT"], endpoint="api_update_column")
@login_required
def api_update_column(col_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    col = CentralConhecimentoColumn.query.get_or_404(col_id)
    data = request.get_json(silent=True) or {}
    
    if "title" in data:
        col.title = data["title"].strip()
    if "position" in data:
        col.position = int(data["position"])
    
    db.session.commit()
    return jsonify(col.as_dict())


@central_conhecimento_bp.route("/api/columns/<int:column_id>", methods=["DELETE"], endpoint="api_delete_column")
@login_required
def api_delete_column(column_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    col = CentralConhecimentoColumn.query.get_or_404(column_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and col.scope_key not in allowed_scopes:
        return jsonify({"error": "scope_forbidden"}), 403

    if role_key != "admin" and col.author_id != current_user.id:
        return jsonify({"error": "only_owner_can_delete"}), 403

    target_col = (
        CentralConhecimentoColumn.query.filter(
            CentralConhecimentoColumn.scope_key == col.scope_key,
            CentralConhecimentoColumn.id != col.id,
        )
        .order_by(CentralConhecimentoColumn.position.asc(), CentralConhecimentoColumn.id.asc())
        .first()
    )
    if target_col:
        Task.query.filter(Task.column_id == col.id).update(
            {"column_id": target_col.id},
            synchronize_session=False,
        )
    else:
        Task.query.filter(Task.column_id == col.id).update(
            {"column_id": None},
            synchronize_session=False,
        )

    db.session.delete(col)
    db.session.commit()
    return jsonify({"ok": True})

# ---------- API: atualizar tarefa ----------
@central_conhecimento_bp.route("/api/tasks/<int:task_id>", methods=["PUT"], endpoint="api_update_task")
@login_required
def api_update_task(task_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    t = Task.query.get_or_404(task_id)
    data = request.get_json(silent=True) or {}
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(t, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403

    before = t.as_dict()
    changed = []

    if "title" in data:
        new_title = (data["title"] or "").strip()
        if new_title and new_title != t.title:
            t.title = new_title
            changed.append("title")
    if "description" in data:
        new_desc = (data["description"] or "").strip() or None
        if new_desc != (t.description or None):
            t.description = new_desc
            changed.append("description")
    if "due_date" in data:
        v = data["due_date"]
        if v:
            try:
                new_dd = datetime.strptime(v, "%Y-%m-%d").date()
            except Exception:
                return jsonify({"error": "due_date inválido (use YYYY-MM-DD)"}), 400
        else:
            new_dd = None
        if new_dd != (t.due_date or None):
            t.due_date = new_dd
            changed.append("due_date")
    if "assignee_id" in data:
        v = data["assignee_id"]
        try:
            new_assignee = int(v) if v else None
        except Exception:
            new_assignee = None
        if new_assignee != (t.assignee_id or None):
            t.assignee_id = new_assignee
            changed.append("assignee")

    if "scope_key" in data:
        new_scope = (data.get("scope_key") or "").strip()
        if not new_scope:
            new_scope = t.scope_key or PUBLIC_SCOPE_KEY
        if role_key != "admin" and new_scope not in allowed_scopes:
            return jsonify({"error": "scope_forbidden"}), 403
        if new_scope != (t.scope_key or PUBLIC_SCOPE_KEY):
            t.scope_key = new_scope
            changed.append("scope")

    if "visibility" in data:
        new_vis = (data.get("visibility") or "").strip().lower()
        if new_vis not in ("public", "private"):
            return jsonify({"error": "visibility inválida"}), 400
        if new_vis == "private" and role_key != "admin" and t.author_id != current_user.id:
            return jsonify({"error": "visibility_forbidden"}), 403
        if new_vis != (t.visibility or "public"):
            t.visibility = new_vis
            changed.append("visibility")

    if changed:
        _add_log(t.id, f"updated: {', '.join(changed)}")
        write_audit(entity_type="Task", entity_id=t.id, action="update",
                    message=f"Campos: {', '.join(changed)}",
                    before=before, after=t.as_dict())

    db.session.commit()
    return jsonify({"ok": True})

# ---------- API: mover tarefa ----------
@central_conhecimento_bp.route("/api/tasks/<int:task_id>/move", methods=["PUT"], endpoint="api_move_task")
@login_required
def api_move_task(task_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)

    for attempt in (1, 2):
        try:
            with db.session.begin_nested():
                t: Task | None = (
                    db.session.query(Task)
                    .filter(Task.id == task_id)
                    .with_for_update()
                    .first()
                )
                if not t:
                    return jsonify({"error": "not_found"}), 404
                if role_key != "admin" and not _can_access_task(t, allowed_scopes, role_key):
                    return jsonify({"error": "forbidden"}), 403

                new_column_id = payload.get("column_id", t.column_id)
                try:
                    new_column_id = int(new_column_id) if new_column_id else None
                except Exception:
                    new_column_id = t.column_id
                if not new_column_id:
                    return jsonify({"error": "column_required"}), 400
                new_column = CentralConhecimentoColumn.query.get(new_column_id)
                if not new_column:
                    return jsonify({"error": "column_not_found"}), 404
                if role_key != "admin" and new_column.scope_key not in allowed_scopes:
                    return jsonify({"error": "scope_forbidden"}), 403
                try:
                    new_position = int(payload.get("position", t.position))
                    if new_position < 1:
                        new_position = 1
                except Exception:
                    new_position = t.position

                old_column_id = t.column_id
                old_position = t.position

                if new_column_id == old_column_id and new_position == old_position:
                    return jsonify({"ok": True})

                if new_column_id != old_column_id:
                    db.session.execute(
                        text(
                            "UPDATE tasks SET position = position - 1 "
                            "WHERE column_id = :col AND position > :pos"
                        ),
                        {"col": old_column_id, "pos": old_position},
                    )
                    max_pos = db.session.scalar(
                        select(func.coalesce(func.max(Task.position), 0))
                        .where(Task.column_id == new_column_id)
                    ) or 0
                    if new_position > max_pos + 1:
                        new_position = max_pos + 1

                    db.session.execute(
                        text(
                            "UPDATE tasks SET position = position + 1 "
                            "WHERE column_id = :col AND position >= :pos"
                        ),
                        {"col": new_column_id, "pos": new_position},
                    )

                    t.position = new_position
                    t.column_id = new_column_id
                    _add_log(t.id, f"moved col#{old_column_id}:{old_position} -> col#{new_column_id}:{new_position}")
                    write_audit(entity_type="Task", entity_id=t.id, action="move",
                                message=f"col#{old_column_id}:{old_position} -> col#{new_column_id}:{new_position}",
                                before={"column_id": old_column_id, "position": old_position},
                                after={"column_id": t.column_id, "position": t.position})
                else:
                    if new_position > old_position:
                        db.session.execute(
                            text(
                                "UPDATE tasks SET position = position - 1 "
                                "WHERE column_id = :col AND position > :old AND position <= :new"
                            ),
                            {"col": new_column_id, "old": old_position, "new": new_position},
                        )
                    else:
                        db.session.execute(
                            text(
                                "UPDATE tasks SET position = position + 1 "
                                "WHERE column_id = :col AND position >= :new AND position < :old"
                            ),
                            {"col": new_column_id, "old": old_position, "new": new_position},
                        )
                    t.position = new_position
                    _add_log(t.id, f"reordered col#{new_column_id} -> #{new_position}")
                    write_audit(entity_type="Task", entity_id=t.id, action="move",
                                message=f"reordered col#{new_column_id} -> #{new_position}",
                                before={"position": old_position},
                                after={"position": t.position})

            db.session.commit()
            return jsonify({"ok": True})

        except OperationalError as e:
            if "1020" in str(e.orig) and attempt == 1:
                db.session.rollback()
                sleep(0.05)
                continue
            db.session.rollback()
            return jsonify({"ok": False, "error": "conflict", "detail": "record_changed"}), 409
        except Exception:
            db.session.rollback()
            return jsonify({"ok": False, "error": "server_error"}), 500

# ---------- API: concluir tarefa ----------
@central_conhecimento_bp.route("/api/tasks/<int:task_id>/complete", methods=["POST"], endpoint="api_complete_task")
@login_required
def api_complete_task(task_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    t = Task.query.get_or_404(task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(t, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403

    now = datetime.utcnow()
    t.completed_at = now
    t.archived_at = now
    t.status = "done"
    _add_log(t.id, "completed")
    write_audit(entity_type="Task", entity_id=t.id, action="complete",
                message="Task concluída e arquivada", after=t.as_dict())
    db.session.commit()
    return jsonify({"ok": True})

# ---------- API: deletar tarefa ----------
@central_conhecimento_bp.route("/api/tasks/<int:task_id>", methods=["DELETE"], endpoint="api_delete_task")
@login_required
def api_delete_task(task_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403

    t = Task.query.get_or_404(task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(t, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403

    role = (getattr(current_user, "role", "") or "").lower()
    visibility = (t.visibility or "public").lower()
    if visibility == "private" and role_key != "admin" and t.author_id != current_user.id:
        return jsonify({"error": "forbidden"}), 403
    if role not in ("gestor", "admin") and t.assignee_id != current_user.id and t.author_id != current_user.id:
        return jsonify({"error": "forbidden"}), 403

    st, pos = t.status, t.position

    _add_log(task_id, "deleted")
    db.session.flush()

    db.session.delete(t)
    db.session.flush()

    db.session.execute(
        text(
            "UPDATE tasks SET position = position - 1 "
            "WHERE status = :st AND position > :pos"
        ),
        {"st": st, "pos": pos},
    )

    write_audit(entity_type="Task", entity_id=task_id, action="delete",
                message=f"Task removida de {st}#{pos}",
                before={"status": st, "position": pos}, after=None)

    db.session.commit()
    return jsonify({"ok": True})

# =========================
# SubTarefas
# =========================
@central_conhecimento_bp.route("/api/tasks/<int:task_id>/subtasks", methods=["GET"], endpoint="api_list_subtasks")
@login_required
def api_list_subtasks(task_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error":"forbidden"}), 403
    task = Task.query.get_or_404(task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    rows = (Subtask.query
            .filter(Subtask.task_id == task_id)
            .order_by(Subtask.position.asc(), Subtask.id.asc())
            .all())
    return jsonify([r.as_dict() for r in rows])

@central_conhecimento_bp.route("/api/tasks/<int:task_id>/subtasks", methods=["POST"], endpoint="api_create_subtask")
@login_required
def api_create_subtask(task_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error":"forbidden"}), 403
    task = Task.query.get_or_404(task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error":"title é obrigatório"}), 400

    last_pos = db.session.scalar(
        select(func.coalesce(func.max(Subtask.position), 0)).where(Subtask.task_id == task_id)
    ) or 0

    work_date = data.get("work_date")
    if work_date:
        try:
            work_date = datetime.strptime(work_date, "%Y-%m-%d").date()
        except Exception:
            return jsonify({"error":"work_date inválido (use YYYY-MM-DD)"}), 400
    else:
        work_date = None

    assignee_id = data.get("assignee_id")
    try:
        assignee_id = int(assignee_id) if assignee_id else None
    except Exception:
        assignee_id = None

    s = Subtask(
        task_id=task_id,
        title=title,
        description=(data.get("description") or "").strip() or None,
        work_date=work_date,
        status=_normalize_sub_status(data.get("status")),
        position=last_pos + 1,
        assignee_id=assignee_id,
    )
    db.session.add(s)
    db.session.commit()

    write_audit(entity_type="Subtask", entity_id=s.id, action="create",
                message=f"Subtask criada para task #{task_id}", after=s.as_dict())

    return jsonify(s.as_dict()), 201

@central_conhecimento_bp.route("/api/subtasks/<int:subtask_id>", methods=["PUT"], endpoint="api_update_subtask")
@login_required
def api_update_subtask(subtask_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error":"forbidden"}), 403
    s = Subtask.query.get_or_404(subtask_id)
    task = Task.query.get_or_404(s.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    before = s.as_dict()
    changed = []

    if "title" in data:
        new_t = (data["title"] or "").strip()
        if new_t and new_t != s.title:
            s.title = new_t; changed.append("title")
    if "description" in data:
        new_d = (data["description"] or "").strip() or None
        if new_d != (s.description or None):
            s.description = new_d; changed.append("description")
    if "status" in data:
        new_st = _normalize_sub_status(data["status"])
        if new_st != s.status:
            s.status = new_st; changed.append("status")
    if "work_date" in data:
        wd = data["work_date"]
        if wd:
            try:
                new_wd = datetime.strptime(wd, "%Y-%m-%d").date()
            except Exception:
                return jsonify({"error":"work_date inválido (use YYYY-MM-DD)"}), 400
        else:
            new_wd = None
        if (s.work_date or None) != new_wd:
            s.work_date = new_wd; changed.append("work_date")
    if "assignee_id" in data:
        v = data["assignee_id"]
        try:
            new_assignee = int(v) if v else None
        except Exception:
            new_assignee = None
        if new_assignee != (s.assignee_id or None):
            s.assignee_id = new_assignee; changed.append("assignee")

    if "position" in data:
        try:
            new_pos = int(data["position"])
            if new_pos < 1: new_pos = 1
        except Exception:
            new_pos = s.position
        if new_pos != s.position:
            task_id = s.task_id
            old_pos = s.position
            if new_pos > old_pos:
                db.session.execute(
                    text(
                        "UPDATE subtasks SET position = position - 1 "
                        "WHERE task_id = :tid AND position > :old AND position <= :new"
                    ),
                    {"tid": task_id, "old": old_pos, "new": new_pos},
                )
            else:
                db.session.execute(
                    text(
                        "UPDATE subtasks SET position = position + 1 "
                        "WHERE task_id = :tid AND position >= :new AND position < :old"
                    ),
                    {"tid": task_id, "old": old_pos, "new": new_pos},
                )
            s.position = new_pos
            changed.append("position")

    if changed:
        write_audit(entity_type="Subtask", entity_id=s.id, action="update",
                    message=f"Campos: {', '.join(changed)}",
                    before=before, after=s.as_dict())

    db.session.commit()
    return jsonify({"ok": True, "changed": changed})

@central_conhecimento_bp.route("/api/subtasks/<int:subtask_id>", methods=["DELETE"], endpoint="api_delete_subtask")
@login_required
def api_delete_subtask(subtask_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error":"forbidden"}), 403
    s = Subtask.query.get_or_404(subtask_id)
    task = Task.query.get_or_404(s.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    tid, pos = s.task_id, s.position
    write_audit(entity_type="Subtask", entity_id=subtask_id, action="delete",
                message=f"Subtask removida (task #{tid}, pos {pos})",
                before={"task_id": tid, "position": pos}, after=None)
    db.session.delete(s)
    db.session.flush()
    db.session.execute(
        text(
            "UPDATE subtasks SET position = position - 1 "
            "WHERE task_id = :tid AND position > :pos"
        ),
        {"tid": tid, "pos": pos},
    )
    db.session.commit()
    return jsonify({"ok": True})

# =========================
# FLOW: NODES
# =========================
@central_conhecimento_bp.route("/api/subtasks/<int:subtask_id>/flow/nodes", methods=["GET"], endpoint="api_flow_nodes_list")
@login_required
def api_flow_nodes_list(subtask_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403
    subtask = Subtask.query.get_or_404(subtask_id)
    task = Task.query.get_or_404(subtask.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    rows = (SubtaskFlowNode.query
            .filter(SubtaskFlowNode.subtask_id == subtask_id)
            .order_by(SubtaskFlowNode.id.asc())
            .all())
    return jsonify([r.as_dict() for r in rows])

@central_conhecimento_bp.route("/api/subtasks/<int:subtask_id>/flow/nodes", methods=["POST"], endpoint="api_flow_nodes_create")
@login_required
def api_flow_nodes_create(subtask_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403
    subtask = Subtask.query.get_or_404(subtask_id)
    task = Task.query.get_or_404(subtask.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title é obrigatório"}), 400
    shape = (data.get("shape") or "rect").lower()
    if shape not in ("rect", "diamond", "pill"):
        shape = "rect"
    color = (data.get("color") or "#e5e7eb").strip()[:16]
    try:
        x = int(data.get("x", 40)); y = int(data.get("y", 40))
    except Exception:
        x, y = 40, 40
    node = SubtaskFlowNode(subtask_id=subtask_id, title=title, shape=shape, color=color, x=x, y=y, body=(data.get("body") or None))
    db.session.add(node)
    db.session.commit()

    write_audit(entity_type="FlowNode", entity_id=node.id, action="create",
                message=f"Nó criado na subtarefa #{subtask_id}", after=node.as_dict())

    return jsonify(node.as_dict()), 201

@central_conhecimento_bp.route("/api/flow/nodes/<int:node_id>", methods=["PUT"], endpoint="api_flow_nodes_update")
@login_required
def api_flow_nodes_update(node_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403
    node = SubtaskFlowNode.query.get_or_404(node_id)
    subtask = Subtask.query.get_or_404(node.subtask_id)
    task = Task.query.get_or_404(subtask.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    before = node.as_dict()
    changed = []
    if "title" in data:
        t = (data["title"] or "").strip()
        if t and t != node.title:
            node.title = t; changed.append("title")
    if "shape" in data:
        shp = (data["shape"] or "rect").lower()
        if shp in ("rect","diamond","pill") and shp != node.shape:
            node.shape = shp; changed.append("shape")
    if "color" in data:
        col = (data["color"] or "#e5e7eb").strip()[:16]
        if col and col != node.color:
            node.color = col; changed.append("color")
    if "body" in data:
        b = (data["body"] or None)
        if b != (node.body or None):
            node.body = b; changed.append("body")
    if "x" in data or "y" in data:
        try:
            nx = int(data.get("x", node.x)); ny = int(data.get("y", node.y))
            if nx != node.x or ny != node.y:
                node.x, node.y = nx, ny; changed.append("pos")
        except Exception:
            pass
    if changed:
        db.session.commit()
        write_audit(entity_type="FlowNode", entity_id=node.id, action="update",
                    message=f"Campos: {', '.join(changed)}",
                    before=before, after=node.as_dict())
    return jsonify({"ok": True, "changed": changed})

@central_conhecimento_bp.route("/api/flow/nodes/<int:node_id>", methods=["DELETE"], endpoint="api_flow_nodes_delete")
@login_required
def api_flow_nodes_delete(node_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403
    node = SubtaskFlowNode.query.get_or_404(node_id)
    subtask = Subtask.query.get_or_404(node.subtask_id)
    task = Task.query.get_or_404(subtask.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    sub_id = node.subtask_id
    write_audit(entity_type="FlowNode", entity_id=node_id, action="delete",
                message=f"Nó removido da subtarefa #{sub_id}",
                before=node.as_dict(), after=None)
    SubtaskFlowEdge.query.filter(
        SubtaskFlowEdge.subtask_id == sub_id,
        ((SubtaskFlowEdge.from_id == node_id) | (SubtaskFlowEdge.to_id == node_id))
    ).delete(synchronize_session=False)
    db.session.delete(node)
    db.session.commit()
    return jsonify({"ok": True})

# =========================
# FLOW: EDGES
# =========================
@central_conhecimento_bp.route("/api/subtasks/<int:subtask_id>/flow/edges", methods=["GET"], endpoint="api_flow_edges_list")
@login_required
def api_flow_edges_list(subtask_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403
    subtask = Subtask.query.get_or_404(subtask_id)
    task = Task.query.get_or_404(subtask.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    rows = (SubtaskFlowEdge.query
            .filter(SubtaskFlowEdge.subtask_id == subtask_id)
            .order_by(SubtaskFlowEdge.id.asc())
            .all())
    return jsonify([r.as_dict() for r in rows])

@central_conhecimento_bp.route("/api/subtasks/<int:subtask_id>/flow/edges", methods=["POST"], endpoint="api_flow_edges_create")
@login_required
def api_flow_edges_create(subtask_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403
    subtask = Subtask.query.get_or_404(subtask_id)
    task = Task.query.get_or_404(subtask.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    try:
        from_id = int(data.get("from_id")); to_id = int(data.get("to_id"))
    except Exception:
        return jsonify({"error": "from_id/to_id inválidos"}), 400
    if from_id == to_id:
        return jsonify({"error": "from_id e to_id não podem ser iguais"}), 400
    f = SubtaskFlowNode.query.get_or_404(from_id)
    t = SubtaskFlowNode.query.get_or_404(to_id)
    if f.subtask_id != subtask_id or t.subtask_id != subtask_id:
        return jsonify({"error": "nós não pertencem a esta subtarefa"}), 400
    label = (data.get("label") or "").strip() or None

    exists = SubtaskFlowEdge.query.filter_by(subtask_id=subtask_id, from_id=from_id, to_id=to_id).first()
    if exists:
        if label != exists.label:
            before = exists.as_dict()
            exists.label = label
            db.session.commit()
            write_audit(entity_type="FlowEdge", entity_id=exists.id, action="update",
                        message=f"Aresta {from_id}->{to_id} label alterada",
                        before=before, after=exists.as_dict())
        return jsonify(exists.as_dict()), 200

    e = SubtaskFlowEdge(subtask_id=subtask_id, from_id=from_id, to_id=to_id, label=label)
    db.session.add(e)
    db.session.commit()
    write_audit(entity_type="FlowEdge", entity_id=e.id, action="link",
                message=f"Ligado {from_id} -> {to_id} (sub #{subtask_id})",
                after=e.as_dict())
    return jsonify(e.as_dict()), 201

@central_conhecimento_bp.route("/api/flow/edges/<int:edge_id>", methods=["DELETE"], endpoint="api_flow_edges_delete")
@login_required
def api_flow_edges_delete(edge_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403
    e = SubtaskFlowEdge.query.get_or_404(edge_id)
    subtask = Subtask.query.get_or_404(e.subtask_id)
    task = Task.query.get_or_404(subtask.task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403
    before = e.as_dict()
    db.session.delete(e)
    db.session.commit()
    write_audit(entity_type="FlowEdge", entity_id=edge_id, action="unlink",
                message=f"Aresta removida {before['from_id']}->{before['to_id']} (sub #{before['subtask_id']})",
                before=before, after=None)
    return jsonify({"ok": True})


@central_conhecimento_bp.route("/api/tasks/<int:task_id>/logs", methods=["GET"], endpoint="api_list_logs")
@login_required
def api_list_logs(task_id: int):
    if not _has_central_conhecimento_access():
        return jsonify({"error": "forbidden"}), 403
    task = Task.query.get_or_404(task_id)
    role_key = normalize_role_key(getattr(current_user, "tipo", None) or getattr(current_user, "role", None))
    allowed_scopes = _allowed_scope_keys(current_user)
    if role_key != "admin" and not _can_access_task(task, allowed_scopes, role_key):
        return jsonify({"error": "forbidden"}), 403

    logs = (TaskLog.query
            .filter(TaskLog.task_id == task_id)
            .order_by(TaskLog.created_at.desc(), TaskLog.id.desc())
            .all())

    author_ids = {log.author_id for log in logs if log.author_id}
    author_map = {}
    if author_ids:
        authors = User.query.filter(User.id.in_(author_ids)).all()
        author_map = {u.id: (u.nome_completo or u.usuario or u.email) for u in authors}

    payload = []
    for log in logs:
        payload.append({
            "id": log.id,
            "note": log.note,
            "log_date": log.log_date.isoformat() if log.log_date else None,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "author_name": author_map.get(log.author_id, "Sistema")
        })
    return jsonify(payload)
