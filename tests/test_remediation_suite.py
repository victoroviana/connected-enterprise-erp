import os
from pathlib import Path
import pytest
from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Department, AgendaEntry


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def app():
    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SERVER_NAME="localhost",
    )
    with app.app_context():
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


# ==========================================
# R1: Template Script Block Fix
# ==========================================
def test_r1_orcamento_templates_script_block():
    template_path = PROJECT_ROOT / "templates" / "admin" / "assistencia" / "orcamento_templates.html"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "{% block scripts %}" in content, "orcamento_templates.html must define {% block scripts %}"
    assert "{{ super() }}" in content, "orcamento_templates.html must include {{ super() }} inside scripts block"
    assert "{% block extra_js %}" not in content, "orcamento_templates.html must not use {% block extra_js %}"


# ==========================================
# R2: Security & ACL Gatekeeper Hardening
# ==========================================
def test_r2_unauthenticated_api_returns_401(client):
    endpoints_to_test = [
        "/admin/suporte/api/agenda",
        "/assistencia/api/agenda",
        "/admin/api/maintenance-check",
        "/audit/api",
        "/sollus-tickets/dashboard",
    ]
    for url in endpoints_to_test:
        resp = client.get(url, headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
        assert resp.status_code == 401, f"Expected 401 for unauthenticated request to {url}, got {resp.status_code}"
        json_data = resp.get_json()
        assert json_data is not None
        assert json_data.get("error") == "Authentication required" or json_data.get("success") is False


def test_r2_consultar_cnpj_requires_login(client):
    resp = client.get("/api/cnpj/00000000000191", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code in (401, 302), f"Expected 401 or 302 for /api/cnpj/ without login, got {resp.status_code}"


def test_r2_maintenance_check_requires_login(client):
    resp = client.get("/admin/api/maintenance-check", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 401, f"Expected 401 for /admin/api/maintenance-check without login, got {resp.status_code}"


def test_r2_shared_agenda_idor_protection(app, client):
    with app.app_context():
        user1 = User.query.filter_by(usuario="tecnico_user_1").first()
        if not user1:
            user1 = User(
                usuario="tecnico_user_1",
                nome_completo="Tecnico 1",
                email="tec1@sollus.com",
                tipo="tecnico",
                role="user",
                password_hash="dummy",
                is_active=True,
            )
            db.session.add(user1)

        user2 = User.query.filter_by(usuario="tecnico_user_2").first()
        if not user2:
            user2 = User(
                usuario="tecnico_user_2",
                nome_completo="Tecnico 2",
                email="tec2@sollus.com",
                tipo="tecnico",
                role="user",
                password_hash="dummy",
                is_active=True,
            )
            db.session.add(user2)
        db.session.commit()
        u1_id = user1.id
        u2_id = user2.id

    # Log in as user1
    with client.session_transaction() as sess:
        sess["usuario_id"] = u1_id
        sess["user_id"] = u1_id
        sess["_user_id"] = str(u1_id)
        sess["tipo"] = "tecnico"

    # User 1 attempts to create an agenda entry for User 2 -> Expect 403
    resp = client.post(
        "/admin/suporte/api/agenda/criar",
        data={
            "usuario_id": str(u2_id),
            "unidade": "RJ",
            "data_atendimento": "2026-09-01",
            "periodo": "Manhã",
            "obs": "IDOR test",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 403, f"Expected 403 when creating appointment for another technician, got {resp.status_code}"


def test_r2_audit_export_non_admin_blocked(app, client):
    with app.app_context():
        user_std = User.query.filter_by(usuario="standard_user_audit").first()
        if not user_std:
            user_std = User(
                usuario="standard_user_audit",
                nome_completo="Standard User",
                email="std@sollus.com",
                tipo="consultor",
                role="user",
                password_hash="dummy",
                is_active=True,
            )
            db.session.add(user_std)
            db.session.commit()
        std_id = user_std.id

    with client.session_transaction() as sess:
        sess["usuario_id"] = std_id
        sess["user_id"] = std_id
        sess["_user_id"] = str(std_id)
        sess["tipo"] = "consultor"

    resp = client.get("/audit/export", headers={"Accept": "application/json"})
    assert resp.status_code == 403, f"Expected 403 on audit export for non-admin, got {resp.status_code}"


# ==========================================
# R3: Database Resilience & Requirements
# ==========================================
def test_r3_requirements_txt():
    req_path = PROJECT_ROOT / "requirements.txt"
    with open(req_path, "r", encoding="utf-8") as f:
        req_content = f.read()

    assert "apscheduler" in req_content
    assert "Flask-Mail" in req_content
    assert "openpyxl" in req_content


# ==========================================
# R4: Blueprint Mounting & Feature Restoration
# ==========================================
def test_r4_sistemas_ponto_blueprint_mounted(app):
    rules = [rule.rule for rule in app.url_map.iter_rules()]
    assert any("/sistemas_ponto" in r for r in rules), "Route /sistemas_ponto must be registered in the Flask application"


def test_r4_cracha_inventory_logic_restored():
    cracha_file = PROJECT_ROOT / "modules" / "cracha" / "blueprints" / "cracha.py"
    with open(cracha_file, "r", encoding="utf-8") as f:
        code = f.read()

    assert "def controle_crachas():" in code
    assert "SELECT COUNT(*) AS total FROM controle_de_crachas" in code
    assert "controle.html" in code


def test_r4_login_dead_code_removed():
    login_file = PROJECT_ROOT / "modules" / "propostas" / "blueprints" / "auth" / "login.py"
    with open(login_file, "r", encoding="utf-8") as f:
        code = f.read()

    assert "def update_avatar():" in code
    assert "flash(\"Perfil atualizado com sucesso!\", \"success\")" in code
