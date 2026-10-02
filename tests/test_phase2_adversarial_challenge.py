import pytest
from datetime import datetime, date
from sqlalchemy import event
from sqlalchemy.engine import Engine
from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Department, AgendaEntry


# Register SQLite helper functions for compatibility in testing environment
@event.listens_for(Engine, "connect")
def _register_sqlite_custom_functions(dbapi_connection, connection_record):
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        def date_format(val, fmt):
            if not val:
                return None
            try:
                if isinstance(val, str):
                    dt = datetime.fromisoformat(val)
                else:
                    dt = val
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


class AdversarialTestConfig:
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "adversarial-phase2-stress-key"
    MAIL_ENABLED = False


@pytest.fixture
def app():
    app_instance = create_app(AdversarialTestConfig)
    with app_instance.app_context():
        db.create_all()

        # Departments
        dept_sup = Department.query.filter_by(slug="suporte").first() or Department(name="SUPORTE", slug="suporte")
        dept_ofic = Department.query.filter_by(slug="oficina").first() or Department(name="OFICINA", slug="oficina")
        dept_com = Department.query.filter_by(slug="comercial").first() or Department(name="COMERCIAL", slug="comercial")
        dept_admin = Department.query.filter_by(slug="administracao").first() or Department(name="ADMINISTRACAO", slug="administracao")
        dept_fin = Department.query.filter_by(slug="financeiro").first() or Department(name="FINANCEIRO", slug="financeiro")

        db.session.add_all([dept_sup, dept_ofic, dept_com, dept_admin, dept_fin])
        db.session.commit()

        # 1. Admin
        user_admin = User(
            usuario="adv_admin",
            nome_completo="Adversarial Admin",
            email="adv_admin@sollus.com",
            tipo="admin",
            role="admin",
            department_id=dept_admin.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={"admin": True, "usuarios_gerenciar": True, "permissoes_gerenciar": True}
        )

        # 2. Gestor
        user_gestor = User(
            usuario="adv_gestor",
            nome_completo="Adversarial Gestor",
            email="adv_gestor@sollus.com",
            tipo="gestor",
            role="gestor",
            department_id=dept_admin.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={}
        )

        # 3. Technician Leader (has admin_agenda_tecnica)
        user_tech_lead = User(
            usuario="adv_tech_lead",
            nome_completo="Adversarial Tech Leader",
            email="adv_tech_lead@sollus.com",
            tipo="tecnico",
            role="user",
            department_id=dept_sup.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={"admin_agenda_tecnica": True}
        )

        # 4. Tech 1 (Suporte)
        user_tec1 = User(
            usuario="adv_tec1",
            nome_completo="Adversarial Tec 1",
            email="adv_tec1@sollus.com",
            tipo="tecnico",
            role="user",
            department_id=dept_sup.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={}
        )

        # 5. Tech 2 (Suporte)
        user_tec2 = User(
            usuario="adv_tec2",
            nome_completo="Adversarial Tec 2",
            email="adv_tec2@sollus.com",
            tipo="tecnico",
            role="user",
            department_id=dept_sup.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={}
        )

        # 6. Tech 3 (Oficina)
        user_tec3 = User(
            usuario="adv_tec3",
            nome_completo="Adversarial Tec 3 Oficina",
            email="adv_tec3@sollus.com",
            tipo="tecnico",
            role="user",
            department_id=dept_ofic.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={}
        )

        # 7. Unprivileged Standard User
        user_std = User(
            usuario="adv_std",
            nome_completo="Adversarial Standard User",
            email="adv_std@sollus.com",
            tipo="usuario",
            role="user",
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={"propostas": False, "central_conhecimento": False, "chamados": False}
        )

        # 8. Commercial User
        user_com = User(
            usuario="adv_com",
            nome_completo="Adversarial Commercial User",
            email="adv_com@sollus.com",
            tipo="consultor",
            role="user",
            department_id=dept_com.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={}
        )

        db.session.add_all([
            user_admin, user_gestor, user_tech_lead,
            user_tec1, user_tec2, user_tec3,
            user_std, user_com
        ])
        db.session.commit()

        user_admin.departments.append(dept_admin)
        user_tec1.departments.append(dept_sup)
        user_tec2.departments.append(dept_sup)
        user_tec3.departments.append(dept_ofic)
        user_com.departments.append(dept_com)
        db.session.commit()

        yield app_instance


