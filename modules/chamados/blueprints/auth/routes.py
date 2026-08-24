from flask import render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from . import auth_bp
from .forms import LoginForm
from modules.propostas.models import User
from extensions import db

# ... [código _ldap_authenticate omitido para brevidade] ...

@auth_bp.route('/')
def auth_root():
    return redirect(url_for('auth.login'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # aceita tanto email/password quanto usuario/senha (legado)
        email = (request.form.get('email') or request.form.get('usuario') or '').strip().lower()
        password = request.form.get('password') or request.form.get('senha') or ''

        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash('Credenciais inválidas.', 'danger')
            return render_template('auth/login.html'), 401
        if user and not user.is_active:
            flash('Conta inativa.', 'danger')
            return render_template('auth/login.html'), 401

        login_user(user)
        return redirect(url_for('tickets.dashboard'))

    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
    if current_user.is_authenticated:
        session.pop('_flashes', None)
        logout_user()
        flash('Sessão encerrada.', 'info')
    return redirect(url_for('auth.login'))

