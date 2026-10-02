import pytest
from datetime import datetime, date
from sqlalchemy import event
from sqlalchemy.engine import Engine
from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Department, AgendaEntry


# Register SQLite helper functions for compatibility
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


class TestConfig:
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-phase2-key"
    MAIL_ENABLED = False


@pytest.fixture
def app():
    app_instance = create_app(TestConfig)
    with app_instance.app_context():
        db.create_all()

        # 1. Departments
        dept_sup = Department.query.filter_by(slug="suporte").first()
        if not dept_sup:
            dept_sup = Department(name="SUPORTE", slug="suporte")
            db.session.add(dept_sup)

        dept_admin = Department.query.filter_by(slug="administracao").first()
        if not dept_admin:
            dept_admin = Department(name="ADMINISTRACAO", slug="administracao")
            db.session.add(dept_admin)

        db.session.commit()

        # 2. Standard user (unprivileged)
        user_std = User(
            usuario="sec_user_std",
            nome_completo="Standard User",
            email="std_sec_test@sollus.com",
            tipo="usuario",
            role="user",
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={},
        )
        db.session.add(user_std)

        # 3. Technician user 1 (with SUPORTE dept)
        user_tec1 = User(
            usuario="sec_user_tec1",
            nome_completo="Tecnico 1",
            email="tec1_sec_test@sollus.com",
            tipo="tecnico",
            role="user",
            department_id=dept_sup.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={},
        )
        db.session.add(user_tec1)

        # 4. Technician user 2 (with SUPORTE dept)
        user_tec2 = User(
            usuario="sec_user_tec2",
            nome_completo="Tecnico 2",
            email="tec2_sec_test@sollus.com",
            tipo="tecnico",
            role="user",
            department_id=dept_sup.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={},
        )
        db.session.add(user_tec2)

        # 5. Admin user
        user_admin = User(
            usuario="sec_user_admin",
            nome_completo="Admin User",
            email="admin_sec_test@sollus.com",
            tipo="admin",
            role="admin",
            department_id=dept_admin.id,
            password_hash="pbkdf2:sha256:dummy",
            is_active=True,
            permissions={
                "usuarios_acesso": True,
                "usuarios_gerenciar": True,
                "permissoes_gerenciar": True,
                "admin_agenda_tecnica": True,
                "admin_suporte": True,
                "admin_assistencia": True,
            }
        )
        db.session.add(user_admin)
        db.session.commit()

        # Connect user_departments
        user_tec1.departments.append(dept_sup)
        user_tec2.departments.append(dept_sup)
        user_admin.departments.append(dept_admin)
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
# 1. Test Unauthenticated Requests Across All 13 Blueprint Hooks
# ============================================================================

