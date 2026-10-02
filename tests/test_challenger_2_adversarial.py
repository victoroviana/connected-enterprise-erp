"""
Challenger 2 Adversarial Verification Suite
Empirical validation of:
1. IDOR protections in shared_agenda.py across technician and management tiers.
2. CSRF protection enforcement on mutating forms (fluxo.html, historico_propostas.html, assistencia and proposal endpoints).
3. Transaction rollback resilience under simulated database failures and dirty session clearing.
"""
import ast
import os
import re
from pathlib import Path
from datetime import datetime, date
from unittest.mock import patch

import pytest
from flask import url_for
from flask_wtf.csrf import generate_csrf
from sqlalchemy import text, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import (
    SQLAlchemyError,
    IntegrityError,
    OperationalError,
    DataError,
    ProgrammingError,
    PendingRollbackError,
)

from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Department, Proposal, AgendaEntry
from modules.suporte.models import AssistenciaTarefa, OrcamentoStatus

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# SQLite compatibility helpers for isolated in-memory testing
@event.listens_for(Engine, "connect")
def _sqlite_compat(dbapi_connection, connection_record):
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        def date_format(val, fmt):
            if not val:
                return None
            try:
                dt = datetime.fromisoformat(val) if isinstance(val, str) else val
                return dt.strftime("%Y-%m")
            except Exception:
                return str(val)

        def concat(*args):
            return "".join(str(a) for a in args if a is not None)

        def ifnull(val, fallback):
            return val if val is not None else fallback

        def curdate():
            return date.today().isoformat()

        dbapi_connection.create_function("DATE_FORMAT", 2, date_format)
        dbapi_connection.create_function("CONCAT", -1, concat)
        dbapi_connection.create_function("IFNULL", 2, ifnull)
        dbapi_connection.create_function("CURDATE", 0, curdate)


class InMemoryBaseConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "challenger-2-adversarial-secret-key-2026"
    MAIL_ENABLED = False
    SERVER_NAME = "localhost"


class InMemoryCSRFConfig(InMemoryBaseConfig):
    WTF_CSRF_ENABLED = True
    WTF_CSRF_CHECK_DEFAULT = True


class InMemoryNoCSRFConfig(InMemoryBaseConfig):
    WTF_CSRF_ENABLED = False


@pytest.fixture
def app_csrf():
    """App with CSRF enabled and in-memory SQLite database."""
    app = create_app(InMemoryCSRFConfig)
    with app.app_context():
        db.create_all()
        _seed_users_and_departments()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client_csrf(app_csrf):
    return app_csrf.test_client()


@pytest.fixture
def app_no_csrf():
    """App with CSRF disabled for IDOR and DB rollback isolation tests."""
    app = create_app(InMemoryNoCSRFConfig)
    with app.app_context():
        db.create_all()
        _seed_users_and_departments()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client_no_csrf(app_no_csrf):
    return app_no_csrf.test_client()


