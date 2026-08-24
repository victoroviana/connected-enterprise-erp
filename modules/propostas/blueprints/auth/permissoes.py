
"""Rotas de gerenciamento de tipos e permissões."""
from __future__ import annotations

import re

from flask import flash, redirect, render_template, session, url_for
from flask_login import current_user, login_required

from . import auth_bp
from .permissions_utils import (
    PERMISSION_KEYS,
    compute_role_initials,
    current_permissions,
    has_permission,
    normalize_permissions,
)
from ...forms import (
    RolePermissionCreateForm,
    RolePermissionUpdateForm,
    DepartmentCreateForm,
    DepartmentUpdateForm,
)
from ...models import PERMISSION_DEFINITIONS, RolePermission, User, Department
from extensions import db


RESERVED_SLUGS = {"admin"}


def _user_has_department(user: User | None, department: Department | None) -> bool:
    if not user or not department:
        return False
    if getattr(user, "department_id", None) == department.id:
        return True
    try:
        return department in (user.departments or [])
    except Exception:
        return False


def _slugify_department(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower())
    return slug.strip("-")


def _collect_permission_flags(form) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for key in PERMISSION_KEYS:
        field = getattr(form, key, None)
        if field is not None:
            flags[key] = bool(field.data)
    return normalize_permissions(flags)


def _build_update_form(role: RolePermission) -> RolePermissionUpdateForm:
    data = {
        "role_id": role.id,
        "label": role.label,
    }
    perms_data = normalize_permissions(role.permissions)
    if (role.name or "").lower() == "admin":
        perms_data = {key: True for key in PERMISSION_KEYS}
    data.update(perms_data)
    return RolePermissionUpdateForm(formdata=None, data=data)


def _apply_permissions(role: RolePermission, permissions: dict[str, bool]) -> None:
    for user in User.query.filter(User.tipo == role.name).all():
        user.permissions = permissions
    if current_user.is_authenticated and (current_user.tipo or '').lower() == role.name.lower():
        try:
            current_user.permissions = permissions
        except Exception:
            pass
        session.update({
            "role_label": role.label,
            "role_initials": compute_role_initials(role.label),
            "tipo": role.name,
        })
        current_permissions()


def _fallback_context() -> tuple[str, dict[str, bool], str]:
    fallback_role = RolePermission.query.filter_by(name="usuario").first()
    fallback_name = "usuario"
    fallback_label = fallback_role.label if fallback_role else fallback_name.title()
    fallback_perms = normalize_permissions(fallback_role.permissions if fallback_role else None)
    return fallback_name, fallback_perms, fallback_label


@auth_bp.route("/admin/permissoes", methods=["GET", "POST"])
@login_required
def gerenciar_permissoes():
    if not has_permission("permissoes_gerenciar"):
        flash("Você não possui permissão para gerenciar tipos.", "danger")
        return redirect(url_for("auth_bp.gerenciar_usuarios"))

    create_form = RolePermissionCreateForm()
    department_form = DepartmentCreateForm(prefix="dept")

    if department_form.submit.data and department_form.validate_on_submit():
        name = (department_form.name.data or "").strip()
        slug = _slugify_department(name)
        if not slug:
            flash("Informe um nome válido para o departamento.", "warning")
        elif Department.query.filter_by(slug=slug).first():
            flash("Já existe um departamento com este nome.", "warning")
        else:
            permissions = _collect_permission_flags(department_form)
            dept = Department(name=name, slug=slug, permissions=permissions)
            db.session.add(dept)
            db.session.commit()
            flash("Departamento cadastrado com sucesso.", "success")
        return redirect(url_for("auth_bp.gerenciar_permissoes"))
    elif department_form.submit.data:
        flash("Não foi possível cadastrar o departamento.", "danger")

    if create_form.validate_on_submit():
        slug = (create_form.name.data or '').strip().lower()
        create_form.name.data = slug
        if not slug:
            flash("Informe um identificador para o tipo.", "warning")
        elif slug in RESERVED_SLUGS:
            flash("O identificador informado está reservado.", "warning")
        elif RolePermission.query.filter_by(name=slug).first():
            flash("Já existe um tipo com este identificador.", "warning")
        else:
            permissions = _collect_permission_flags(create_form)
            role = RolePermission(
                name=slug,
                label=(create_form.label.data or slug.title()).strip(),
                permissions=permissions,
            )
            db.session.add(role)
            db.session.commit()
            flash("Tipo criado com sucesso.", "success")
            return redirect(url_for("auth_bp.gerenciar_permissoes"))
    elif create_form.is_submitted():
        flash("Não foi possível criar o tipo informado.", "danger")

    roles = RolePermission.query.order_by(RolePermission.label).all()
    update_forms = {role.id: _build_update_form(role) for role in roles}
    departments = Department.query.order_by(Department.name.asc()).all()
    department_forms = {}
    for dept in departments:
        data = {
            "department_id": dept.id,
            "name": dept.name,
        }
        data.update(dept.to_permissions())
        department_forms[dept.id] = DepartmentUpdateForm(formdata=None, data=data)

    return render_template(
        "admin_permissoes.html",
        create_form=create_form,
        update_forms=update_forms,
        roles=roles,
        department_form=department_form,
        department_forms=department_forms,
        departments=departments,
        permission_definitions=PERMISSION_DEFINITIONS,
    )

