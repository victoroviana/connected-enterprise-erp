"""Authentication blueprint utilities for the proposals module."""
from __future__ import annotations

from functools import wraps

from flask import Blueprint, flash, jsonify, redirect, request, session, url_for
from flask_login import current_user
from sqlalchemy import inspect
from werkzeug.security import generate_password_hash

from extensions import db
from ...models import User


auth_bp = Blueprint(
    "auth_bp",
    __name__,
)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated or session.get("usuario_id"):
            return f(*args, **kwargs)

        wants_html = request.accept_mimetypes.accept_html
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        if wants_html and not is_ajax:
            flash("Please log in to access this page.", "danger")
            return redirect(url_for("auth_bp.login", next=request.path))

        return jsonify(error="login_required"), 401

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        role = getattr(current_user, "tipo", None) or session.get("tipo")
        if not current_user.is_authenticated or (role or "").lower() != "admin":
            flash("Acesso restrito aos administradores.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function


def criar_admin_padrao() -> None:
    """Ensure the initial admin account exists safely."""
    import os
    import secrets
    import sys
    insp = inspect(db.engine)
    if "users" not in insp.get_table_names():
        return
    if "prox_num" not in [c["name"] for c in insp.get_columns("users")]:
        return

    admin_user = os.getenv("DEFAULT_ADMIN_USER", "admin")
    if not User.query.filter_by(usuario=admin_user).first():
        admin_pass = os.getenv("DEFAULT_ADMIN_PASSWORD")
        if not admin_pass:
            admin_pass = secrets.token_urlsafe(12)
            sys.stdout.write(f"\n[SECURITY WARNING] Created default admin user '{admin_user}' with generated password: {admin_pass}\n")
            sys.stdout.flush()
        admin = User(
            usuario=admin_user,
            nome_completo="Administrador",
            password_hash=generate_password_hash(admin_pass),
            tipo="admin",
            role="admin",
            email="admin@example.com",
            prox_num=1,
            is_active=True,
        )
        db.session.add(admin)
        db.session.commit()


from . import login  # noqa: E402,F401
from . import usuarios  # noqa: E402,F401
from . import permissoes  # noqa: E402,F401

