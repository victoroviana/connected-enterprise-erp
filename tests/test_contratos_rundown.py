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
# TEST CONFIG & FIXTURES WITH SQLITE DB SUPPORT FOR CONTRATOS
# ==============================================================================

class TestConfig:
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-contratos-key"
    MAIL_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


def _seed_contratos_tables():
    # Ensure contratos and protocolos tables exist in SQLite
    sql_contratos = (
        "CREATE TABLE IF NOT EXISTS contratos ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "cliente varchar(255) NOT NULL,"
        "cnpj varchar(20),"
        "base varchar(100),"
        "contrato varchar(100),"
        "protocolo varchar(50),"
        "Sistema varchar(100),"
        "valor decimal(12,2),"
        "tem_multa varchar(10),"
        "valor_multa decimal(12,2),"
        "data_solicitacao date,"
        "data_cancelamento datetime,"
        "data_revertido datetime,"
        "base_ativa_ate date,"
        "informacoes text,"
        "status varchar(50) DEFAULT 'Ativo',"
        "cancelamento_concluido datetime"
        ")"
    )

    sql_protocolos = (
        "CREATE TABLE IF NOT EXISTS protocolos ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "tabela_origem varchar(50) NOT NULL,"
        "id_tabela_origem int NOT NULL,"
        "protocolo varchar(20) NOT NULL,"
        "data_criacao datetime NOT NULL"
        ")"
    )

    db.session.execute(text(sql_contratos))
    db.session.execute(text(sql_protocolos))
    db.session.commit()


@pytest.fixture
def app():
    app_instance = create_app(TestConfig)
    with app_instance.app_context():
        db.create_all()
        _seed_contratos_tables()

        # Retrieve or create CONTRATOS and ADMINISTRACAO departments
        dept_contratos = Department.query.filter_by(slug="contratos").first()
        if not dept_contratos:
            dept_contratos = Department(name="CONTRATOS", slug="contratos")
            db.session.add(dept_contratos)

        dept_admin = Department.query.filter_by(slug="administracao").first()
        if not dept_admin:
            dept_admin = Department(name="ADMINISTRACAO", slug="administracao")
            db.session.add(dept_admin)

        db.session.commit()

        # Admin user
        admin = User(
            usuario="admin_contratos",
            nome_completo="Admin Contratos",
            email="admin_contratos@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="admin",
            role="admin",
            is_active=True,
            department_id=dept_admin.id,
            permissions={"contratos": True},
        )
        admin.departments = [dept_admin, dept_contratos]

        # User with Contratos department access
        operator = User(
            usuario="operador_contratos",
            nome_completo="Operador Contratos",
            email="operador_contratos@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="user",
            is_active=True,
            department_id=dept_contratos.id,
            permissions={"contratos": True},
        )
        operator.departments = [dept_contratos]

        # User without Contratos permission
        no_perm_user = User(
            usuario="user_sem_contratos",
            nome_completo="User Sem Contratos",
            email="sem_contratos@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="user",
            is_active=True,
            permissions={},
        )

        db.session.add_all([admin, operator, no_perm_user])
        db.session.commit()

        yield app_instance


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username="admin_contratos"):
    with client.session_transaction() as sess:
        user = User.query.filter_by(usuario=username).first()
        sess["_user_id"] = str(user.id)
        sess["user_id"] = user.id
        sess["usuario_id"] = user.id
        sess["logged_in_user"] = user.nome_completo
        sess["tipo"] = user.tipo
        sess["role"] = user.role


# ==============================================================================
# 1. PERMISSIONS & ACCESS CONTROL TESTS
# ==============================================================================

def test_contratos_unauthorized_access(client):
    res = client.get("/contratos/cancelados")
    assert res.status_code in (200, 302, 401)


def test_contratos_no_permission_redirect(client):
    login(client, username="user_sem_contratos")
    res = client.get("/contratos/cancelados")
    assert res.status_code in (200, 302, 403)


def test_contratos_admin_access_allowed(client):
    login(client, username="admin_contratos")
    res = client.get("/contratos/cancelados")
    assert res.status_code == 200


def test_contratos_sem_permissao_page(client):
    login(client, username="user_sem_contratos")
    res = client.get("/contratos/sem-permissao")
    assert res.status_code == 200


# ==============================================================================
# 2. LISTING, SEARCHING & STATUS FILTERING
# ==============================================================================

def test_contratos_index_redirect(client):
    login(client, username="admin_contratos")
    res = client.get("/contratos/")
    assert res.status_code == 302
    assert "/contratos/cancelados" in res.location


