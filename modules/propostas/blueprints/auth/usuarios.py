"""
CRUD de usuários (painel de administração)
Rotas dentro do Blueprint auth_bp
URLs resultantes:
    • /auth/admin/usuarios              – listar & criar
    • /auth/editar_usuario/<id>         – editar via modal (GET/POST)
    • /auth/admin/usuarios/excluir/<id> – excluir (POST)
"""
from flask import (
    render_template, redirect, url_for, flash,
    request, jsonify, session
)
from flask_login import current_user
from werkzeug.security import generate_password_hash

from . import auth_bp, login_required
from .permissions_utils import (
    current_permissions,
    has_permission,
    normalize_permissions,
    normalize_role_key,
    permissions_for_role,
    resolve_role_meta,
)
from extensions import db
from ...constants import ISSUER_COMPANY_CHOICES, ISSUER_COMPANY_MAP, DEFAULT_ISSUER_CODE
from ...models import User, RolePermission, Department
from ...forms import UserForm


# Listar & criar usuários
# --------------------------------------------------------------------------- #
@auth_bp.route("/admin/usuarios", methods=["GET", "POST"])
@login_required
def gerenciar_usuarios():
    can_manage = has_permission("usuarios_gerenciar")
    can_access = can_manage or has_permission("usuarios_acesso")
    if not can_access:
        flash("Você não possui permissão para acessar a gestão de usuários.", "danger")
        return redirect(url_for("index"))

    session["permissions"] = current_permissions()

    form = UserForm()
    roles = RolePermission.query.order_by(RolePermission.label).all()
    form.tipo.choices = [(role.name, role.label) for role in roles]

    departments = Department.query.order_by(Department.name.asc()).all()
    dept_choices = [(0, "Sem departamento")]
    dept_choices.extend((dept.id, dept.name) for dept in departments)
    form.department_ids.choices = dept_choices
    if not form.unit_code.data:
        form.unit_code.data = DEFAULT_ISSUER_CODE
    form.unit_code.choices = ISSUER_COMPANY_CHOICES

    if request.method == "POST":
        if form.validate_on_submit():
            if not can_manage:
                flash("Você não possui permissão para gerenciar usuários.", "danger")
            elif User.query.filter_by(usuario=form.usuario.data).first():
                flash("Este usuário já existe.", "warning")
            elif User.query.filter_by(email=form.email.data).first():
                flash("Este e-mail já está cadastrado para outro usuário.", "warning")
            else:
                dept_ids = [int(value) for value in request.form.getlist("department_ids") if value and value != "0"]
                departments_selected = []
                if dept_ids:
                    departments_selected = Department.query.filter(Department.id.in_(dept_ids)).all()
                primary_dept_id = dept_ids[0] if dept_ids else None
                extra_submitted = [value.strip() for value in request.form.getlist("extra_phones[]") if value.strip()]

                role_key = normalize_role_key(form.tipo.data)
                novo = User(
                    usuario=form.usuario.data,
                    nome_completo=form.nome_completo.data,
                    email=form.email.data,
                    tipo=role_key,
                    password_hash=generate_password_hash(form.senha.data),
                    prox_num=form.prox_num.data or 1,
                    permissions=permissions_for_role(role_key),
                    phone=form.phone.data or None,
                    department_id=primary_dept_id,
                    unit_code=form.unit_code.data or DEFAULT_ISSUER_CODE,
                    ramal=(form.ramal.data or '').strip() or None,
                    is_active=form.is_active.data,
                )
                novo.extra_phones = extra_submitted
                novo.departments = departments_selected
                db.session.add(novo)
                db.session.commit()
                flash("Usuário cadastrado com sucesso.", "success")
                return redirect(url_for("auth_bp.gerenciar_usuarios"))
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Erro no campo '{form[field].label.text}': {error}", "danger")

    status_filter = (request.args.get("status") or "active").strip().lower()
    if status_filter not in {"active", "inactive", "all"}:
        status_filter = "active"

    base_query = User.query
    if status_filter == "active":
        base_query = base_query.filter(User.is_active.is_(True))
    elif status_filter == "inactive":
        base_query = base_query.filter(User.is_active.is_(False))

    user_filter = request.args.get("usuario_id", type=int)
    options_query = base_query
    if user_filter:
        base_query = base_query.filter(User.id == user_filter)

    user_options = (
        options_query.order_by(User.nome_completo.asc(), User.usuario.asc()).all()
    )

    page = request.args.get('page', 1, type=int)
    pagination = base_query.order_by(User.id.asc()).paginate(page=page, per_page=10, error_out=False)
    usuarios = pagination.items
    roles_payload = {
        role.name: {
            "label": role.label,
            "permissions": role.to_permissions(),
        }
        for role in RolePermission.query.all()
    }
    return render_template(
        "admin_usuarios.html",
        usuarios=usuarios,
        form=form,
        can_manage=can_manage,
        roles=roles,
        roles_payload=roles_payload,
        departments=departments,
        issuer_units=ISSUER_COMPANY_CHOICES,
        issuer_units_map=ISSUER_COMPANY_MAP,
        pagination=pagination,
        status_filter=status_filter,
        user_sel=user_filter,
        user_options=user_options,
        total_users=pagination.total,
    )


