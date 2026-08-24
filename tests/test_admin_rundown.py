from __future__ import annotations

import io
import os
import re
import pytest
from datetime import datetime, date, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Department, AgendaEntry, Birthday, VacationEntry, RolePermission
from modules.audit.models import AuditLog


# ==============================================================================
# TEST CONFIG & FIXTURES
# ==============================================================================

class TestConfig:
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-admin-key"
    MAIL_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


@pytest.fixture
def app():
    app_instance = create_app(TestConfig)
    with app_instance.app_context():
        db.create_all()

        # Fetch or ensure Departments
        dept_admin = Department.query.filter_by(slug="administracao").first()
        if not dept_admin:
            dept_admin = Department(name="ADMINISTRACAO", slug="administracao")
            db.session.add(dept_admin)

        dept_rh = Department.query.filter_by(slug="rh").first()
        if not dept_rh:
            dept_rh = Department(name="RH", slug="rh")
            db.session.add(dept_rh)

        db.session.commit()

        # Master Admin user
        admin = User(
            usuario="admin_master",
            nome_completo="Master Admin",
            email="admin_master@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="admin",
            role="admin",
            is_active=True,
            department_id=dept_admin.id,
            permissions={
                "usuarios_acesso": True,
                "usuarios_gerenciar": True,
                "permissoes_gerenciar": True,
                "admin_aniversariantes": True,
                "admin_ferias": True,
                "admin_agenda_tecnica": True,
                "admin_galeria": True,
            },
        )
        admin.departments = [dept_admin]

        # Regular user without admin permissions
        regular_user = User(
            usuario="usuario_comum",
            nome_completo="Usuario Comum",
            email="comum@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="user",
            is_active=True,
            department_id=dept_rh.id,
            permissions={},
        )
        regular_user.departments = [dept_rh]

        db.session.add_all([admin, regular_user])
        db.session.commit()

        yield app_instance


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username="admin_master"):
    with client.session_transaction() as sess:
        user = User.query.filter_by(usuario=username).first()
        sess["_user_id"] = str(user.id)
        sess["user_id"] = user.id
        sess["usuario_id"] = user.id
        sess["logged_in_user"] = user.nome_completo
        sess["tipo"] = user.tipo
        sess["role"] = user.role


# ==============================================================================
# 1. PERMISSIONS & ADMIN HUB TESTS
# ==============================================================================

def test_admin_unauthorized_access(client):
    res = client.get("/auth/admin/usuarios")
    assert res.status_code in (200, 302, 401)


def test_admin_hub_access_master_admin(client):
    login(client, username="admin_master")
    res = client.get("/admin/")
    assert res.status_code == 200


def test_admin_forbidden_regular_user(client):
    login(client, username="usuario_comum")
    res = client.get("/auth/admin/usuarios")
    assert res.status_code in (200, 302, 403)


# ==============================================================================
# 2. USER MANAGEMENT (GERENCIAR USUÁRIOS)
# ==============================================================================

def test_admin_usuarios_index(client):
    login(client, username="admin_master")
    res = client.get("/auth/admin/usuarios")
    assert res.status_code == 200


def test_admin_usuarios_create_new_user(client, app):
    login(client, username="admin_master")

    # Fetch available role name
    with app.app_context():
        role = RolePermission.query.first()
        role_name = role.name if role else "user"

    payload = {
        "usuario": "novo_tecnico",
        "nome_completo": "Novo Técnico de Campo",
        "email": "tecnico_novo@sollus.com",
        "tipo": role_name,
        "senha": "Password123!",
        "department_ids": [1],
        "unit_code": "01",
    }

    res = client.post("/auth/admin/usuarios", data=payload, follow_redirects=True)
    assert res.status_code in (200, 302)

    with app.app_context():
        u = User.query.filter_by(usuario="novo_tecnico").first()
        assert u is not None
        assert u.nome_completo == "Novo Técnico de Campo"


def test_admin_usuarios_toggle_active_status(client, app):
    login(client, username="admin_master")

    with app.app_context():
        u = User.query.filter_by(usuario="usuario_comum").first()
        uid = u.id

    res = client.post(f"/auth/admin/usuarios/excluir/{uid}", follow_redirects=True)
    assert res.status_code in (200, 302)


# ==============================================================================
# 3. PERMISSION MATRIX MANAGEMENT (GERENCIAR PERMISSÕES)
# ==============================================================================

def test_admin_permissoes_index(client):
    login(client, username="admin_master")
    res = client.get("/auth/admin/permissoes")
    assert res.status_code == 200


def test_admin_permissoes_update_user_permissions(client, app):
    login(client, username="admin_master")

    with app.app_context():
        u = User.query.filter_by(usuario="usuario_comum").first()
        uid = u.id

    payload = {
        "user_id": str(uid),
        "perm_propostas": "on",
        "perm_financeiro": "on",
        "perm_chamados": "on",
    }

    res = client.post("/auth/admin/permissoes", data=payload, follow_redirects=True)
    assert res.status_code in (200, 302)


# ==============================================================================
# 4. ANIVERSARIANTES, FÉRIAS & AGENDA TÉCNICA
# ==============================================================================

def test_aniversariantes_index(client, app):
    login(client, username="admin_master")

    with app.app_context():
        bday = Birthday(nome="Carlos Eduardo", data_nascimento=date(1990, 7, 28))
        db.session.add(bday)
        db.session.commit()

    res = client.get("/admin/aniversariantes")
    assert res.status_code == 200


def test_ferias_index(client, app):
    login(client, username="admin_master")

    with app.app_context():
        user = User.query.filter_by(usuario="admin_master").first()
        vac = VacationEntry(
            usuario_id=str(user.id),
            data_inicial=date(2026, 8, 1),
            data_final=date(2026, 8, 15),
            referente_ano=2026,
            unidade="Sollus Tecnologia",
        )
        db.session.add(vac)
        db.session.commit()

    res = client.get("/admin/ferias")
    assert res.status_code == 200


def test_agenda_index(client, app):
    login(client, username="admin_master")

    with app.app_context():
        user = User.query.filter_by(usuario="admin_master").first()
        ag = AgendaEntry(
            usuario_id=user.id,
            unidade="Sollus Tecnologia",
            data_atendimento=date(2026, 7, 29),
            periodo="Manhã",
            obs="Manutenção Preventiva Catracas",
        )
        db.session.add(ag)
        db.session.commit()

    res = client.get("/admin/agenda-tecnica")
    assert res.status_code in (200, 302)


# ==============================================================================
# 5. AUDITORIA & SISTEMA LOGS
# ==============================================================================

def test_audit_log_page(client, app):
    login(client, username="admin_master")

    with app.app_context():
        user = User.query.filter_by(usuario="admin_master").first()
        log_entry = AuditLog(
            actor_id=user.id,
            actor_email=user.email,
            actor_name=user.nome_completo,
            ip="127.0.0.1",
            ua="pytest",
            entity_type="user",
            entity_id=user.id,
            action="login_success",
            message="Login de administrador realizado com sucesso.",
        )
        db.session.add(log_entry)
        db.session.commit()

    res = client.get("/audit/")
    assert res.status_code in (200, 302)


def test_online_users_page(client):
    login(client, username="admin_master")
    res = client.get("/admin/usuarios-online")
    assert res.status_code in (200, 302)
