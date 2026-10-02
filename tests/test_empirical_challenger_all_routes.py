"""Empirical Adversarial Test Suite & Comprehensive 374+ Route Crawler.

Author: teamwork_preview_challenger_final_1
Objective:
1. Automated route verification across ALL routes in app.url_map.iter_rules():
   - Every route resolves without unhandled 500 exceptions.
2. Stress test security endpoints (unauthenticated -> 401 JSON, unauthorized -> 403 JSON).
3. Verify /assistencia/orcamento-templates renders 200 OK.
4. Verify /sistemas_ponto is mounted and renders 200 OK.
5. Verify IDOR protection on /api/agenda/criar, /atualizar, /excluir.
"""

import json
import os
import re
import uuid
import pytest
from datetime import datetime, date
from sqlalchemy.pool import StaticPool

from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Department, AgendaEntry
from modules.suporte.models import OrcamentoTemplate


class ChallengerConfig:
    TESTING = True
    WTF_CSRF_ENABLED = False
    PRESERVE_CONTEXT_ON_EXCEPTION = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "challenger-empirical-test-key-!@#$%"
    MAIL_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


@pytest.fixture
def app_instance():
    app = create_app(ChallengerConfig)
    with app.app_context():
        db.drop_all()
        db.create_all()

        # Seed necessary departments
        dept_admin = Department(name="ADMINISTRACAO", slug="administracao")
        dept_assist = Department(name="ASSISTENCIA TECNICA", slug="assistencia-tecnica")
        db.session.add_all([dept_admin, dept_assist])
        db.session.commit()

        # Admin user
        admin = User(
            usuario="admin_challenger",
            nome_completo="Admin Challenger",
            email="admin_challenger@sollus.com",
            tipo="admin",
            role="admin",
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
        )

        # Tech 1 user (Assistencia Tecnica dept, standard technician without admin overrides)
        tech1 = User(
            usuario="tech1_challenger",
            nome_completo="Technician One",
            email="tech1_challenger@sollus.com",
            tipo="tecnico",
            role="user",
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
        )

        # Tech 2 user (Assistencia Tecnica dept, standard technician without admin overrides)
        tech2 = User(
            usuario="tech2_challenger",
            nome_completo="Technician Two",
            email="tech2_challenger@sollus.com",
            tipo="tecnico",
            role="user",
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
        )

        # Standard non-privileged user
        std_user = User(
            usuario="std_challenger",
            nome_completo="Standard User",
            email="std_challenger@sollus.com",
            tipo="consultor",
            role="user",
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
        )

        db.session.add_all([admin, tech1, tech2, std_user])
        db.session.flush()

        admin.department_id = dept_admin.id
        admin.departments = [dept_admin]
        admin.permissions = {
            "admin": True,
            "usuarios_gerenciar": True,
            "admin_assistencia": True,
            "admin_suporte": True,
            "assistencia_chamados": True,
            "assistencia_orcamentos": True,
            "admin_agenda_tecnica": True,
            "assistencia_agenda": True,
            "gerente": True,
        }

        tech1.department_id = dept_assist.id
        tech1.departments = [dept_assist]
        tech1.permissions = {"tecnico": True, "assistencia_agenda": True}

        tech2.department_id = dept_assist.id
        tech2.departments = [dept_assist]
        tech2.permissions = {"tecnico": True, "assistencia_agenda": True}

        std_user.department_id = dept_admin.id
        std_user.departments = [dept_admin]
        std_user.permissions = {}

        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app_instance):
    return app_instance.test_client()


def _login_as(client, username):
    with client.session_transaction() as sess:
        u = User.query.filter_by(usuario=username).first()
        assert u is not None, f"User {username} not found in DB!"
        from modules.propostas.blueprints.auth.permissions_utils import normalize_role_key, effective_permissions
        role_key = normalize_role_key(u.tipo or u.role or "usuario")
        perms = effective_permissions(u)
        sess["_user_id"] = str(u.id)
        sess["usuario_id"] = u.id
        sess["user_id"] = u.id
        sess["usuario"] = u.usuario
        sess["username"] = u.usuario
        sess["nome"] = u.nome_completo
        sess["logged_in_user"] = u.nome_completo
        sess["tipo"] = role_key
        sess["role"] = getattr(u, "role", "user")
        sess["permissions"] = perms
        sess["logged_in"] = True