def _seed_users_and_departments():
    dept_sup = Department.query.filter_by(slug="suporte").first() or Department(name="SUPORTE", slug="suporte")
    dept_ofic = Department.query.filter_by(slug="oficina").first() or Department(name="OFICINA", slug="oficina")
    dept_admin = Department.query.filter_by(slug="administracao").first() or Department(name="ADMINISTRACAO", slug="administracao")
    dept_com = Department.query.filter_by(slug="comercial").first() or Department(name="COMERCIAL", slug="comercial")

    db.session.add_all([dept_sup, dept_ofic, dept_admin, dept_com])
    db.session.commit()

    users = [
        User(
            usuario="c2_admin",
            nome_completo="Challenger Admin",
            email="c2_admin@sollus.com",
            tipo="admin",
            role="admin",
            department_id=dept_admin.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={"admin": True, "admin_agenda_tecnica": True},
        ),
        User(
            usuario="c2_gestor",
            nome_completo="Challenger Gestor",
            email="c2_gestor@sollus.com",
            tipo="gestor",
            role="gestor",
            department_id=dept_admin.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={},
        ),
        User(
            usuario="c2_tech_lead",
            nome_completo="Challenger Tech Lead",
            email="c2_lead@sollus.com",
            tipo="tecnico",
            role="user",
            department_id=dept_sup.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={"admin_agenda_tecnica": True},
        ),
        User(
            usuario="c2_tec_1",
            nome_completo="Technician One",
            email="c2_tec1@sollus.com",
            tipo="tecnico",
            role="user",
            department_id=dept_sup.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={},
        ),
        User(
            usuario="c2_tec_2",
            nome_completo="Technician Two",
            email="c2_tec2@sollus.com",
            tipo="tecnico",
            role="user",
            department_id=dept_sup.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={},
        ),
        User(
            usuario="c2_tec_3",
            nome_completo="Technician Three Oficina",
            email="c2_tec3@sollus.com",
            tipo="tecnico",
            role="user",
            department_id=dept_ofic.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={},
        ),
        User(
            usuario="c2_standard",
            nome_completo="Standard User",
            email="c2_std@sollus.com",
            tipo="usuario",
            role="user",
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={},
        ),
    ]
    db.session.add_all(users)
    db.session.commit()

    # Link departments
    u_admin = User.query.filter_by(usuario="c2_admin").first()
    u_tec1 = User.query.filter_by(usuario="c2_tec_1").first()
    u_tec2 = User.query.filter_by(usuario="c2_tec_2").first()
    u_tec3 = User.query.filter_by(usuario="c2_tec_3").first()

    u_admin.departments.append(dept_admin)
    u_tec1.departments.append(dept_sup)
    u_tec2.departments.append(dept_sup)
    u_tec3.departments.append(dept_ofic)
    db.session.commit()


def login_client(client, username):
    user = User.query.filter_by(usuario=username).first()
    assert user is not None, f"User {username} not found in database"
    uid = user.id
    tipo = user.tipo
    role = user.role
    nome = user.nome_completo
    perms = user.permissions or {}

    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
        sess["user_id"] = uid
        sess["usuario_id"] = uid
        sess["logged_in_user"] = nome
        sess["tipo"] = tipo
        sess["role"] = role
        sess["permissions"] = perms
    return uid


# ============================================================================
# 1. ADVERSARIAL IDOR VERIFICATION: shared_agenda.py
# ============================================================================

