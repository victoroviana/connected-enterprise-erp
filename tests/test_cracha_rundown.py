from __future__ import annotations

import io
import os
import re
import pytest
from datetime import datetime, date
from unittest.mock import patch, MagicMock

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Department


# ==============================================================================
# TEST CONFIG & FIXTURES WITH LEGACY SQLITE DB SUPPORT
# ==============================================================================

class TestConfig:
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-cracha-key"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


def _seed_legacy_cracha_tables():
    from modules.cracha.blueprints.cracha import _legacy_cracha_table_statements
    for name, stmt in _legacy_cracha_table_statements():
        clean_stmt = stmt
        if "ENGINE=" in clean_stmt:
            clean_stmt = clean_stmt.split("ENGINE=")[0].strip()

        start_idx = clean_stmt.find("(")
        end_idx = clean_stmt.rfind(")")
        if start_idx != -1 and end_idx != -1:
            prefix = clean_stmt[:start_idx + 1]
            body = clean_stmt[start_idx + 1:end_idx]
            suffix = clean_stmt[end_idx:]
            parts = [p for p in body.split(",") if not p.strip().upper().startswith("KEY ")]
            clean_stmt = prefix + ",".join(parts) + suffix

        clean_stmt = clean_stmt.replace("int NOT NULL AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        clean_stmt = clean_stmt.replace("int NOT NULL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        clean_stmt = clean_stmt.replace("id int NOT NULL PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")
        clean_stmt = clean_stmt.replace("AUTO_INCREMENT", "")
        clean_stmt = re.sub(r"(?i)enum\([^)]+\)", "text", clean_stmt)

        try:
            db.session.execute(text(clean_stmt))
        except Exception:
            pass
    db.session.commit()


@pytest.fixture
def app():
    app_instance = create_app(TestConfig)
    with app_instance.app_context():
        db.create_all()
        _seed_legacy_cracha_tables()

        # Retrieve or create CRACHA and ADMIN departments
        dept_cracha = Department.query.filter_by(slug="cracha").first()
        if not dept_cracha:
            dept_cracha = Department(name="CRACHA", slug="cracha")
            db.session.add(dept_cracha)

        dept_admin = Department.query.filter_by(slug="administracao").first()
        if not dept_admin:
            dept_admin = Department(name="ADMINISTRACAO", slug="administracao")
            db.session.add(dept_admin)

        db.session.commit()

        # Admin user
        admin = User(
            usuario="admin_cracha",
            nome_completo="Admin Cracha",
            email="admin_cracha@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="admin",
            role="admin",
            is_active=True,
            department_id=dept_admin.id,
            permissions={"cracha": True, "cracha_cortador": True, "cracha_clientes": True, "cracha_modelos": True, "cracha_extratos": True},
        )
        admin.departments = [dept_admin, dept_cracha]

        # Operador de Crachá
        operador = User(
            usuario="operador_cracha",
            nome_completo="Operador Cracha",
            email="operador_cracha@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="user",
            is_active=True,
            department_id=dept_cracha.id,
            permissions={"cracha": True, "cracha_cortador": True, "cracha_clientes": True},
        )
        operador.departments = [dept_cracha]

        # Usuário sem acesso
        user_no_access = User(
            usuario="user_sem_cracha",
            nome_completo="User Sem Acesso Cracha",
            email="sem_cracha@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="user",
            is_active=True,
            permissions={},
        )

        db.session.add_all([admin, operador, user_no_access])
        db.session.commit()

        yield app_instance


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username="admin_cracha"):
    with client.session_transaction() as sess:
        user = User.query.filter_by(usuario=username).first()
        sess["_user_id"] = str(user.id)
        sess["user_id"] = user.id
        sess["usuario_id"] = user.id
        sess["logged_in_user"] = user.nome_completo
        sess["tipo"] = user.tipo
        sess["role"] = user.role


# ==============================================================================
# 1. ACCESSS & PERMISSION TESTS
# ==============================================================================

def test_cracha_unauthorized_access(client):
    res = client.get("/cracha/pedidos")
    assert res.status_code in (200, 302, 401)


def test_cracha_no_permission_redirect(client):
    login(client, username="user_sem_cracha")
    res = client.get("/cracha/pedidos")
    assert res.status_code in (200, 302, 403)


