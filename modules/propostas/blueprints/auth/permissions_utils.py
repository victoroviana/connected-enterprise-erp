"""Shared helpers for role-based permissions within the auth blueprint."""
from __future__ import annotations

from typing import Tuple

from flask import session
from flask_login import current_user

from ...models import (
    PERMISSION_DEFINITIONS,
    RolePermission,
    Department,
    default_permissions,
)


ROLE_META: dict[str, Tuple[str, str]] = {
    "admin": ("Administrador", "AD"),
    "gestor": ("Gestor", "GE"),
    "agent": ("Agente", "AG"),
    "usuario": ("Usuário", "US"),
}

PERMISSION_KEYS: tuple[str, ...] = tuple(PERMISSION_DEFINITIONS.keys())

ROLE_ALIASES = {
    "administrador": "admin",
    "user": "usuario",
}


def normalize_role_key(value: str | None) -> str:
    key = (value or "").strip().lower()
    if not key:
        return ""
    return ROLE_ALIASES.get(key, key)


def raw_permissions(user=None) -> dict[str, bool]:
    """Return permission flags without department scoping."""
    if user is None:
        if not current_user.is_authenticated:
            return normalize_permissions()
        user = current_user
    perms = getattr(user, "permissions", None)
    return normalize_permissions(perms if isinstance(perms, dict) else {})


def current_role_key() -> str:
    if not current_user.is_authenticated:
        return ""
    return normalize_role_key(getattr(current_user, "tipo", None) or session.get("tipo"))


def _full_permission_map() -> dict[str, bool]:
    """Return a mapping with all permission keys enabled."""
    return {key: True for key in PERMISSION_KEYS}


def normalize_permissions(perms: dict[str, bool] | str | None = None) -> dict[str, bool]:
    """Ensure a permission mapping contains all known keys and derived flags."""
    base = default_permissions()
    if perms:
        if isinstance(perms, str):
            try:
                import json
                perms = json.loads(perms)
            except Exception:
                perms = {}
        if isinstance(perms, dict):
            # Legacy support: if 'kanban' is present but 'central_conhecimento' is not, copy it.
            if "kanban" in perms and "central_conhecimento" not in perms:
                perms["central_conhecimento"] = perms["kanban"]
            base.update(perms)
    if base.get("usuarios_gerenciar"):
        base["usuarios_acesso"] = True
    if base.get("permissoes_gerenciar"):
        base["usuarios_acesso"] = True
    return base



def _department_permissions(user: User | None) -> dict[str, bool]:
    """Calculate raw permission mapping for a specific user based on departments."""
    if not user:
        return default_permissions()

    dept_permission_sets: list[dict[str, bool]] = []
    try:
        if getattr(user, "departments", None):
            for dept in user.departments:
                if dept and getattr(dept, "permissions", None) is not None:
                    dept_permission_sets.append(normalize_permissions(dept.permissions))
    except Exception:
        dept_permission_sets = []

    if not dept_permission_sets and getattr(user, "department", None):
        try:
            dept_permission_sets.append(normalize_permissions(user.department.permissions))
        except Exception:
            dept_permission_sets = []

    if not dept_permission_sets:
        return default_permissions()

    merged: dict[str, bool] = {key: False for key in PERMISSION_KEYS}
    for key in PERMISSION_KEYS:
        merged[key] = any(perms.get(key, False) for perms in dept_permission_sets)
    return merged


def effective_permissions(user=None) -> dict[str, bool]:
    if user is None:
        return normalize_permissions()

    role_key = normalize_role_key(getattr(user, "tipo", None) or getattr(user, "role", None))
    if (role_key or "").lower() == "admin":
        return _full_permission_map()

    role_perms = permissions_for_role(role_key)
    dept_perms = _department_permissions(user)
    user_flags = normalize_permissions(getattr(user, "permissions", None))

    combined: dict[str, bool] = {}
    for key in PERMISSION_KEYS:
        # Um usuário tem acesso se a role permite OU o usuário tem a permissão
        # individualmente OU o departamento concede a permissão.
        combined[key] = (
            bool(role_perms.get(key, False))
            or bool(user_flags.get(key, False))
            or bool(dept_perms.get(key, False))
        )
    return combined


def current_permissions() -> dict[str, bool]:
    """Return the current user's permissions merged with department flags."""
    if not current_user.is_authenticated:
        perms = normalize_permissions()
        session["permissions"] = perms
        return perms

    perms = effective_permissions(current_user)
    session["permissions"] = perms
    return perms


def is_admin_user() -> bool:
    if not current_user.is_authenticated:
        return False
    role = normalize_role_key(getattr(current_user, "tipo", None) or session.get("tipo") or "")
    return role == "admin"


def has_permission(*keys: str) -> bool:
    if is_admin_user():
        return True
    perms = current_permissions()
    return any(perms.get(k, False) for k in keys)


def permissions_for_role(role_name: str | None) -> dict[str, bool]:
    if not role_name:
        return normalize_permissions()

    normalized = normalize_role_key(role_name)
    if not normalized:
        return normalize_permissions()

    if normalized == "admin":
        return _full_permission_map()

    role = RolePermission.query.filter_by(name=normalized).first()
    if role and role.permissions:
        return normalize_permissions(role.permissions)

    return normalize_permissions()


def resolve_role_meta(role_key: str | None) -> Tuple[str, str]:
    key = normalize_role_key(role_key or "usuario")

    role = RolePermission.query.filter_by(name=key).first()
    if role:
        label = role.label.strip() or key.title()
        initials = _initials_from_label(label)
        return label, initials

    return ROLE_META.get(key, ("Usuário", "US"))


def _initials_from_label(label: str) -> str:
    parts = [part[0] for part in label.split() if part]
    if not parts:
        return (label[:2] or "US").upper()
    initials = ("".join(parts[:2]) or label[:2]).upper()
    return initials or "US"


def compute_role_initials(label: str) -> str:
    """Return short initials for a role label."""
    return _initials_from_label(label)