# ==============================================================================
# 1. Comprehensive Route Verification (All rules in app.url_map)
# ==============================================================================
def test_all_flask_routes_empirical_crawl(app_instance):
    """Crawl and verify all routes in app.url_map.iter_rules().

    Verifies every route resolves without unhandled 500 Internal Server Errors.
    """
    rules = list(app_instance.url_map.iter_rules())
    assert len(rules) >= 370, f"Expected at least 370 routes, found {len(rules)}"

    unauth_client = app_instance.test_client()
    auth_client = app_instance.test_client()
    with app_instance.app_context():
        _login_as(auth_client, "admin_challenger")

    results = []
    failures = []

    for rule in rules:
        endpoint = rule.endpoint
        methods = [m for m in rule.methods if m not in ("OPTIONS", "HEAD")]
        rule_str = rule.rule

        # Generate sample path for dynamic parameters
        sample_path = rule_str
        # Replace converters
        sample_path = re.sub(r"<int:[^>]+>", "9999", sample_path)
        sample_path = re.sub(r"<float:[^>]+>", "9999.0", sample_path)
        sample_path = re.sub(r"<uuid:[^>]+>", str(uuid.uuid4()), sample_path)
        sample_path = re.sub(r"<path:[^>]+>", "sample/path", sample_path)
        sample_path = re.sub(r"<string:[^>]+>", "sample", sample_path)
        sample_path = re.sub(r"<[^>]+>", "9999", sample_path)

        preferred_method = "GET" if "GET" in methods else (methods[0] if methods else "GET")

        # 1. Test Unauthenticated Request
        try:
            if preferred_method == "GET":
                resp_unauth = unauth_client.get(sample_path, follow_redirects=False)
            elif preferred_method == "POST":
                resp_unauth = unauth_client.post(sample_path, json={}, follow_redirects=False)
            else:
                resp_unauth = unauth_client.open(sample_path, method=preferred_method, follow_redirects=False)
            status_unauth = resp_unauth.status_code
        except Exception as e:
            status_unauth = f"EXCEPTION: {str(e)}"

        # 2. Test Authenticated Request (Admin)
        try:
            if preferred_method == "GET":
                resp_auth = auth_client.get(sample_path, follow_redirects=False)
            elif preferred_method == "POST":
                resp_auth = auth_client.post(sample_path, json={}, follow_redirects=False)
            else:
                resp_auth = auth_client.open(sample_path, method=preferred_method, follow_redirects=False)
            status_auth = resp_auth.status_code
        except Exception as e:
            status_auth = f"EXCEPTION: {str(e)}"

        # Check for 500 error or crash
        is_500_unauth = status_unauth == 500 or (isinstance(status_unauth, str) and "EXCEPTION" in status_unauth)
        is_500_auth = status_auth == 500 or (isinstance(status_auth, str) and "EXCEPTION" in status_auth)

        passed = not is_500_unauth and not is_500_auth
        record = {
            "endpoint": endpoint,
            "rule": rule_str,
            "sample_path": sample_path,
            "method": preferred_method,
            "unauth_status": status_unauth,
            "auth_status": status_auth,
            "passed": passed,
        }
        results.append(record)

        if not passed:
            failures.append(record)

    # Dump full log summary to ensure transparency
    pass_count = sum(1 for r in results if r["passed"])
    fail_count = len(failures)

    print(f"\n================ ROUTE CRAWLER SUMMARY ================")
    print(f"Total Routes Scanned: {len(results)}")
    print(f"Passed (No 500): {pass_count}")
    print(f"Failed (500 Error/Crash): {fail_count}")

    if failures:
        print(f"FAILED ROUTES:")
        for f in failures:
            print(f"  - {f['rule']} [{f['endpoint']}] unauth={f['unauth_status']} auth={f['auth_status']}")

    assert fail_count == 0, f"Found {fail_count} routes throwing unhandled 500 exceptions or crashes!"