ALL_13_HOOK_ENDPOINTS = [
    # 1. support_bp
    ("/admin/suporte/api/agenda", "/admin/suporte/atendimentos"),
    # 2. tech_bp
    ("/admin/tecnica/api/chamados", "/admin/tecnica/chamados"),
    # 3. assist_bp
    ("/assistencia/api/agenda", "/assistencia/"),
    # 4. atestados_bp
    ("/assistencia/atestados/task-status/dummy-id", "/assistencia/atestados/"),
    # 5. propostas_bp
    ("/api/jobs/dummy-id", "/nova_proposta"),
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


@pytest.mark.parametrize("api_endpoint,html_endpoint", ALL_13_HOOK_ENDPOINTS)
def test_unauthenticated_api_returns_401(client, api_endpoint, html_endpoint):
    """Unauthenticated API/AJAX calls must return HTTP 401 with JSON error payload."""
    resp = client.get(
        api_endpoint,
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    )
    assert resp.status_code == 401, f"Expected 401 for unauthenticated API {api_endpoint}, got {resp.status_code}"
    data = resp.get_json()
    assert data is not None
    assert data.get("error") == "Authentication required" or data.get("success") is False or "Autenticação" in str(data)


@pytest.mark.parametrize("api_endpoint,html_endpoint", ALL_13_HOOK_ENDPOINTS)
def test_unauthenticated_html_redirects_to_login(client, api_endpoint, html_endpoint):
    """Unauthenticated HTML browser requests must return HTTP 302 redirecting to login."""
    resp = client.get(
        html_endpoint,
        headers={"Accept": "text/html"}
    )
    assert resp.status_code == 302, f"Expected 302 redirect for unauthenticated HTML {html_endpoint}, got {resp.status_code}"
    loc = resp.headers.get("Location", "")
    assert "/login" in loc or "auth" in loc


# ============================================================================
# 2. Test Unauthorized Requests Across Blueprint API & HTML Endpoints
# ============================================================================

RESTRICTED_API_ENDPOINTS = [
    "/admin/suporte/api/agenda",
    "/admin/tecnica/api/chamados",
    "/assistencia/api/dashboard",
    "/assistencia/atestados/task-status/dummy-id",
    "/admin/api/maintenance-check",
    "/financeiro/contas-receber",
    "/contratos/cancelados",
    "/audit/api",
    "/audit/export",
]


@pytest.mark.parametrize("api_endpoint", RESTRICTED_API_ENDPOINTS)
def test_unauthorized_user_api_returns_403(app, client, api_endpoint):
    """Authenticated users without permission must receive HTTP 403 on restricted APIs."""
    with app.app_context():
        login_as(client, "sec_user_std")

    resp = client.get(
        api_endpoint,
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    )
    assert resp.status_code == 403, f"Expected 403 for unauthorized user on {api_endpoint}, got {resp.status_code}"
    data = resp.get_json()
    assert data is not None
    assert data.get("error") == "Access denied" or data.get("success") is False or "permissão" in str(data) or "Acesso negado" in str(data)


# ============================================================================
# 3. Test Sensitive Endpoints: /api/cnpj/<cnpj> & /admin/api/maintenance-check
# ============================================================================

def test_cnpj_endpoint_unauthenticated(client):
    """Unauthenticated access to /api/cnpj/<cnpj> must be blocked (302 or 401)."""
    resp = client.get("/api/cnpj/00000000000191", headers={"Accept": "application/json"})
    assert resp.status_code in (302, 401)


def test_cnpj_endpoint_authenticated(app, client):
    """Authenticated access to /api/cnpj/<cnpj> with invalid format returns 400."""
    with app.app_context():
        login_as(client, "sec_user_std")

    resp = client.get("/api/cnpj/invalid123")
    assert resp.status_code == 400


def test_maintenance_check_access_levels(app, client):
    """Test /admin/api/maintenance-check across unauth, standard, and admin."""
    # 1. Unauthenticated -> 401
    resp = client.get("/admin/api/maintenance-check", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 401

    # 2. Standard user -> 403
    with app.app_context():
        login_as(client, "sec_user_std")
    resp = client.get("/admin/api/maintenance-check", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 403

    # 3. Admin user -> 200
    with app.app_context():
        login_as(client, "sec_user_admin")
    resp = client.get("/admin/api/maintenance-check", headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200


# ============================================================================
# 4. Test Shared Agenda Ownership & IDOR Protections
# ============================================================================

def test_shared_agenda_idor_create_other_user(app, client):
    """Technician 1 cannot create an agenda entry for Technician 2 (403 Forbidden)."""
    with app.app_context():
        user_tec2 = User.query.filter_by(usuario="sec_user_tec2").first()
        target_uid = user_tec2.id
        login_as(client, "sec_user_tec1")

    resp = client.post(
        "/admin/suporte/api/agenda/criar",
        data={
            "usuario_id": str(target_uid),
            "unidade": "Matriz",
            "data_atendimento": "2026-09-01",
            "periodo": "Manhã",
            "obs": "IDOR attempt",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 403


def test_shared_agenda_own_entry_lifecycle(app, client):
    """Technician 1 CAN create, update, and delete their OWN agenda entry."""
    with app.app_context():
        user_tec1 = User.query.filter_by(usuario="sec_user_tec1").first()
        user_tec2 = User.query.filter_by(usuario="sec_user_tec2").first()
        u1_id = user_tec1.id
        u2_id = user_tec2.id

    # 1. Create own entry as Tec 1
    with app.app_context():
        login_as(client, "sec_user_tec1")
    resp_create = client.post(
        "/admin/suporte/api/agenda/criar",
        data={
            "usuario_id": str(u1_id),
            "unidade": "Filial SP",
            "data_atendimento": "2026-09-02",
            "periodo": "Tarde",
            "obs": "Legitimate appointment",
        },
        follow_redirects=False,
    )
    assert resp_create.status_code == 302

    # Find created entry
    with app.app_context():
        entry = AgendaEntry.query.filter_by(
            usuario_id=u1_id,
            unidade="Filial SP"
        ).order_by(AgendaEntry.id.desc()).first()
        assert entry is not None
        entry_id = entry.id

    # 2. Update own entry as Tec 1
    with app.app_context():
        login_as(client, "sec_user_tec1")
    resp_update = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={
            "usuario_id": str(u1_id),
            "unidade": "Filial SP Atualizada",
            "data_atendimento": "2026-09-03",
            "periodo": "Dia todo",
            "obs": "Updated notes",
        },
        follow_redirects=False,
    )
    assert resp_update.status_code == 302

    with app.app_context():
        updated_entry = AgendaEntry.query.get(entry_id)
        assert updated_entry.unidade == "Filial SP Atualizada"

    # 3. Technician 2 attempts to update Technician 1's entry -> 403
    with app.app_context():
        login_as(client, "sec_user_tec2")
    resp_idor_update = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={
            "unidade": "Hacked Unidade",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_idor_update.status_code == 403

    # 4. Technician 2 attempts to delete Technician 1's entry -> 403
    resp_idor_delete = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/excluir",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_idor_delete.status_code == 403

    # 5. Technician 1 deletes own entry -> 302
    with app.app_context():
        login_as(client, "sec_user_tec1")
    resp_delete = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/excluir",
        follow_redirects=False,
    )
    assert resp_delete.status_code == 302

    with app.app_context():
        assert AgendaEntry.query.get(entry_id) is None


def test_admin_can_manage_all_agenda_entries(app, client):
    """Admin can create, update, and delete entries for any technician."""
    with app.app_context():
        user_tec1 = User.query.filter_by(usuario="sec_user_tec1").first()
        user_tec2 = User.query.filter_by(usuario="sec_user_tec2").first()

        entry = AgendaEntry(
            usuario_id=user_tec1.id,
            unidade="Admin Test Hub",
            data_atendimento=datetime.strptime("2026-09-05", "%Y-%m-%d").date(),
            periodo="Manhã",
            obs="Admin management test",
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id
        tec2_id = user_tec2.id

    # Admin modifies Tec 1's entry
    with app.app_context():
        login_as(client, "sec_user_admin")
    resp_update = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/atualizar",
        data={
            "usuario_id": str(tec2_id),  # Reassign to Tec 2
            "unidade": "Admin Reassigned Hub",
        },
        follow_redirects=False,
    )
    assert resp_update.status_code == 302

    with app.app_context():
        reassigned = AgendaEntry.query.get(entry_id)
        assert reassigned.usuario_id == tec2_id
        assert reassigned.unidade == "Admin Reassigned Hub"

    # Admin deletes the entry
    resp_delete = client.post(
        f"/admin/suporte/api/agenda/{entry_id}/excluir",
        follow_redirects=False,
    )
    assert resp_delete.status_code == 302

    with app.app_context():
        assert AgendaEntry.query.get(entry_id) is None
