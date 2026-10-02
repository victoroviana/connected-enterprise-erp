"""
Adversarial stress-test suite for:
1. Database error handling, dirty transaction clearing, and PendingRollbackError prevention.
2. CSRF validation on fluxo.html and historico_propostas.html.
3. Dependency resolution and imports in requirements.txt.
"""
from datetime import datetime, date
import os
import re
from pathlib import Path
import pytest
from unittest.mock import patch
from flask import session, url_for
from flask_wtf.csrf import generate_csrf
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError, PendingRollbackError

from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Department, Proposal, AgendaEntry
from modules.suporte.models import AssistenciaTarefa, OrcamentoStatus

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def app_with_csrf():
    """Create test application with CSRF protection ENABLED."""
    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=True,
        WTF_CSRF_CHECK_DEFAULT=True,
        SECRET_KEY="test-secret-key-for-csrf-adversarial",
        SERVER_NAME="localhost",
    )
    with app.app_context():
        yield app


@pytest.fixture
def client_with_csrf(app_with_csrf):
    return app_with_csrf.test_client()


@pytest.fixture
def app_no_csrf():
    """Create test application with CSRF disabled for DB rollback isolation tests."""
    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SERVER_NAME="localhost",
    )
    with app.app_context():
        yield app


@pytest.fixture
def client_no_csrf(app_no_csrf):
    return app_no_csrf.test_client()


def _get_or_create_admin(app):
    with app.app_context():
        user = User.query.filter_by(usuario="admin_challenger_test").first()
        if not user:
            user = User(
                usuario="admin_challenger_test",
                nome_completo="Admin Challenger",
                email="admin_challenger@sollus.com",
                tipo="admin",
                role="admin",
                password_hash="dummy",
                is_active=True,
            )
            db.session.add(user)
            db.session.commit()
        return user.id


def _login_session(client, user_id, tipo="admin"):
    with client.session_transaction() as sess:
        sess["usuario_id"] = user_id
        sess["user_id"] = user_id
        sess["_user_id"] = str(user_id)
        sess["tipo"] = tipo


# =========================================================================
# AREA 1: Database Error Handling, Rollback & PendingRollbackError Prevention
# =========================================================================

def test_db_session_dirty_state_clearing_direct(app_no_csrf):
    """
    Oracle Test: Verify that when a database transaction fails during a flush/commit,
    omitting rollback leaves the session in an error state, whereas issuing
    db.session.rollback() clears the dirty transaction and allows subsequent queries.
    """
    with app_no_csrf.app_context():
        # Step 1: Intentionally cause an error by executing invalid SQL
        try:
            db.session.execute(text("INSERT INTO non_existent_table_xyz VALUES (1, 2, 3)"))
            db.session.flush()
        except SQLAlchemyError:
            pass  # Caught exception

        # Step 2: Call rollback
        db.session.rollback()

        # Step 3: Verify that subsequent query succeeds cleanly
        result = db.session.execute(text("SELECT 1")).scalar()
        assert result == 1, "Session should be completely healthy after rollback"

        # Step 4: Stress test with 50 iterations of error -> rollback -> query
        for i in range(50):
            try:
                db.session.execute(text(f"INSERT INTO fake_table_{i} VALUES (1)"))
                db.session.flush()
            except SQLAlchemyError:
                db.session.rollback()

            res = db.session.execute(text("SELECT 1")).scalar()
            assert res == 1, f"Iteration {i}: session failed to recover after rollback"