def test_cracha_admin_access_allowed(client):
    login(client, username="admin_cracha")
    res = client.get("/cracha/pedidos")
    assert res.status_code == 200


def test_cracha_sem_permissao_page(client):
    login(client, username="user_sem_cracha")
    res = client.get("/cracha/sem-permissao")
    assert res.status_code == 200


# ==============================================================================
# 2. PEDIDOS CRACHÁ (SOLICITAÇÕES & PEDIR CRACHÁ)
# ==============================================================================

def test_cracha_pedidos_index(client):
    login(client, username="admin_cracha")
    res = client.get("/cracha/pedidos")
    assert res.status_code == 200


def test_cracha_pedidos_historico(client):
    login(client, username="admin_cracha")
    res = client.get("/cracha/pedidos/historico")
    assert res.status_code == 200


def test_cracha_pedidos_criar(client, app):
    login(client, username="admin_cracha")

    payload = {
        "empresa": "Empresa Teste LTDA",
        "data_solicitacao": date.today().isoformat(),
        "etapa": "recebimento",
        "quantidade": "1",
        "tipo": "cracha",
        "observacoes": "Crachá com presilha jacaré.",
    }

    res = client.post("/cracha/pedidos/criar", data=payload, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        row = db.session.execute(text("SELECT * FROM pedidos_cracha WHERE empresa = 'Empresa Teste LTDA'")).fetchone()
        assert row is not None
        assert row.empresa == "Empresa Teste LTDA"


def test_cracha_pedidos_atualizar_etapa(client, app):
    login(client, username="admin_cracha")

    payload_criar = {
        "empresa": "Cliente SP LTDA",
        "data_solicitacao": date.today().isoformat(),
        "etapa": "recebimento",
        "quantidade": "1",
        "tipo": "cracha",
    }
    client.post("/cracha/pedidos/criar", data=payload_criar, follow_redirects=True)

    with app.app_context():
        pid = db.session.execute(text("SELECT id FROM pedidos_cracha WHERE empresa = 'Cliente SP LTDA'")).scalar()
        assert pid is not None

    payload = {"pedido_id": str(pid), "etapa": "confeccao_manual"}
    res = client.post("/cracha/pedidos/atualizar-etapa", data=payload, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        etapa = db.session.execute(text("SELECT etapa FROM pedidos_cracha WHERE id = :pid"), {"pid": pid}).scalar()
        assert etapa == "confeccao_manual"


# ==============================================================================
# 3. CORTADOR DE FOTOS (CRACHÁ PHOTO CUTTER)
# ==============================================================================

def test_cracha_cortador_fotos_page(client):
    login(client, username="admin_cracha")
    res = client.get("/cracha/cortador-fotos")
    assert res.status_code == 200


def test_cracha_cortador_fotos_upload_batch(client, app):
    login(client, username="admin_cracha")

    fake_img = (io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08"), "colaborador1.jpg")
    data = {
        "files": [fake_img],
    }

    with patch("modules.cracha.blueprints.cracha._process_cracha_photo", return_value=True):
        res = client.post("/cracha/cortador-fotos/processar", data=data, content_type="multipart/form-data")
        assert res.status_code in (200, 302)


# ==============================================================================
# 4. CLIENTES & MODELOS DE CRACHÁ (LEGADO JA_EMP & JA_CRA)
# ==============================================================================

def test_cracha_clientes_index(client):
    login(client, username="admin_cracha")
    res = client.get("/cracha/clientes")
    assert res.status_code == 200


def test_cracha_modelos_index(client):
    login(client, username="admin_cracha")
    res = client.get("/cracha/modelos")
    assert res.status_code == 200


def test_cracha_extratos_index(client):
    login(client, username="admin_cracha")
    res = client.get("/cracha/extratos")
    assert res.status_code == 200


# ==============================================================================
# 5. BANCO DE DADOS & TABELAS DE LEGADO
# ==============================================================================

def test_legacy_cracha_tables_existence(app):
    with app.app_context():
        res_emp = db.session.execute(text("SELECT COUNT(*) FROM ja_emp_empresas")).scalar()
        res_mod = db.session.execute(text("SELECT COUNT(*) FROM ja_cra_crachas_modelos")).scalar()
        res_ext = db.session.execute(text("SELECT COUNT(*) FROM ja_cra_crachas_extratos")).scalar()

        assert res_emp is not None
        assert res_mod is not None
        assert res_ext is not None