# ==============================================================================
# 2. Security & ACL Gatekeeper Hardening Stress Test
# ==============================================================================
def test_unauthenticated_api_endpoints_return_401_json(app_instance):
    """Stress test unauthenticated requests to API endpoints.

    All unauthenticated AJAX/JSON requests to protected API endpoints must return 401 with JSON error.
    """
    unauth_client = app_instance.test_client()

    api_endpoints = [
        "/admin/suporte/api/agenda",
        "/assistencia/api/agenda",
        "/admin/api/maintenance-check",
        "/audit/api",
        "/sollus-tickets/dashboard",
        "/admin/suporte/api/atendimentos",
        "/assistencia/api/fluxo",
        "/central-conhecimento/api/tasks",
        "/api/jobs/999",
    ]

    for url in api_endpoints:
        resp = unauth_client.get(
            url,
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 401, (
            f"Endpoint {url} did not return 401 when unauthenticated! Got {resp.status_code}"
        )
        assert resp.is_json, f"Endpoint {url} response is not JSON! Content-Type: {resp.content_type}"
        data = resp.get_json()
        assert data is not None
        assert (
            data.get("error") == "Authentication required"
            or data.get("success") is False
            or "Autenticação" in str(data)
        )


def test_cnpj_and_maintenance_check_login_required(app_instance):
    """Verify sensitive endpoints /api/cnpj and /admin/api/maintenance-check require login."""
    unauth_client = app_instance.test_client()

    # /api/cnpj/<cnpj> requires login (returns 401 or 302)
    resp_cnpj = unauth_client.get(
        "/api/cnpj/00000000000191",
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_cnpj.status_code in (401, 302), (
        f"Expected 401 or 302 for unauthenticated /api/cnpj/, got {resp_cnpj.status_code}"
    )

    # /admin/api/maintenance-check requires login (returns 401)
    resp_maint = unauth_client.get(
        "/admin/api/maintenance-check",
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_maint.status_code == 401, (
        f"Expected 401 for unauthenticated /admin/api/maintenance-check, got {resp_maint.status_code}"
    )


def test_unauthorized_api_endpoints_return_403_json(app_instance):
    """Stress test unauthorized requests (low privilege user) to restricted endpoints.

    Non-admin user requests to admin-only APIs must return 403 with JSON error.
    """
    client = app_instance.test_client()
    with app_instance.app_context():
        _login_as(client, "std_challenger")

    restricted_endpoints = [
        ("/audit/api", "GET"),
        ("/audit/export", "GET"),
        ("/admin/api/maintenance-check", "GET"),
    ]

    for url, method in restricted_endpoints:
        if method == "GET":
            resp = client.get(url, headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
        else:
            resp = client.post(url, json={}, headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})

        assert resp.status_code == 403, (
            f"Expected 403 Forbidden for unauthorized user on {url}, got {resp.status_code}"
        )


# ==============================================================================
# 3. Verification of /assistencia/orcamento-templates (200 OK)
# ==============================================================================
def test_assistencia_orcamento_templates_renders_200_ok(app_instance):
    """Verify /assistencia/orcamento-templates renders 200 OK with correct scripts block."""
    with app_instance.app_context():
        # Ensure at least one template exists
        tmpl = OrcamentoTemplate.query.filter_by(chave="template_test").first()
        if not tmpl:
            tmpl = OrcamentoTemplate(
                chave="template_test",
                label="Template Challenger Test",
                table_title="Tabela de Itens",
                items=[{"descricao": "Item 1", "valor": 100.0}],
                ativo=True,
            )
            db.session.add(tmpl)
            db.session.commit()

    client = app_instance.test_client()
    with app_instance.app_context():
        _login_as(client, "admin_challenger")

    resp = client.get("/assistencia/orcamento-templates")
    assert resp.status_code == 200, f"Expected 200 OK for /assistencia/orcamento-templates, got {resp.status_code}"
    html = resp.get_data(as_text=True)
    assert "Modelos de Orçamento" in html or "Templates" in html or "orcamento" in html.lower()
    assert "<script" in html


# ==============================================================================
# 4. Verification of /sistemas_ponto (Mounted and 200 OK)
# ==============================================================================
def test_sistemas_ponto_mounted_and_renders_200_ok(app_instance):
    """Verify /sistemas_ponto blueprint is mounted and renders 200 OK."""
    rules = [r.rule for r in app_instance.url_map.iter_rules()]
    assert any("/sistemas_ponto" in r for r in rules), "Route /sistemas_ponto not found in app.url_map!"

    client = app_instance.test_client()
    with app_instance.app_context():
        _login_as(client, "admin_challenger")

    resp = client.get("/sistemas_ponto")
    assert resp.status_code == 200, f"Expected 200 OK for /sistemas_ponto, got {resp.status_code}"
    html = resp.get_data(as_text=True)
    assert "Sistemas de Ponto" in html or "sistemas" in html.lower()


# ==============================================================================
# 5. IDOR Protection Verification on /api/agenda/criar, /atualizar, /excluir
# ==============================================================================
def test_idor_shared_agenda_protection(app_instance):
    """Stress test IDOR boundaries across shared agenda endpoints:

    - Tech 1 attempting to create entry for Tech 2 -> 403 Forbidden
    - Tech 1 attempting to update Tech 2's entry -> 403 Forbidden
    - Tech 1 attempting to delete Tech 2's entry -> 403 Forbidden
    - Tech 2 updating Tech 2's entry -> 200 OK / 302 Redirect
    - Admin updating Tech 2's entry -> 200 OK / 302 Redirect
    """
    with app_instance.app_context():
        tech1 = User.query.filter_by(usuario="tech1_challenger").first()
        tech2 = User.query.filter_by(usuario="tech2_challenger").first()
        admin = User.query.filter_by(usuario="admin_challenger").first()

        # Create fresh agenda entry for Tech 2 to test against
        entry_t2 = AgendaEntry(
            usuario_id=tech2.id,
            data_atendimento=date(2026, 9, 10),
            periodo="Manhã",
            unidade="RJ",
            obs="Fresh Tech 2 Entry For IDOR Test",
        )
        db.session.add(entry_t2)
        db.session.commit()

        t1_id = tech1.id
        t2_id = tech2.id
        admin_id = admin.id
        entry_id = entry_t2.id

    # --- 1. Tech 1 (Attacker) attempts IDOR operations against Tech 2 ---
    client_t1 = app_instance.test_client()
    with app_instance.app_context():
        _login_as(client_t1, "tech1_challenger")

    # 1. Tech 1 attempts to create entry for Tech 2 -> Expect 403
    resp_create = client_t1.post(
        "/assistencia/api/agenda/criar",
        data={
            "usuario_id": str(t2_id),
            "unidade": "RJ",
            "data_atendimento": "2026-09-02",
            "periodo": "Tarde",
            "obs": "IDOR Attack Attempt Create",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_create.status_code == 403, (
        f"Tech 1 creating entry for Tech 2 did not return 403! Got {resp_create.status_code}"
    )

    # 2. Tech 1 attempts to update Tech 2's entry -> Expect 403
    resp_update = client_t1.post(
        f"/assistencia/api/agenda/{entry_id}/atualizar",
        data={
            "usuario_id": str(t2_id),
            "unidade": "SP",
            "data_atendimento": "2026-09-03",
            "periodo": "Manhã",
            "obs": "IDOR Attack Attempt Update",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_update.status_code == 403, (
        f"Tech 1 updating Tech 2's entry did not return 403! Got {resp_update.status_code}"
    )

    # 3. Tech 1 attempts to delete Tech 2's entry -> Expect 403
    resp_delete = client_t1.post(
        f"/assistencia/api/agenda/{entry_id}/excluir",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_delete.status_code == 403, (
        f"Tech 1 deleting Tech 2's entry did not return 403! Got {resp_delete.status_code}"
    )

    # --- 2. Tech 2 (Legitimate Owner) updates own entry ---
    client_t2 = app_instance.test_client()
    with app_instance.app_context():
        _login_as(client_t2, "tech2_challenger")
    resp_t2_update = client_t2.post(
        f"/assistencia/api/agenda/{entry_id}/atualizar",
        data={
            "usuario_id": str(t2_id),
            "unidade": "RJ",
            "data_atendimento": "2026-09-04",
            "periodo": "Tarde",
            "obs": "Legitimate Tech 2 Update",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_t2_update.status_code in (200, 302), (
        f"Tech 2 updating own entry failed! Got {resp_t2_update.status_code}"
    )

    # --- 3. Admin (Superuser) updates Tech 2's entry ---
    client_admin = app_instance.test_client()
    with app_instance.app_context():
        _login_as(client_admin, "admin_challenger")
    resp_admin_update = client_admin.post(
        f"/assistencia/api/agenda/{entry_id}/atualizar",
        data={
            "usuario_id": str(t2_id),
            "unidade": "RJ",
            "data_atendimento": "2026-09-05",
            "periodo": "Integral",
            "obs": "Admin Superuser Update",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_admin_update.status_code in (200, 302), (
        f"Admin updating Tech 2's entry failed! Got {resp_admin_update.status_code}"
    )