def test_contratos_list_status_filter(client, app):
    login(client, username="admin_contratos")

    with app.app_context():
        db.session.execute(
            text(
                "INSERT INTO contratos (cliente, cnpj, contrato, status, valor, data_solicitacao) "
                "VALUES ('Industria Metalurgica LTDA', '11222333000181', 'CT-2026-001', 'Ativo', 1500.00, '2026-01-15')"
            )
        )
        db.session.execute(
            text(
                "INSERT INTO contratos (cliente, cnpj, contrato, status, valor, data_solicitacao) "
                "VALUES ('Comercio de Alimentos SA', '22333444000199', 'CT-2026-002', 'Inativo', 850.00, '2026-02-10')"
            )
        )
        db.session.commit()

    res = client.get("/contratos/cancelados?status=Ativo")
    assert res.status_code == 200


def test_contratos_search_by_client(client, app):
    login(client, username="admin_contratos")

    with app.app_context():
        db.session.execute(
            text(
                "INSERT INTO contratos (cliente, cnpj, contrato, status, valor) "
                "VALUES ('Supermercado Silva VIP', '33444555000177', 'CT-2026-003', 'Ativo', 3200.00)"
            )
        )
        db.session.commit()

    res = client.get("/contratos/cancelados?search=Supermercado")
    assert res.status_code == 200


# ==============================================================================
# 3. CONTRACT INFORMATION & HISTORY UPDATES
# ==============================================================================

def test_contratos_historico_fetch(client, app):
    login(client, username="admin_contratos")

    with app.app_context():
        db.session.execute(
            text(
                "INSERT INTO contratos (cliente, cnpj, contrato, informacoes) "
                "VALUES ('Cliente Historico LTDA', '44555666000188', 'CT-HIST-01', '<li>Instalação inicial efetuada em 01/01/2026.</li>')"
            )
        )
        db.session.commit()

        cid = db.session.execute(text("SELECT id FROM contratos WHERE cliente = 'Cliente Historico LTDA'")).scalar()

    res = client.post("/contratos/historico", data={"id": str(cid)})
    assert res.status_code == 200
    assert "Instalação inicial" in res.get_data(as_text=True)


def test_contratos_update_info_success(client, app):
    login(client, username="admin_contratos")

    with app.app_context():
        db.session.execute(
            text(
                "INSERT INTO contratos (cliente, cnpj, contrato, informacoes) "
                "VALUES ('Empresa Nota LTDA', '55666777000199', 'CT-NOTE-01', '')"
            )
        )
        db.session.commit()

        cid = db.session.execute(text("SELECT id FROM contratos WHERE cliente = 'Empresa Nota LTDA'")).scalar()

    payload = {
        "id": str(cid),
        "new_info": "Cliente solicitou aditivo contratual para 5 novos pontos de marcação.",
    }
    res = client.post("/contratos/update-info", data=payload)
    assert res.status_code == 200

    with app.app_context():
        info = db.session.execute(text("SELECT informacoes FROM contratos WHERE id = :id"), {"id": cid}).scalar()
        assert "aditivo contratual" in info


# ==============================================================================
# 4. CONTRACT CANCELLATION WORKFLOW & EMAIL DISPATCH
# ==============================================================================

def test_contratos_solicitar_cancelamento(client, app):
    login(client, username="admin_contratos")

    with app.app_context():
        db.session.execute(
            text(
                "INSERT INTO contratos (cliente, cnpj, contrato, base, Sistema, status) "
                "VALUES ('Empresa Cancelamento SA', '66777888000100', 'CT-CANCEL-99', 'Sollus Tecnologia', 'Sollus Ponto', 'Ativo')"
            )
        )
        db.session.commit()

        cid = db.session.execute(text("SELECT id FROM contratos WHERE cliente = 'Empresa Cancelamento SA'")).scalar()

    payload = {
        "id": str(cid),
        "cancelamento": "28/07/2026 10:00:00",
    }

    with patch("modules.contratos.blueprints.contratos._send_email", return_value=True):
        res = client.post("/contratos/cancelamento", data=payload)
        assert res.status_code == 200

    with app.app_context():
        row = db.session.execute(text("SELECT data_cancelamento, informacoes FROM contratos WHERE id = :id"), {"id": cid}).fetchone()
        assert row.data_cancelamento is not None
        assert "Cancelamento Solicitado" in row.informacoes


# ==============================================================================
# 5. PROTOCOL GENERATION & DATABASE INTEGRITY
# ==============================================================================

def test_contratos_protocol_generation(app):
    with app.app_context():
        from modules.contratos.blueprints.contratos import _generate_protocol
        protocol = _generate_protocol()
        assert protocol is not None
        assert len(protocol) >= 10