@pytest.fixture
def client(app):
    return app.test_client()


def login_as(client, username):
    user = User.query.filter_by(usuario=username).first()
    assert user is not None, f"User {username} not found"
    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
        sess["user_id"] = user.id
        sess["usuario_id"] = user.id
        sess["logged_in_user"] = user.nome_completo
        sess["tipo"] = user.tipo
        sess["role"] = user.role
        sess["permissions"] = user.permissions or {}


# ============================================================================
# Section 1: Adversarial Gatekeeper Probing across 13 Blueprints + Audit
# ============================================================================

ALL_13_BLUEPRINT_HOOKS = [
    # 1. support_bp
    ("/admin/suporte/api/agenda", "/admin/suporte/atendimentos"),
    # 2. tech_bp
    ("/admin/tecnica/api/chamados", "/admin/tecnica/chamados"),
    # 3. assist_bp
    ("/assistencia/api/agenda", "/assistencia/"),
    # 4. atestados_bp
    ("/assistencia/atestados/task-status/test-id", "/assistencia/atestados/"),
    # 5. propostas_bp
    ("/api/jobs/test-id", "/nova_proposta"),
    # 6. equipamentos_bp
    ("/cadastro_equipamentos", "/cadastro_equipamentos"),
    # 7. admin_tools_bp
    ("/admin/api/maintenance-check", "/admin/"),
    # 8. financeiro_bp
    ("/financeiro/contas-receber", "/financeiro/contas-receber"),
    # 9. contratos_bp
    ("/contratos/cancelados", "/contratos/cancelados"),
    # 10. cracha_bp
    ("/cracha/cortador-fotos", "/cracha/pedidos"),
    # 11. tickets_bp
    ("/tickets/dashboard", "/tickets/dashboard"),
    # 12. central_conhecimento_bp
    ("/central-conhecimento/api/columns", "/central-conhecimento/"),
    # 13. sollus_tickets_bp
    ("/sollus-tickets/api/agent/signature", "/sollus-tickets/"),
]