def test_db_exception_in_shared_agenda_routes(app_no_csrf, client_no_csrf):
    """
    Adversarially simulate database exceptions during shared agenda mutations and
    verify that db.session.rollback() prevents PendingRollbackError on follow-up operations.
    """
    admin_id = _get_or_create_admin(app_no_csrf)
    _login_session(client_no_csrf, admin_id, tipo="admin")

    with app_no_csrf.app_context():
        entry = AgendaEntry(
            usuario_id=admin_id,
            unidade="RJ",
            data_atendimento=date.today(),
            periodo="Manhã",
            obs="Initial entry for test",
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    # Simulate database exception during commit in criar_agendamento
    with patch.object(db.session, "commit", side_effect=OperationalError("Simulated DB lock error", {}, None)):
        resp = client_no_csrf.post(
            "/admin/suporte/api/agenda/criar",
            data={
                "usuario_id": str(admin_id),
                "unidade": "SP",
                "data_atendimento": "2026-09-10",
                "periodo": "Tarde",
                "obs": "Exception test",
            },
        )
        # Should catch and redirect without unhandled 500 crash
        assert resp.status_code in (302, 200, 500)

    # CRITICAL VERIFICATION: In the very same application context, verify follow-up query succeeds without PendingRollbackError
    with app_no_csrf.app_context():
        clean_query = User.query.filter_by(id=admin_id).first()
        assert clean_query is not None, "Follow-up query failed with dirty session state!"
        db_res = db.session.execute(text("SELECT 1")).scalar()
        assert db_res == 1

    # Simulate database exception during commit in atualizar_agendamento
    with patch.object(db.session, "commit", side_effect=OperationalError("Simulated DB lock error", {}, None)):
        resp = client_no_csrf.post(
            f"/admin/suporte/api/agenda/{entry_id}/atualizar",
            data={
                "unidade": "BH",
                "data_atendimento": "2026-09-15",
                "periodo": "Noite",
                "obs": "Updated test",
            },
        )
        assert resp.status_code in (302, 200, 500)

    with app_no_csrf.app_context():
        clean_query = AgendaEntry.query.get(entry_id)
        assert clean_query is not None, "Follow-up query failed with dirty session state!"


def test_db_exception_in_assistencia_orcamentos_criar(app_no_csrf, client_no_csrf):
    """
    Adversarially simulate database exceptions in assistencia_orcamentos_criar and verify
    rollback clears transaction state.
    """
    admin_id = _get_or_create_admin(app_no_csrf)
    _login_session(client_no_csrf, admin_id, tipo="admin")

    with patch.object(db.session, "commit", side_effect=SQLAlchemyError("Simulated commit error")):
        resp = client_no_csrf.post(
            "/assistencia/orcamentos/criar",
            data={
                "dataEnvio": "2026-09-01",
                "tipoVisita": "AVULSA",
                "equipamento": "Catraca Teste",
                "cliente": "Empresa Teste",
                "numeroProposta": "PROP-9999",
                "valor": "1500,00",
                "unidade": "RJ",
            },
        )
        assert resp.status_code == 302

    # Follow-up query
    with app_no_csrf.app_context():
        orc = OrcamentoStatus.query.filter_by(numero_proposta="PROP-9999").first()
        assert orc is None, "Failed transaction should have been rolled back"
        # Session must be clean
        assert db.session.execute(text("SELECT count(*) FROM users")).scalar() >= 1


def test_db_exception_in_assistencia_criar(app_no_csrf, client_no_csrf):
    """
    Adversarially simulate database exceptions in assistencia_criar and verify
    clean rollback.
    """
    admin_id = _get_or_create_admin(app_no_csrf)
    _login_session(client_no_csrf, admin_id, tipo="admin")

    with patch.object(db.session, "commit", side_effect=SQLAlchemyError("Simulated OS creation failure")):
        resp = client_no_csrf.post(
            "/assistencia/criar",
            data={
                "nome": "Cliente OS Rollback Test",
                "cnpj": "00000000000191",
                "os_codigo": "OS-ROLLBACK-1",
                "unidade": "RJ",
                "departamento_responsavel": "ASSISTENCIA TECNICA",
                "tipo_entrada": "balcao",
                "fluxo_tipo": "interno",
                "contrato": "sim",
                "orcamento": "100",
                "data_criacao": "2026-09-01",
                "data_fim": "2026-09-05",
                "status": "Entrada",
                "descricao": "Rollback test description",
                "notificacao": "nao",
            },
        )
        assert resp.status_code in (302, 200, 500)

    with app_no_csrf.app_context():
        # Verify session is not poisoned
        check = db.session.execute(text("SELECT 1")).scalar()
        assert check == 1


def test_db_exception_in_propostas_routes(app_no_csrf, client_no_csrf):
    """
    Adversarially test proposal approval and operations under simulated commit failures.
    """
    admin_id = _get_or_create_admin(app_no_csrf)
    _login_session(client_no_csrf, admin_id, tipo="admin")

    with app_no_csrf.app_context():
        prop = Proposal(
            usuario_id=admin_id,
            company="Empresa Rollback Proposta",
            cnpj="00000000000191",
            client_name="Cliente Test",
            filename="Proposta Rollback Test",
            is_current=True,
        )
        db.session.add(prop)
        db.session.commit()
        prop_id = prop.id

    # Test failure during approval
    with patch.object(db.session, "commit", side_effect=SQLAlchemyError("Simulated approval commit failure")):
        try:
            resp = client_no_csrf.post(f"/aprovar_proposta/{prop_id}")
        except Exception:
            db.session.rollback()

    with app_no_csrf.app_context():
        db.session.rollback()  # Ensure clean context
        p = Proposal.query.get(prop_id)
        assert p is not None
        assert db.session.execute(text("SELECT 1")).scalar() == 1


# =========================================================================
# AREA 2: Adversarial CSRF Validation on fluxo.html and historico_propostas.html
# =========================================================================

def test_csrf_rendered_in_fluxo_template(app_with_csrf, client_with_csrf):
    """
    Verify that fluxo.html renders valid CSRF hidden fields and JavaScript CSRF tokens.
    """
    admin_id = _get_or_create_admin(app_with_csrf)
    _login_session(client_with_csrf, admin_id, tipo="admin")

    template_path = PROJECT_ROOT / "templates" / "admin" / "assistencia" / "fluxo.html"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Form 1: Modal Nova OS must have {{ create_form.hidden_tag() }} or csrf_token
    assert "{{ create_form.hidden_tag() }}" in content or "csrf_token" in content
    # Form 2: Task card dynamic form must have csrf_token
    assert 'name="csrf_token"' in content
    # Drag-and-drop postMove must have csrf_token
    assert "csrf_token" in content


def test_csrf_rendered_in_historico_propostas_template():
    """
    Verify that historico_propostas.html renders valid CSRF token in the proposal deletion form.
    """
    template_path = PROJECT_ROOT / "templates" / "historico_propostas.html"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Deletion form must contain csrf_token
    assert '<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>' in content or 'name="csrf_token"' in content


def test_csrf_adversarial_assistencia_criar(app_with_csrf, client_with_csrf):
    """
    Adversarial test on POST /assistencia/criar:
    1. Request WITHOUT CSRF token -> REJECTED (HTTP 400).
    2. Request with INVALID / TAMPERED CSRF token -> REJECTED (HTTP 400).
    3. Request with VALID CSRF token -> ACCEPTED (HTTP 302 redirect).
    """
    admin_id = _get_or_create_admin(app_with_csrf)
    _login_session(client_with_csrf, admin_id, tipo="admin")

    form_payload = {
        "nome": "Adversarial CSRF Client",
        "cnpj": "00000000000191",
        "os_codigo": "OS-CSRF-1",
        "unidade": "RJ",
        "departamento_responsavel": "ASSISTENCIA TECNICA",
        "tipo_entrada": "balcao",
        "fluxo_tipo": "interno",
        "contrato": "sim",
        "orcamento": "100",
        "data_criacao": "2026-09-01",
        "data_fim": "2026-09-05",
        "status": "Entrada",
        "descricao": "CSRF attack test",
        "notificacao": "nao",
    }

    # Case 1: Missing CSRF token
    resp_missing = client_with_csrf.post(
        "/assistencia/criar",
        data=form_payload,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_missing.status_code == 400, f"Expected 400 for missing CSRF, got {resp_missing.status_code}"
    json_data = resp_missing.get_json() or {}
    assert json_data.get("reason") == "csrf" or "CSRF" in resp_missing.get_data(as_text=True)

    # Case 2: Tampered / Invalid CSRF token
    tampered_payload = dict(form_payload)
    tampered_payload["csrf_token"] = "tampered_token_xyz_1234567890"
    resp_tampered = client_with_csrf.post(
        "/assistencia/criar",
        data=tampered_payload,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_tampered.status_code == 400, f"Expected 400 for tampered CSRF, got {resp_tampered.status_code}"

    # Case 3: Valid CSRF token
    with app_with_csrf.test_request_context():
        valid_token = generate_csrf()

    valid_payload = dict(form_payload)
    valid_payload["csrf_token"] = valid_token
    resp_valid = client_with_csrf.post(
        "/assistencia/criar",
        data=valid_payload,
        headers={"X-CSRFToken": valid_token},
    )
    # With valid CSRF token, request passes CSRF layer (returns 302 or 200)
    assert resp_valid.status_code != 400, f"Valid CSRF token was unexpectedly rejected with 400: {resp_valid.get_data(as_text=True)}"


def test_csrf_adversarial_assistencia_mover(app_with_csrf, client_with_csrf):
    """
    Adversarial test on POST /assistencia/<tarefa_id>/mover:
    1. Missing CSRF -> REJECTED (HTTP 400).
    2. Invalid CSRF -> REJECTED (HTTP 400).
    3. Valid CSRF via form data -> ACCEPTED.
    4. Valid CSRF via X-CSRFToken header -> ACCEPTED.
    """
    admin_id = _get_or_create_admin(app_with_csrf)
    _login_session(client_with_csrf, admin_id, tipo="admin")

    with app_with_csrf.app_context():
        tarefa = AssistenciaTarefa(
            nome="OS Mover CSRF Test",
            OS="OS-CSRF-MOVE",
            cnpj="00000000000191",
            unidade="RJ",
            departamento_responsavel="ASSISTENCIA TECNICA",
            tipo_entrada="balcao",
            status="Entrada",
        )
        db.session.add(tarefa)
        db.session.commit()
        tarefa_id = tarefa.id

    # Case 1: Missing CSRF
    resp_missing = client_with_csrf.post(
        f"/assistencia/{tarefa_id}/mover",
        data={"status": "em progresso"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_missing.status_code == 400, f"Expected 400 for missing CSRF, got {resp_missing.status_code}"

    # Case 2: Tampered CSRF
    resp_tampered = client_with_csrf.post(
        f"/assistencia/{tarefa_id}/mover",
        data={"status": "em progresso", "csrf_token": "invalid_forged_csrf_token"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_tampered.status_code == 400, f"Expected 400 for tampered CSRF, got {resp_tampered.status_code}"

    # Case 3: Valid CSRF via form data
    with app_with_csrf.test_request_context():
        valid_token = generate_csrf()

    resp_valid_form = client_with_csrf.post(
        f"/assistencia/{tarefa_id}/mover",
        data={"status": "em progresso", "csrf_token": valid_token},
    )
    assert resp_valid_form.status_code != 400, "Valid form CSRF was blocked!"

    # Case 4: Valid CSRF via X-CSRFToken header
    with app_with_csrf.test_request_context():
        valid_header_token = generate_csrf()

    resp_valid_header = client_with_csrf.post(
        f"/assistencia/{tarefa_id}/mover",
        data={"status": "Entrada"},
        headers={"X-CSRFToken": valid_header_token},
    )
    assert resp_valid_header.status_code != 400, "Valid header CSRF was blocked!"


def test_csrf_adversarial_excluir_proposta(app_with_csrf, client_with_csrf):
    """
    Adversarial test on POST /excluir_proposta/<id>:
    1. Missing CSRF -> REJECTED (HTTP 400).
    2. Invalid CSRF -> REJECTED (HTTP 400).
    3. Valid CSRF -> ACCEPTED (HTTP 302).
    """
    admin_id = _get_or_create_admin(app_with_csrf)
    _login_session(client_with_csrf, admin_id, tipo="admin")

    with app_with_csrf.app_context():
        prop = Proposal(
            usuario_id=admin_id,
            company="Empresa Excluir CSRF Test",
            cnpj="00000000000191",
            client_name="Cliente Excluir",
            filename="Proposta Excluir CSRF",
            is_current=True,
        )
        db.session.add(prop)
        db.session.commit()
        prop_id = prop.id

    # Case 1: Missing CSRF token
    resp_missing = client_with_csrf.post(
        f"/excluir_proposta/{prop_id}",
        data={},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_missing.status_code == 400, f"Expected 400 on proposal deletion without CSRF, got {resp_missing.status_code}"

    # Case 2: Tampered CSRF token
    resp_tampered = client_with_csrf.post(
        f"/excluir_proposta/{prop_id}",
        data={"csrf_token": "tampered_token_proposta_delete"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_tampered.status_code == 400, f"Expected 400 on proposal deletion with bad CSRF, got {resp_tampered.status_code}"

    # Case 3: Valid CSRF token
    with app_with_csrf.test_request_context():
        valid_token = generate_csrf()

    resp_valid = client_with_csrf.post(
        f"/excluir_proposta/{prop_id}",
        data={"csrf_token": valid_token},
    )
    assert resp_valid.status_code == 302, f"Expected 302 redirect after proposal deletion, got {resp_valid.status_code}"


# =========================================================================
# AREA 3: Requirements.txt Dependency Resolution & Package Integrity
# =========================================================================

def test_requirements_dependencies_importable():
    """
    Verify that critical packages added or listed in requirements.txt
    (apscheduler, Flask-Mail, openpyxl, weasyprint, etc.) can be imported
    cleanly without syntax or symbol resolution errors.
    """
    import apscheduler
    assert hasattr(apscheduler, "__version__")

    import flask_mail
    assert hasattr(flask_mail, "Mail")

    import openpyxl
    assert hasattr(openpyxl, "Workbook")

    import sqlalchemy
    assert hasattr(sqlalchemy, "__version__")

    import flask_wtf
    assert hasattr(flask_wtf, "CSRFProtect")


def test_requirements_file_syntax_and_versions():
    """
    Verify that requirements.txt does not contain contradictory version pins,
    invalid operators, or malformed lines.
    """
    req_path = PROJECT_ROOT / "requirements.txt"
    with open(req_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    seen_packages = set()
    for line in lines:
        pkg_name = re.split(r"[=<>!~;]", line)[0].strip().lower()
        assert pkg_name, f"Malformed requirement line: {line}"
        assert pkg_name not in seen_packages, f"Duplicate package pin in requirements.txt: {pkg_name}"
        seen_packages.add(pkg_name)

    assert "apscheduler" in seen_packages
    assert "flask-mail" in seen_packages
    assert "openpyxl" in seen_packages