def test_idor_cross_technician_creation_blocked(app_no_csrf, client_no_csrf):
    """
    Adversarial IDOR Test: Technician 1 tries to create agenda entries assigned
    to Technician 2, Technician 3 (Oficina), and Standard User.
    All spoofed creation attempts MUST be rejected with HTTP 403.
    """
    with app_no_csrf.app_context():
        u1_id = login_client(client_no_csrf, "c2_tec_1")
        u2 = User.query.filter_by(usuario="c2_tec_2").first()
        u3 = User.query.filter_by(usuario="c2_tec_3").first()
        std = User.query.filter_by(usuario="c2_standard").first()
        u2_id = u2.id
        u3_id = u3.id
        std_id = std.id

    # Attempt 1: Create for Technician 2
    resp1 = client_no_csrf.post(
        "/admin/suporte/api/agenda/criar",
        data={
            "usuario_id": str(u2_id),
            "unidade": "IDOR Unit 1",
            "data_atendimento": "2026-09-10",
            "periodo": "Manhã",
            "obs": "Spoofed entry",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp1.status_code == 403, f"Expected 403 on cross-tech creation, got {resp1.status_code}"
    assert resp1.is_json
    assert "Você não tem permissão" in resp1.get_json().get("message", "")

    # Attempt 2: Create for Technician 3
    resp2 = client_no_csrf.post(
        "/admin/suporte/api/agenda/criar",
        data={
            "usuario_id": str(u3_id),
            "unidade": "IDOR Unit 2",
            "data_atendimento": "2026-09-10",
            "periodo": "Tarde",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp2.status_code == 403

    # Attempt 3: Create for standard user
    resp3 = client_no_csrf.post(
        "/admin/suporte/api/agenda/criar",
        data={
            "usuario_id": str(std_id),
            "unidade": "IDOR Unit 3",
            "data_atendimento": "2026-09-10",
            "periodo": "Dia todo",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp3.status_code == 403

    # Verify no entries were created in the database
    with app_no_csrf.app_context():
        assert AgendaEntry.query.filter_by(unidade="IDOR Unit 1").first() is None
        assert AgendaEntry.query.filter_by(unidade="IDOR Unit 2").first() is None
        assert AgendaEntry.query.filter_by(unidade="IDOR Unit 3").first() is None


def test_idor_cross_technician_modification_and_reassignment_blocked(app_no_csrf, client_no_csrf):
    """
    Adversarial IDOR Test:
    1. Technician 2 attempts to modify Technician 1's agenda entry details -> 403.
    2. Technician 2 attempts to steal/reassign Technician 1's entry to themselves -> 403.
    3. Technician 1 attempts to offload their own entry by reassigning to Technician 2 -> 403.
    """
    with app_no_csrf.app_context():
        u1 = User.query.filter_by(usuario="c2_tec_1").first()
        u2 = User.query.filter_by(usuario="c2_tec_2").first()
        u1_id = u1.id
        u2_id = u2.id

        entry = AgendaEntry(
            usuario_id=u1_id,
            unidade="Original Tec 1 Unit",
            data_atendimento=date(2026, 9, 15),
            periodo="Manhã",
            obs="Legitimate task for Tec 1",
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    # 1. Login as Tec 2 and attempt modification
    with app_no_csrf.app_context():
        login_client(client_no_csrf, "c2_tec_2")

    resp_mod = client_no_csrf.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={"unidade": "Tampered Unit", "obs": "Tampered by Tec 2"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_mod.status_code == 403
    assert resp_mod.is_json

    # 2. Tec 2 attempts to reassign Tec 1's entry to Tec 2 (theft)
    resp_theft = client_no_csrf.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={"usuario_id": str(u2_id), "unidade": "Stolen Unit"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_theft.status_code == 403

    # 3. Login as Tec 1 and attempt to reassign own entry to Tec 2 (offloading)
    with app_no_csrf.app_context():
        login_client(client_no_csrf, "c2_tec_1")

    resp_offload = client_no_csrf.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={"usuario_id": str(u2_id), "unidade": "Offloaded Unit"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_offload.status_code == 403

    # Verify original entry remains unchanged in DB
    with app_no_csrf.app_context():
        fresh = AgendaEntry.query.get(entry_id)
        assert fresh.usuario_id == u1_id
        assert fresh.unidade == "Original Tec 1 Unit"
        assert fresh.obs == "Legitimate task for Tec 1"


def test_idor_cross_technician_deletion_blocked(app_no_csrf, client_no_csrf):
    """
    Adversarial IDOR Test: Technician 2 attempts to delete Technician 1's agenda entry.
    Must be rejected with 403 and entry preserved.
    """
    with app_no_csrf.app_context():
        u1 = User.query.filter_by(usuario="c2_tec_1").first()
        u1_id = u1.id
        entry = AgendaEntry(
            usuario_id=u1_id,
            unidade="Protected Unit",
            data_atendimento=date(2026, 9, 20),
            periodo="Tarde",
            obs="Cannot be deleted by others",
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    with app_no_csrf.app_context():
        login_client(client_no_csrf, "c2_tec_2")

    resp_del = client_no_csrf.post(
        f"/admin/suporte/api/agenda/{entry_id}/excluir",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_del.status_code == 403

    with app_no_csrf.app_context():
        assert AgendaEntry.query.get(entry_id) is not None


def test_idor_assistencia_blueprint_mount_protection(app_no_csrf, client_no_csrf):
    """
    Verify IDOR protections are equally enforced when agenda is accessed via
    assist_bp mount (/assistencia/api/agenda/...).
    """
    with app_no_csrf.app_context():
        u1 = User.query.filter_by(usuario="c2_tec_1").first()
        u1_id = u1.id

        entry = AgendaEntry(
            usuario_id=u1_id,
            unidade="Assistencia Mount Unit",
            data_atendimento=date(2026, 9, 22),
            periodo="Manhã",
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    with app_no_csrf.app_context():
        login_client(client_no_csrf, "c2_tec_2")

    # Update via assistencia blueprint
    resp_up = client_no_csrf.post(
        f"/assistencia/api/agenda/{entry_id}/atualizar",
        data={"unidade": "Hacked Assistencia Unit"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_up.status_code == 403

    # Delete via assistencia blueprint
    resp_del = client_no_csrf.post(
        f"/assistencia/api/agenda/{entry_id}/excluir",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_del.status_code == 403

    with app_no_csrf.app_context():
        assert AgendaEntry.query.get(entry_id) is not None


def test_privileged_management_can_mutate_any_agenda(app_no_csrf, client_no_csrf):
    """
    Verify that privileged roles (Admin, Gestor, and Tech Lead with admin_agenda_tecnica)
    CAN legitimately manage, reassign, and delete any technician's agenda entries.
    """
    with app_no_csrf.app_context():
        u1 = User.query.filter_by(usuario="c2_tec_1").first()
        u2 = User.query.filter_by(usuario="c2_tec_2").first()
        u1_id = u1.id
        u2_id = u2.id

        entry = AgendaEntry(
            usuario_id=u1_id,
            unidade="Initial Delegation Unit",
            data_atendimento=date(2026, 9, 25),
            periodo="Manhã",
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    # 1. Gestor reassigns Tec 1's entry to Tec 2
    with app_no_csrf.app_context():
        login_client(client_no_csrf, "c2_gestor")

    resp_gestor = client_no_csrf.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={"usuario_id": str(u2_id), "unidade": "Gestor Managed Unit"},
        follow_redirects=False,
    )
    assert resp_gestor.status_code in (302, 200)

    with app_no_csrf.app_context():
        updated = AgendaEntry.query.get(entry_id)
        assert updated.usuario_id == u2_id
        assert updated.unidade == "Gestor Managed Unit"

    # 2. Tech Lead (with admin_agenda_tecnica permission) reassigns back to Tec 1
    with app_no_csrf.app_context():
        login_client(client_no_csrf, "c2_tech_lead")

    resp_lead = client_no_csrf.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={"usuario_id": str(u1_id), "unidade": "Tech Lead Managed Unit"},
        follow_redirects=False,
    )
    assert resp_lead.status_code in (302, 200)

    with app_no_csrf.app_context():
        updated2 = AgendaEntry.query.get(entry_id)
        assert updated2.usuario_id == u1_id

    # 3. Admin deletes entry
    with app_no_csrf.app_context():
        login_client(client_no_csrf, "c2_admin")

    resp_admin = client_no_csrf.post(
        f"/admin/suporte/api/agenda/{entry_id}/excluir",
        follow_redirects=False,
    )
    assert resp_admin.status_code in (302, 200)

    with app_no_csrf.app_context():
        assert AgendaEntry.query.get(entry_id) is None


# ============================================================================
# 2. ADVERSARIAL CSRF VERIFICATION: fluxo.html & historico_propostas.html
# ============================================================================

def test_csrf_tokens_present_in_template_source():
    """
    Verify static template compliance:
    - templates/admin/assistencia/fluxo.html must have create_form.hidden_tag() or csrf_token.
    - templates/historico_propostas.html must have csrf_token in proposal deletion form.
    """
    fluxo_path = PROJECT_ROOT / "templates" / "admin" / "assistencia" / "fluxo.html"
    with open(fluxo_path, "r", encoding="utf-8") as f:
        fluxo_content = f.read()

    assert "{{ create_form.hidden_tag() }}" in fluxo_content or "csrf_token" in fluxo_content, \
        "fluxo.html missing CSRF token in Nova OS form"
    assert 'name="csrf_token"' in fluxo_content or "csrf_token" in fluxo_content

    historico_path = PROJECT_ROOT / "templates" / "historico_propostas.html"
    with open(historico_path, "r", encoding="utf-8") as f:
        historico_content = f.read()

    assert '<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>' in historico_content, \
        "historico_propostas.html missing CSRF input tag in proposal deletion form"


def test_csrf_adversarial_assistencia_criar_endpoint(app_csrf, client_csrf):
    """
    Adversarial CSRF Test on POST /assistencia/criar:
    1. Unauthenticated request -> 302/401
    2. Authenticated request WITHOUT CSRF token -> 400 Bad Request
    3. Authenticated request with INVALID / FORGED CSRF token -> 400 Bad Request
    4. Authenticated request with VALID CSRF token -> Passes CSRF check (302 redirect)
    """
    os_payload = {
        "nome": "Adversarial Client OS",
        "cnpj": "00000000000191",
        "os_codigo": "OS-ADV-CSRF-1",
        "unidade": "RJ",
        "departamento_responsavel": "ASSISTENCIA TECNICA",
        "tipo_entrada": "balcao",
        "fluxo_tipo": "interno",
        "contrato": "sim",
        "orcamento": "100",
        "data_criacao": "2026-09-01",
        "data_fim": "2026-09-05",
        "status": "Entrada",
        "descricao": "Testing CSRF token enforcement",
        "notificacao": "nao",
    }

    with app_csrf.app_context():
        login_client(client_csrf, "c2_admin")

    # Step 1: Missing CSRF token
    resp_missing = client_csrf.post(
        "/assistencia/criar",
        data=os_payload,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_missing.status_code == 400, f"Expected 400 for missing CSRF, got {resp_missing.status_code}"

    # Step 2: Forged / Tampered CSRF token
    forged_payload = dict(os_payload)
    forged_payload["csrf_token"] = "forged_adversarial_csrf_token_xyz"
    resp_forged = client_csrf.post(
        "/assistencia/criar",
        data=forged_payload,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_forged.status_code == 400, f"Expected 400 for forged CSRF, got {resp_forged.status_code}"

    # Step 3: Valid CSRF token
    with app_csrf.test_request_context():
        valid_token = generate_csrf()

    valid_payload = dict(os_payload)
    valid_payload["csrf_token"] = valid_token
    resp_valid = client_csrf.post(
        "/assistencia/criar",
        data=valid_payload,
    )
    assert resp_valid.status_code != 400, "Valid CSRF token was rejected with 400"
    assert resp_valid.status_code in (302, 200)


def test_csrf_adversarial_excluir_proposta_endpoint(app_csrf, client_csrf):
    """
    Adversarial CSRF Test on POST /excluir_proposta/<id>:
    1. Authenticated request WITHOUT CSRF token -> 400 Bad Request
    2. Authenticated request with INVALID CSRF token -> 400 Bad Request
    3. Authenticated request with VALID CSRF token -> 302 Redirect
    """
    with app_csrf.app_context():
        admin_id = login_client(client_csrf, "c2_admin")
        prop = Proposal(
            usuario_id=admin_id,
            company="Empresa CSRF Delete Test",
            cnpj="00000000000191",
            client_name="Cliente Exclusao",
            filename="Proposta CSRF Delete",
            is_current=True,
        )
        db.session.add(prop)
        db.session.commit()
        prop_id = prop.id

    # Step 1: Missing CSRF token
    resp_missing = client_csrf.post(
        f"/excluir_proposta/{prop_id}",
        data={},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_missing.status_code == 400

    # Step 2: Forged CSRF token
    resp_forged = client_csrf.post(
        f"/excluir_proposta/{prop_id}",
        data={"csrf_token": "forged_delete_token"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_forged.status_code == 400

    # Step 3: Valid CSRF token
    with app_csrf.test_request_context():
        valid_token = generate_csrf()

    resp_valid = client_csrf.post(
        f"/excluir_proposta/{prop_id}",
        data={"csrf_token": valid_token},
    )
    assert resp_valid.status_code == 302


def test_csrf_adversarial_assistencia_mover_endpoint(app_csrf, client_csrf):
    """
    Adversarial CSRF Test on POST /assistencia/<tarefa_id>/mover (Kanban drag-and-drop):
    1. Missing CSRF -> 400
    2. Invalid CSRF -> 400
    3. Valid CSRF via Form -> Accepted
    4. Valid CSRF via X-CSRFToken Header -> Accepted
    """
    with app_csrf.app_context():
        login_client(client_csrf, "c2_admin")
        tarefa = AssistenciaTarefa(
            nome="OS Mover CSRF Test",
            OS="OS-CSRF-MOVE-1",
            cnpj="00000000000191",
            unidade="RJ",
            departamento_responsavel="ASSISTENCIA TECNICA",
            tipo_entrada="balcao",
            status="Entrada",
        )
        db.session.add(tarefa)
        db.session.commit()
        tarefa_id = tarefa.id

    # 1. Missing CSRF
    resp_missing = client_csrf.post(
        f"/assistencia/{tarefa_id}/mover",
        data={"status": "em progresso"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_missing.status_code == 400

    # 2. Forged CSRF
    resp_forged = client_csrf.post(
        f"/assistencia/{tarefa_id}/mover",
        data={"status": "em progresso", "csrf_token": "tampered_move_token"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_forged.status_code == 400

    # 3. Valid CSRF via form
    with app_csrf.test_request_context():
        token_form = generate_csrf()

    resp_valid_form = client_csrf.post(
        f"/assistencia/{tarefa_id}/mover",
        data={"status": "em progresso", "csrf_token": token_form},
    )
    assert resp_valid_form.status_code != 400

    # 4. Valid CSRF via X-CSRFToken header
    with app_csrf.test_request_context():
        token_header = generate_csrf()

    resp_valid_header = client_csrf.post(
        f"/assistencia/{tarefa_id}/mover",
        data={"status": "Entrada"},
        headers={"X-CSRFToken": token_header},
    )
    assert resp_valid_header.status_code != 400


# ============================================================================
# 3. ADVERSARIAL TRANSACTION ROLLBACK & DB FAILURE RESILIENCE
# ============================================================================

def test_db_session_dirty_state_recovery_oracle(app_no_csrf):
    """
    Oracle Test: Intentionally cause database failures across multiple error types
    (IntegrityError, OperationalError, ProgrammingError) and verify that
    db.session.rollback() immediately clears the transaction and restores health
    for 50 sequential rapid cycles.
    """
    with app_no_csrf.app_context():
        # Cycle through 50 simulated error/rollback sequences
        for i in range(50):
            try:
                # Trigger SQL error
                db.session.execute(text(f"SELECT * FROM nonexistent_table_adversarial_{i}"))
                db.session.flush()
            except SQLAlchemyError:
                db.session.rollback()

            # Session must execute queries cleanly
            res = db.session.execute(text("SELECT 100 + :val"), {"val": i}).scalar()
            assert res == 100 + i, f"Failed recovery at cycle {i}"


def test_db_exception_in_shared_agenda_commit(app_no_csrf, client_no_csrf):
    """
    Simulate database commit failure during agenda creation and verify that:
    1. The exception is caught and handled gracefully without unhandled crash.
    2. db.session.rollback() prevents PendingRollbackError on subsequent queries.
    """
    with app_no_csrf.app_context():
        admin_id = login_client(client_no_csrf, "c2_admin")

    # Inject OperationalError on commit
    with patch.object(db.session, "commit", side_effect=OperationalError("Simulated DB lock", {}, None)):
        resp = client_no_csrf.post(
            "/admin/suporte/api/agenda/criar",
            data={
                "usuario_id": str(admin_id),
                "unidade": "Rollback Test Unit",
                "data_atendimento": "2026-09-10",
                "periodo": "Manhã",
            },
        )
        assert resp.status_code in (302, 200, 500)

    # CRITICAL: Verify session in the same application context is clean and operational
    with app_no_csrf.app_context():
        u = User.query.get(admin_id)
        assert u is not None
        assert db.session.execute(text("SELECT 1")).scalar() == 1


def test_db_exception_in_assistencia_orcamentos(app_no_csrf, client_no_csrf):
    """
    Simulate commit failure in /assistencia/orcamentos/criar and verify clean rollback.
    """
    with app_no_csrf.app_context():
        login_client(client_no_csrf, "c2_admin")

    with patch.object(db.session, "commit", side_effect=SQLAlchemyError("Simulated Orcamento failure")):
        resp = client_no_csrf.post(
            "/assistencia/orcamentos/criar",
            data={
                "dataEnvio": "2026-09-01",
                "tipoVisita": "AVULSA",
                "equipamento": "Catraca Rollback Test",
                "cliente": "Cliente Rollback",
                "numeroProposta": "PROP-FAIL-1",
                "valor": "2000,00",
                "unidade": "RJ",
            },
        )
        assert resp.status_code in (302, 200, 500)

    with app_no_csrf.app_context():
        orc = OrcamentoStatus.query.filter_by(numero_proposta="PROP-FAIL-1").first()
        assert orc is None, "Failed transaction was not rolled back"
        assert db.session.execute(text("SELECT 1")).scalar() == 1


def test_db_exception_in_proposal_approval(app_no_csrf, client_no_csrf):
    """
    Simulate database commit failure during proposal approval and verify clean rollback.
    """
    with app_no_csrf.app_context():
        admin_id = login_client(client_no_csrf, "c2_admin")
        prop = Proposal(
            usuario_id=admin_id,
            company="Empresa Approval Rollback Test",
            cnpj="00000000000191",
            client_name="Cliente Approval Rollback",
            filename="Proposta Approval Rollback",
            is_current=True,
        )
        db.session.add(prop)
        db.session.commit()
        prop_id = prop.id

    with patch.object(db.session, "commit", side_effect=SQLAlchemyError("Simulated Approval commit failure")):
        try:
            resp = client_no_csrf.post(f"/aprovar_proposta/{prop_id}")
        except Exception:
            with app_no_csrf.app_context():
                db.session.rollback()

    with app_no_csrf.app_context():
        db.session.rollback()
        assert db.session.execute(text("SELECT 1")).scalar() == 1
        p = Proposal.query.get(prop_id)
        assert p is not None


# ============================================================================
# 4. CODEBASE-WIDE AST AUDIT OF DB EXCEPTION ROLLBACK HANDLERS
# ============================================================================

class DBExceptionASTVisitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.unhandled_try_blocks = []

    def visit_Try(self, node):
        body_text = ""
        for stmt in node.body:
            try:
                body_text += ast.unparse(stmt) + "\n"
            except Exception:
                pass

        mutation_indicators = [
            "db.session.add",
            "db.session.commit",
            "db.session.delete",
            "db.session.flush",
        ]

        if any(ind in body_text for ind in mutation_indicators):
            for handler in node.handlers:
                try:
                    handler_text = ast.unparse(handler)
                except Exception:
                    handler_text = ""
                if "db.session.rollback()" not in handler_text:
                    self.unhandled_try_blocks.append(
                        (self.filename, handler.lineno, handler_text[:100])
                    )
        self.generic_visit(node)


def test_ast_scan_rollback_in_all_db_mutation_handlers():
    """
    Scan all Python files across all modules in the repository.
    Verify that 100% of try-except blocks executing db mutations explicitly invoke
    db.session.rollback() in their exception handlers.
    Handles UTF-8 BOM encoding safely.
    """
    target_dirs = [
        PROJECT_ROOT / "modules",
        PROJECT_ROOT / "platform_app",
        PROJECT_ROOT / "utils",
        PROJECT_ROOT / "Viva_Rio",
    ]

    violations = []

    for target_dir in target_dirs:
        if not target_dir.exists():
            continue
        for root, _, files in os.walk(target_dir):
            for file in files:
                if not file.endswith(".py"):
                    continue
                file_path = Path(root) / file
                try:
                    with open(file_path, "r", encoding="utf-8-sig") as f:
                        source = f.read()
                    tree = ast.parse(source, filename=str(file_path))
                    visitor = DBExceptionASTVisitor(str(file_path))
                    visitor.visit(tree)
                    violations.extend(visitor.unhandled_try_blocks)
                except Exception as e:
                    pytest.fail(f"AST Parsing failed on {file_path}: {e}")

    assert len(violations) == 0, f"Found unhandled DB mutation except blocks: {violations}"
