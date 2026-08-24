from flask import render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from . import admin_bp
from .forms import UserForm
from extensions import db
from modules.propostas.models import User
from modules.propostas.blueprints.auth.permissions_utils import normalize_role_key, permissions_for_role

def admin_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Apenas administradores.', 'warning')
            return redirect('/')
        return fn(*args, **kwargs)
    return wrapper

@admin_bp.route('/users')
@login_required
@admin_required
def users_list():
    users = (
        User.query
        .order_by(User.nome_completo.asc(), User.email.asc())
        .all()
    )
    return render_template('chamados/admin/users.html', users=users)

@admin_bp.route('/users/new', methods=['GET','POST'])
@login_required
@admin_required
def users_new():
    form = UserForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data.lower()).first():
            flash('Já existe usuário com esse e-mail.', 'danger')
        else:
            role_key = normalize_role_key(form.role.data)
            u = User(name=form.name.data.strip(), email=form.email.data.lower(),
                     role=role_key, tipo=role_key, permissions=permissions_for_role(role_key),
                     is_active=form.is_active.data,
                     password_hash=generate_password_hash(form.password.data or 'changeme'))
            db.session.add(u)
            db.session.commit()
            flash('Usuário criado.', 'success')
            return redirect(url_for('admin.users_list'))
    elif request.method == 'POST':
        if form.errors:
            flash('; '.join(' '.join(v) for v in form.errors.values()), 'danger')
        else:
            flash('Falha ao validar formulário. Confira os campos.', 'danger')
    return render_template('chamados/admin/user_form.html', form=form, mode='new')

@admin_bp.route('/users/<int:user_id>/edit', methods=['GET','POST'])
@login_required
@admin_required
def users_edit(user_id: int):
    u = User.query.get_or_404(user_id)
    form = UserForm(obj=u)
    if form.validate_on_submit():
        u.name = form.name.data.strip()
        u.email = form.email.data.lower()
        role_key = normalize_role_key(form.role.data)
        u.role = role_key
        u.tipo = role_key
        u.permissions = permissions_for_role(role_key)
        u.is_active = form.is_active.data
        if form.password.data:
            u.password_hash = generate_password_hash(form.password.data)
        db.session.commit()
        flash('Usuário atualizado.', 'success')
        return redirect(url_for('admin.users_list'))
    elif request.method == 'POST':
        if form.errors:
            flash('; '.join(' '.join(v) for v in form.errors.values()), 'danger')
        else:
            flash('Falha ao validar formulário. Confira os campos.', 'danger')
    return render_template('chamados/admin/user_form.html', form=form, mode='edit', user=u)

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def users_delete(user_id: int):
    if current_user.id == user_id:
        flash('Você não pode excluir a si mesmo.', 'warning')
        return redirect(url_for('admin.users_list'))
    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    flash('Usuário excluído.', 'success')
    return redirect(url_for('admin.users_list'))

