"""Common decorators for propostas module blueprints."""
from functools import wraps
import unicodedata
from flask import flash, jsonify, redirect, request, session, url_for
from flask_login import current_user

from .auth.permissions_utils import normalize_role_key

from utils.helpers import (
    wants_json as _wants_json,
    normalize_dept_name as _normalize_dept_name,
)




def _deny_access(area_label: str):
    if _wants_json():
        return jsonify({"ok": False, "message": "Você não tem permissão para acessar esta área."}), 403
    flash(
        "Você não tem permissão para acessar esta área. Procure seu superior caso precise de acesso.",
        "warning",
    )
    return redirect(url_for("sem_permissao", area=area_label))




def _dept_names() -> set[str]:
    names: set[str] = set()
    try:
        for name in getattr(current_user, "department_names", []) or []:
            normalized = _normalize_dept_name(name)
            if normalized:
                names.add(normalized)
    except Exception:
        return set()
    return names


def gestor_ou_admin_required(func):
    """Ensure the current user can access comercial-related admin areas."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        role_key = normalize_role_key(getattr(current_user, "tipo", None) or session.get("tipo"))
        if role_key in ("admin", "gestor", "consultor"):
            return func(*args, **kwargs)
        if "COMERCIAL" in _dept_names():
            return func(*args, **kwargs)
        return _deny_access("Cadastros")

    return wrapper