@pytest.mark.parametrize("api_endpoint,html_endpoint", ALL_13_BLUEPRINT_HOOKS)
def test_unauthenticated_api_header_variants_return_401(client, api_endpoint, html_endpoint):
    """Test various API headers (Accept: application/json, X-Requested-With) return 401 JSON."""
    # Test with Accept header
    resp1 = client.get(api_endpoint, headers={"Accept": "application/json"})
    assert resp1.status_code == 401
    assert resp1.is_json
    data1 = resp1.get_json()
    assert data1.get("error") == "Authentication required" or data1.get("success") is False

    # Test with XMLHttpRequest header
    resp2 = client.get(api_endpoint, headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp2.status_code == 401
    assert resp2.is_json

    # Test with combined headers
    resp3 = client.get(api_endpoint, headers={"Accept": "application/json, text/plain, */*", "X-Requested-With": "XMLHttpRequest"})
    assert resp3.status_code == 401
    assert resp3.is_json


@pytest.mark.parametrize("api_endpoint,html_endpoint", ALL_13_BLUEPRINT_HOOKS)
def test_unauthenticated_html_requests_redirect(client, api_endpoint, html_endpoint):
    """Test standard browser requests without JSON headers redirect to login."""
    resp = client.get(html_endpoint, headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "") or "auth" in resp.headers.get("Location", "")


@pytest.mark.parametrize("api_endpoint,html_endpoint", ALL_13_BLUEPRINT_HOOKS)
def test_unauthenticated_mutating_verbs_rejected(client, api_endpoint, html_endpoint):
    """Test unauthenticated POST / PUT / DELETE requests do not execute and are properly blocked."""
    resp_post = client.post(api_endpoint, data={"malicious": "payload"}, headers={"Accept": "application/json"})
    assert resp_post.status_code in (401, 404, 405)

    resp_delete = client.delete(api_endpoint, headers={"Accept": "application/json"})
    assert resp_delete.status_code in (401, 404, 405)


def test_audit_blueprint_gatekeeper(client, app):
    """Test audit blueprint unauthenticated and unauthorized access control."""
    # 1. Unauthenticated API -> 401
    resp_api = client.get("/audit/api", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp_api.status_code == 401
    assert resp_api.is_json

    resp_exp = client.get("/audit/export", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp_exp.status_code == 401

    # 2. Unauthenticated HTML -> 302
    resp_html = client.get("/audit/", headers={"Accept": "text/html"})
    assert resp_html.status_code == 302

    # 3. Standard user (unauthorized) -> 403 for API, 302 for HTML
    with app.app_context():
        login_as(client, "adv_std")

    resp_std_api = client.get("/audit/api", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp_std_api.status_code == 403

    resp_std_exp = client.get("/audit/export", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp_std_exp.status_code == 403


# ============================================================================
# Section 2: Adversarial Sensitive Endpoint Probing (/api/cnpj and maintenance)
# ============================================================================

def test_cnpj_endpoint_unauthenticated(client):
    """Adversarially probe unauthenticated /api/cnpj/<cnpj> access is blocked."""
    resp_unauth = client.get("/api/cnpj/00000000000191", headers={"Accept": "application/json"})
    assert resp_unauth.status_code in (302, 401)


def test_cnpj_endpoint_authenticated_adversarial_inputs(client, app):
    """Adversarially probe /api/cnpj/<cnpj> with authenticated user and invalid/malicious payloads."""
    with app.app_context():
        login_as(client, "adv_std")

    # 1. SQL injection payload without raw whitespace
    resp_sqli = client.get("/api/cnpj/00000000000191_OR_1=1")
    assert resp_sqli.status_code == 400

    # 2. Non-numeric invalid strings
    resp_invalid = client.get("/api/cnpj/invalid123")
    assert resp_invalid.status_code == 400

    # 3. XSS attempts without raw whitespace
    resp_xss = client.get("/api/cnpj/script_alert_1")
    assert resp_xss.status_code == 400

    # 4. Invalid length (less than 14 digits)
    resp_short = client.get("/api/cnpj/123456789")
    assert resp_short.status_code == 400

    # 5. Invalid length (greater than 14 digits)
    resp_long = client.get("/api/cnpj/1234567890123456789")
    assert resp_long.status_code == 400


def test_maintenance_check_adversarial_matrix(client, app):
    """Test maintenance-check endpoint access matrix across all role tiers."""
    # 1. Unauthenticated
    resp_unauth = client.get("/admin/api/maintenance-check", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp_unauth.status_code == 401

    # 2. Unprivileged standard user
    with app.app_context():
        login_as(client, "adv_std")
    resp_std = client.get("/admin/api/maintenance-check", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp_std.status_code == 403

    # 3. Commercial user
    with app.app_context():
        login_as(client, "adv_com")
    resp_com = client.get("/admin/api/maintenance-check", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp_com.status_code == 403

    # 4. Technician 1 (no admin perm)
    with app.app_context():
        login_as(client, "adv_tec1")
    resp_tec = client.get("/admin/api/maintenance-check", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp_tec.status_code == 403

    # 5. Admin
    with app.app_context():
        login_as(client, "adv_admin")
    resp_admin = client.get("/admin/api/maintenance-check", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp_admin.status_code == 200
    assert resp_admin.is_json
    assert "active" in resp_admin.get_json()


# ============================================================================
# Section 3: Deep Adversarial IDOR Stress Testing on Shared Agenda
# ============================================================================

def test_shared_agenda_idor_creation_spoofing(client, app):
    """Technician 1 attempts to create agenda entries for other technicians and outsiders."""
    with app.app_context():
        u1 = User.query.filter_by(usuario="adv_tec1").first()
        u2 = User.query.filter_by(usuario="adv_tec2").first()
        u3 = User.query.filter_by(usuario="adv_tec3").first()
        u_std = User.query.filter_by(usuario="adv_std").first()
        u2_id = u2.id
        u3_id = u3.id
        std_id = u_std.id

    # Login as Tec 1
    with app.app_context():
        login_as(client, "adv_tec1")

    # Attempt 1: Create for Tec 2
    resp1 = client.post(
        "/admin/suporte/api/agenda/criar",
        data={"usuario_id": str(u2_id), "unidade": "Spoofed Unit", "data_atendimento": "2026-09-10", "periodo": "Manhã"},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert resp1.status_code == 403

    # Attempt 2: Create for Tec 3 (Oficina)
    resp2 = client.post(
        "/admin/suporte/api/agenda/criar",
        data={"usuario_id": str(u3_id), "unidade": "Spoofed Unit 2", "data_atendimento": "2026-09-10", "periodo": "Tarde"},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert resp2.status_code == 403

    # Attempt 3: Create for standard user
    resp3 = client.post(
        "/admin/suporte/api/agenda/criar",
        data={"usuario_id": str(std_id), "unidade": "Spoofed Unit 3", "data_atendimento": "2026-09-10", "periodo": "Dia todo"},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert resp3.status_code == 403

    # Verify nothing was created for any other user
    with app.app_context():
        assert AgendaEntry.query.filter_by(unidade="Spoofed Unit").first() is None
        assert AgendaEntry.query.filter_by(unidade="Spoofed Unit 2").first() is None
        assert AgendaEntry.query.filter_by(unidade="Spoofed Unit 3").first() is None


def test_shared_agenda_idor_lateral_update_and_reassignment_attack(client, app):
    """Technician 2 attempts to modify Tec 1's entry, or Tec 1 attempts to reassign to Tec 2."""
    with app.app_context():
        u1 = User.query.filter_by(usuario="adv_tec1").first()
        u2 = User.query.filter_by(usuario="adv_tec2").first()
        u1_id = u1.id
        u2_id = u2.id

        # Create entry owned by Tec 1
        entry = AgendaEntry(
            usuario_id=u1_id,
            unidade="Original Unit Tec 1",
            data_atendimento=date(2026, 9, 15),
            periodo="Manhã",
            obs="Legitimate task"
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    # Attack 1: Tec 2 tries to update Tec 1's entry
    with app.app_context():
        login_as(client, "adv_tec2")

    resp_atk1 = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={"unidade": "Hacked Unit", "obs": "Hacked by Tec 2"},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert resp_atk1.status_code == 403

    # Attack 2: Tec 2 tries to steal and reassign Tec 1's entry to themselves
    resp_atk2 = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={"usuario_id": str(u2_id), "unidade": "Stolen Unit"},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert resp_atk2.status_code == 403

    # Attack 3: Tec 1 tries to reassign their own entry to Tec 2 (offloading work)
    with app.app_context():
        login_as(client, "adv_tec1")

    resp_atk3 = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={"usuario_id": str(u2_id), "unidade": "Offloaded Unit"},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert resp_atk3.status_code == 403

    # Verify entry remains unchanged in database
    with app.app_context():
        fresh = AgendaEntry.query.get(entry_id)
        assert fresh.usuario_id == u1_id
        assert fresh.unidade == "Original Unit Tec 1"
        assert fresh.obs == "Legitimate task"


def test_shared_agenda_idor_lateral_deletion_attack(client, app):
    """Technician 2 attempts to delete Technician 1's agenda entry."""
    with app.app_context():
        u1 = User.query.filter_by(usuario="adv_tec1").first()

        entry = AgendaEntry(
            usuario_id=u1.id,
            unidade="Do Not Delete Unit",
            data_atendimento=date(2026, 9, 20),
            periodo="Tarde",
            obs="Critical appointment"
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    # Tec 2 attempts deletion
    with app.app_context():
        login_as(client, "adv_tec2")

    resp = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/excluir",
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert resp.status_code == 403

    # Verify entry is still intact
    with app.app_context():
        assert AgendaEntry.query.get(entry_id) is not None


def test_shared_agenda_boundary_and_nonexistent_ids(client, app):
    """Test boundary conditions, invalid IDs, and 404 handling."""
    with app.app_context():
        login_as(client, "adv_tec1")

    # Non-existent entry ID update -> 404
    resp_up = client.post("/admin/suporte/api/agenda/99999999/atualizar", data={"unidade": "Nowhere"})
    assert resp_up.status_code == 404

    # Non-existent entry ID delete -> 404
    resp_del = client.post("/admin/suporte/api/agenda/99999999/excluir")
    assert resp_del.status_code == 404


def test_shared_agenda_privileged_roles_delegation(client, app):
    """Test that Gestor, Admin, and Tech Leader (admin_agenda_tecnica) CAN manage any technician's agenda."""
    with app.app_context():
        u1 = User.query.filter_by(usuario="adv_tec1").first()
        u2 = User.query.filter_by(usuario="adv_tec2").first()
        u1_id = u1.id
        u2_id = u2.id

        entry = AgendaEntry(
            usuario_id=u1_id,
            unidade="Delegated Test Unit",
            data_atendimento=date(2026, 9, 25),
            periodo="Manhã",
            obs="Initial state"
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    # 1. Gestor updates and reassigns entry
    with app.app_context():
        login_as(client, "adv_gestor")

    resp_gestor = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={"usuario_id": str(u2_id), "unidade": "Gestor Reassigned"},
        follow_redirects=False
    )
    assert resp_gestor.status_code == 302

    with app.app_context():
        updated = AgendaEntry.query.get(entry_id)
        assert updated.usuario_id == u2_id
        assert updated.unidade == "Gestor Reassigned"

    # 2. Tech Leader (has admin_agenda_tecnica permission) reassigns back to Tec 1
    with app.app_context():
        login_as(client, "adv_tech_lead")

    resp_lead = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={"usuario_id": str(u1_id), "unidade": "Leader Reassigned"},
        follow_redirects=False
    )
    assert resp_lead.status_code == 302

    with app.app_context():
        updated_lead = AgendaEntry.query.get(entry_id)
        assert updated_lead.usuario_id == u1_id
        assert updated_lead.unidade == "Leader Reassigned"

    # 3. Admin deletes entry
    with app.app_context():
        login_as(client, "adv_admin")

    resp_admin = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/excluir",
        follow_redirects=False
    )
    assert resp_admin.status_code == 302

    with app.app_context():
        assert AgendaEntry.query.get(entry_id) is None


def test_shared_agenda_assistencia_blueprint_mounting_idor(client, app):
    """Test that agenda routes mounted on assist_bp also enforce IDOR protections."""
    with app.app_context():
        u1 = User.query.filter_by(usuario="adv_tec1").first()
        u2 = User.query.filter_by(usuario="adv_tec2").first()

        # Create entry for Tec 1
        entry = AgendaEntry(
            usuario_id=u1.id,
            unidade="Assist Unit Tec 1",
            data_atendimento=date(2026, 9, 28),
            periodo="Manhã",
            obs="Assistencia task"
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    # Tec 2 attempts update via assistencia blueprint route
    with app.app_context():
        login_as(client, "adv_tec2")

    resp_assist_idor = client.post(
        f"/assistencia/api/agenda/{entry_id}/atualizar",
        data={"unidade": "Assistencia Hacked Unit"},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert resp_assist_idor.status_code == 403

    # Tec 2 attempts delete via assistencia blueprint route
    resp_assist_del = client.post(
        f"/assistencia/api/agenda/{entry_id}/excluir",
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert resp_assist_del.status_code == 403

    with app.app_context():
        assert AgendaEntry.query.get(entry_id) is not None