@auth_bp.route("/editar_usuario/<int:id>", methods=["GET", "POST"])
@login_required
def editar_usuario(id):
    if not has_permission("usuarios_gerenciar"):
        return jsonify({"error": "Permissão negada."}), 403

    usuario = User.query.get(id)
    if not usuario:
        return jsonify({"error": "Usuário não encontrado."}), 404

    if request.method == "POST":
        username = request.form.get("usuario")
        if not username:
            return jsonify({"error": "O nome de usuário é obrigatório."}), 400
        existing_user = User.query.filter_by(usuario=username).first()
        if existing_user and existing_user.id != id:
            return jsonify({"error": "Este nome de usuário já está em uso."}), 400

        email_input = request.form.get("email")
        if not email_input:
            return jsonify({"error": "O e-mail é obrigatório."}), 400
        existing_email = User.query.filter_by(email=email_input).first()
        if existing_email and existing_email.id != id:
            return jsonify({"error": "Este e-mail já está cadastrado para outro usuário."}), 400

        usuario.usuario = username
        usuario.nome_completo = request.form.get("nome_completo")
        usuario.email = email_input
        role_key = normalize_role_key(request.form.get("tipo"))
        usuario.tipo = role_key
        usuario.prox_num = int(request.form.get("prox_num") or usuario.prox_num)
        usuario.permissions = permissions_for_role(role_key)
        usuario.phone = request.form.get("phone") or None

        extra_submitted = [value.strip() for value in request.form.getlist("extra_phones[]") if value.strip()]
        usuario.extra_phones = extra_submitted
        dept_ids = [int(value) for value in request.form.getlist("department_ids") if value and value != "0"]
        departments_selected = []
        if dept_ids:
            departments_selected = Department.query.filter(Department.id.in_(dept_ids)).all()
        usuario.departments = departments_selected
        usuario.department_id = dept_ids[0] if dept_ids else None
        unit_code = request.form.get("unit_code") or DEFAULT_ISSUER_CODE
        usuario.unit_code = unit_code
        ramal = (request.form.get("ramal") or "").strip()
        usuario.ramal = ramal or None
        usuario.is_active = request.form.get("is_active") == "on"

        nova_senha = request.form.get("senha")
        if nova_senha:
            usuario.password_hash = generate_password_hash(nova_senha)

        db.session.commit()

        if current_user.is_authenticated and current_user.id == usuario.id:
            role_key = normalize_role_key(usuario.tipo or usuario.role or "usuario")
            role_label, role_initials = resolve_role_meta(role_key)
            try:
                current_user.tipo = role_key
                current_user.permissions = usuario.permissions
            except Exception:
                pass
            session.update(
                {
                    "tipo": role_key,
                    "role_label": role_label,
                    "role_initials": role_initials,
                }
            )
            current_permissions()
        return jsonify({"success": True})

    avatar_url = None
    if usuario.avatar_path:
        try:
            avatar_url = url_for("static", filename=usuario.avatar_path)
        except Exception:
            avatar_url = None

    role_obj = RolePermission.query.filter_by(name=normalize_role_key(usuario.tipo)).first()
    role_label = role_obj.label if role_obj else usuario.tipo

    unit_meta = ISSUER_COMPANY_MAP.get(usuario.unit_code or DEFAULT_ISSUER_CODE)
    return jsonify(
        {
            "id": usuario.id,
            "usuario": usuario.usuario,
            "nome_completo": usuario.nome_completo,
            "email": usuario.email,
            "tipo": usuario.tipo,
            "tipo_label": role_label,
            "prox_num": usuario.prox_num,
            "permissions": normalize_permissions(usuario.permissions),
            "phone": usuario.phone,
            "extra_phones": usuario.extra_phones or [],
            "is_active": usuario.is_active,
            "department_id": usuario.department_id,
            "department_ids": [dept.id for dept in (usuario.departments or [])] or ([usuario.department_id] if usuario.department_id else []),
            "department_name": usuario.department.name if usuario.department else None,
            "department_names": usuario.department_names,
            "unit_code": usuario.unit_code or DEFAULT_ISSUER_CODE,
            "unit_name": unit_meta["name"] if unit_meta else None,
            "ramal": usuario.ramal,
            "avatar_url": avatar_url,
        }
    )


@auth_bp.route("/admin/usuarios/excluir/<int:id>", methods=["POST"])
@login_required
def excluir_usuario(id):
    if not has_permission("usuarios_gerenciar"):
        flash("Você não possui permissão para gerenciar usuários.", "danger")
        return redirect(url_for("auth_bp.gerenciar_usuarios"))

    usuario = User.query.get_or_404(id)

    # evita que o usuário exclua a si mesmo
    if usuario.usuario == session.get("usuario"):
        flash("Você não pode excluir a si mesmo.", "danger")
        return redirect(url_for("auth_bp.gerenciar_usuarios"))

    db.session.delete(usuario)
    db.session.commit()
    flash("Usuário excluído com sucesso.", "success")
    return redirect(url_for("auth_bp.gerenciar_usuarios"))