@auth_bp.route("/admin/permissoes/departamentos/<int:dept_id>", methods=["POST"])
@login_required
def atualizar_departamento(dept_id: int):
    if not has_permission("permissoes_gerenciar"):
        flash("Você não possui permissão para gerenciar departamentos.", "danger")
        return redirect(url_for("auth_bp.gerenciar_permissoes"))

    department = Department.query.get_or_404(dept_id)
    form = DepartmentUpdateForm()

    if not form.validate_on_submit():
        for errors in form.errors.values():
            for error in errors:
                flash(error, "danger")
        return redirect(url_for("auth_bp.gerenciar_permissoes"))

    name = (form.name.data or department.name).strip()
    slug = _slugify_department(name)
    if not slug:
        flash("Informe um nome válido para o departamento.", "warning")
        return redirect(url_for("auth_bp.gerenciar_permissoes"))

    exists = Department.query.filter(Department.slug == slug, Department.id != department.id).first()
    if exists:
        flash("Já existe um departamento com este identificador.", "warning")
        return redirect(url_for("auth_bp.gerenciar_permissoes"))

    department.name = name
    department.slug = slug
    department.permissions = _collect_permission_flags(form)
    db.session.commit()

    if _user_has_department(current_user, department):
        current_permissions()

    flash("Departamento atualizado com sucesso.", "success")
    return redirect(url_for("auth_bp.gerenciar_permissoes"))


@auth_bp.route("/admin/departamentos/<int:dept_id>/excluir", methods=["POST"])
@login_required
def excluir_departamento(dept_id: int):
    if not has_permission("permissoes_gerenciar"):
        flash("Você não possui permissão para gerenciar departamentos.", "danger")
        return redirect(url_for("auth_bp.gerenciar_permissoes"))

    department = Department.query.get_or_404(dept_id)
    affected_current_user = _user_has_department(current_user, department)

    for user in department.users.all():
        user.department_id = None
    for user in department.members.all():
        try:
            if department in (user.departments or []):
                user.departments.remove(department)
        except Exception:
            continue

    db.session.delete(department)
    db.session.commit()

    if affected_current_user:
        current_permissions()

    flash("Departamento removido com sucesso.", "success")
    return redirect(url_for("auth_bp.gerenciar_permissoes"))


@auth_bp.route("/admin/permissoes/<int:role_id>", methods=["POST"])
@login_required
def atualizar_permissao(role_id: int):
    if not has_permission("permissoes_gerenciar"):
        flash("Você não possui permissão para gerenciar tipos.", "danger")
        return redirect(url_for("auth_bp.gerenciar_permissoes"))

    role = RolePermission.query.get_or_404(role_id)
    form = RolePermissionUpdateForm()

    if not form.validate_on_submit():
        for errors in form.errors.values():
            for error in errors:
                flash(error, "danger")
        return redirect(url_for("auth_bp.gerenciar_permissoes"))

    if str(role.id) != (form.role_id.data or '').strip():
        flash("Dados do tipo não conferem.", "danger")
        return redirect(url_for("auth_bp.gerenciar_permissoes"))

    role.label = (form.label.data or role.label).strip() or role.label
    permissions = _collect_permission_flags(form)
    if role.name == "admin":
        permissions = {key: True for key in PERMISSION_KEYS}
    role.permissions = permissions
    _apply_permissions(role, permissions)
    db.session.commit()
    flash("Tipo atualizado com sucesso.", "success")
    return redirect(url_for("auth_bp.gerenciar_permissoes"))


@auth_bp.route("/admin/permissoes/<int:role_id>/excluir", methods=["POST"])
@login_required
def excluir_permissao(role_id: int):
    if not has_permission("permissoes_gerenciar"):
        flash("Você não possui permissão para gerenciar tipos.", "danger")
        return redirect(url_for("auth_bp.gerenciar_permissoes"))

    role = RolePermission.query.get_or_404(role_id)
    if role.name == "admin":
        flash("Não é possível remover o tipo administrador.", "warning")
        return redirect(url_for("auth_bp.gerenciar_permissoes"))

    fallback_name, fallback_perms, fallback_label = _fallback_context()
    for user in User.query.filter(User.tipo == role.name).all():
        user.tipo = fallback_name
        user.permissions = fallback_perms

    db.session.delete(role)
    db.session.commit()

    if current_user.is_authenticated and (current_user.tipo or '').lower() == role.name.lower():
        try:
            current_user.tipo = fallback_name
            current_user.permissions = fallback_perms
        except Exception:
            pass
        session.update({
            "tipo": fallback_name,
            "role_label": fallback_label,
            "role_initials": compute_role_initials(fallback_label),
        })
        current_permissions()

    flash("Tipo removido com sucesso.", "success")
    return redirect(url_for("auth_bp.gerenciar_permissoes"))
