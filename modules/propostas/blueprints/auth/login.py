"""Rotas de login e logout."""
from __future__ import annotations

from urllib.parse import urlparse, urljoin

from flask import (
    render_template, redirect, url_for,
    flash, request, session, current_app,
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from pathlib import Path
import time
from werkzeug.security import check_password_hash

from . import auth_bp         # Blueprint criado em __init__.py
from .permissions_utils import (
    effective_permissions,
    normalize_role_key,
    normalize_permissions,
    resolve_role_meta,
)
from ...models import User

ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def _is_safe_url(target: str) -> bool:
    """Return True only when 'target' is a relative URL or matches the current host."""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def _avatar_upload_dir() -> Path:
    static_dir = Path(current_app.static_folder)
    target = static_dir / "uploads" / "avatars"
    target.mkdir(parents=True, exist_ok=True)
    return target



@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    current_app.logger.info("auth.login accessed method=%s", request.method)

    if request.method == "POST":
        login_identifier = (request.form.get("usuario") or request.form.get("email") or "").strip()
        senha_form = request.form.get("senha") or request.form.get("password")

        user = None
        if login_identifier:
            user = User.query.filter_by(usuario=login_identifier).first()
            if not user:
                user = User.query.filter(User.email.ilike(login_identifier)).first()

        if user and senha_form and check_password_hash(user.password_hash, senha_form):
            session.clear()
            login_user(user)

            role_key = normalize_role_key(user.tipo or user.role or "usuario")
            role_label, role_initials = resolve_role_meta(role_key)

            perms = effective_permissions(user)

            session.update(
                {
                    "usuario_id": user.id,
                    "usuario": user.usuario,
                    "nome": user.nome_completo,
                    "email": user.email,
                    "tipo": role_key,
                    "role_label": role_label,
                    "role_initials": role_initials,
                    "prox_num": user.prox_num or 1,
                    "avatar_path": user.avatar_path,
                    "phone": user.phone or '',
                    "extra_phones": user.extra_phones or [],
                    "permissions": perms,
                }
            )
            session.permanent = True

            flash("Login realizado com sucesso!", "success")
            next_url = request.args.get("next")
            if not next_url or not _is_safe_url(next_url):
                next_url = url_for("index")
            return redirect(next_url)

        flash("Usuário ou senha inválidos.", "danger")

    current_app.logger.info("Rendering auth/login.html template")
    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    logout_user()
    session.clear()
    flash("Logout realizado com sucesso.", "info")
    return redirect(url_for("auth_bp.login"))


@auth_bp.route("/profile/avatar", methods=["POST"])
@login_required
def update_avatar():
    file = request.files.get("avatar")
    filename = (file.filename or "") if file else ""
    ext = filename.rsplit(".", 1)[-1].lower() if file and "." in filename else ""

    if file and not filename:
        file = None
        filename = ""
        ext = ""

    if file and ext not in ALLOWED_AVATAR_EXTENSIONS:
        flash("Formatos permitidos: png, jpg, jpeg, webp.", "danger")
        return redirect(request.referrer or url_for("index"))

    phone_raw = (request.form.get("phone") or "").strip()
    current_phone = current_user.phone or ""
    phone_changed = False
    if phone_raw != current_phone:
        current_user.phone = phone_raw or None
        session["phone"] = phone_raw
        phone_changed = True

    extra_submitted = [value.strip() for value in request.form.getlist("extra_phones[]") if value.strip()]
    extras_changed = extra_submitted != (current_user.extra_phones or [])
    if extras_changed:
        current_user.extra_phones = extra_submitted
        session["extra_phones"] = extra_submitted

    avatar_updated = False
    if file:
        safe_name = secure_filename(f"avatar_{current_user.id}_{int(time.time())}.{ext}")
        target_dir = _avatar_upload_dir()
        destination = target_dir / safe_name
        file.save(destination)

        if current_user.avatar_path:
            old = Path(current_app.static_folder) / current_user.avatar_path
            try:
                old.unlink(missing_ok=True)
            except Exception:
                pass

        relative_path = f"uploads/avatars/{safe_name}"
        current_user.avatar_path = relative_path
        session["avatar_path"] = relative_path
        avatar_updated = True

    if not phone_changed and not extras_changed and not avatar_updated:
        flash("Nenhuma alteração realizada.", "info")
        return redirect(request.referrer or url_for("index"))

    from extensions import db  # import tardio para evitar ciclo

    db.session.commit()
    flash("Perfil atualizado com sucesso!", "success")
    return redirect(request.referrer or url_for("index"))

    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        flash("Formatos permitidos: png, jpg, jpeg, webp.", "danger")
        return redirect(request.referrer or url_for("index"))

    safe_name = secure_filename(f"avatar_{current_user.id}_{int(time.time())}.{ext}")
    target_dir = _avatar_upload_dir()
    destination = target_dir / safe_name
    file.save(destination)

    # Remove antigo
    if current_user.avatar_path:
        old = Path(current_app.static_folder) / current_user.avatar_path
        try:
            old.unlink(missing_ok=True)
        except Exception:
            pass

    relative_path = f"uploads/avatars/{safe_name}"
    current_user.avatar_path = relative_path
    session["avatar_path"] = relative_path

    from extensions import db  # import tardio para evitar ciclo

    db.session.commit()
    flash("Avatar atualizado com sucesso!", "success")
    return redirect(request.referrer or url_for("index"))
