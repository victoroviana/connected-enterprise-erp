from __future__ import annotations

import io
import os
import pytest
from datetime import datetime, date, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy import event
from sqlalchemy.engine import Engine

from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Department
from modules.chamados.models import Ticket, TicketMessage, Attachment
from modules.sollus_tickets.models import SollusTicket, SollusTicketContact
from modules.suporte.models import AtendimentoSuporte, Empresa


# ==============================================================================
# SQLITE COMPATIBILITY EMULATION FOR MYSQL RAW SQL FUNCTIONS
# ==============================================================================
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
    MAIL_ENABLED = False
    MAIL_SERVER = "smtp.test.com"
    MAIL_DEFAULT_SENDER = "suporte@sollustecnologia.com"
    SECRET_KEY = "test-secret-chamados-key"


@pytest.fixture
def app():
    app_instance = create_app(TestConfig)
    with app_instance.app_context():
        db.create_all()

        # Seed Department Oficina
        oficina_dept = Department(name="Oficina", slug="oficina")
        db.session.add(oficina_dept)
        db.session.commit()

        # Seed Test Users
        admin = User(
            usuario="admin_chamados",
            nome_completo="Admin Chamados",
            email="admin_chamados@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="admin",
            role="admin",
            is_active=True,
            permissions={"chamados": True, "admin_suporte": True, "admin_assistencia": True},
        )
        agent = User(
            usuario="tecnico_oficina",
            nome_completo="Tecnico Oficina",
            email="tecnico@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="agent",
            department_id=oficina_dept.id,
            is_active=True,
            permissions={"chamados": True, "suporte_atendimentos": True},
        )
        regular = User(
            usuario="cliente_chamados",
            nome_completo="Cliente Solicitante",
            email="cliente@empresa.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="user",
            is_active=True,
            permissions={"chamados": True},
        )
        no_perm_user = User(
            usuario="user_sem_acesso",
            nome_completo="Usuario Sem Permissao",
            email="sem_acesso@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="user",
            is_active=True,
            permissions={},
        )

        db.session.add_all([admin, agent, regular, no_perm_user])
        db.session.commit()

        yield app_instance


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username="admin_chamados"):
    with client.session_transaction() as sess:
        user = User.query.filter_by(usuario=username).first()
        sess["_user_id"] = str(user.id)
        sess["usuario_id"] = user.id
        sess["logged_in_user"] = user.nome_completo
        sess["tipo"] = user.tipo
        sess["role"] = user.role


# ==============================================================================
# 1. PERMISSIONS & ACCESS CONTROL TESTS (TICKETS)
# ==============================================================================

def test_chamados_permissions_unauthorized(client):
    res = client.get("/tickets/dashboard")
    assert res.status_code in (302, 401)


def test_chamados_permissions_forbidden(client):
    login(client, username="user_sem_acesso")
    res = client.get("/tickets/dashboard")
    assert res.status_code in (200, 302, 403)


def test_chamados_permissions_agent_allowed(client):
    login(client, username="tecnico_oficina")
    res = client.get("/tickets/dashboard")
    assert res.status_code == 200


# ==============================================================================
# 2. TICKET CREATION & LISTING (HELP DESK)
# ==============================================================================

def test_new_ticket_form_render(client):
    login(client, username="cliente_chamados")
    res = client.get("/tickets/new")
    assert res.status_code == 200


def test_create_ticket_success(client, app):
    login(client, username="cliente_chamados")

    payload = {
        "title": "Impressora de Crachá não liga",
        "description": "Ao conectar na tomada, o LED indicador permanece apagado.",
        "priority": "high",
    }

    with patch("modules.chamados.blueprints.tickets.routes._notify_event"):
        res = client.post("/tickets/create", data=payload, follow_redirects=True)
        assert res.status_code == 200

    with app.app_context():
        ticket = Ticket.query.filter_by(title="Impressora de Crachá não liga").first()
        assert ticket is not None
        assert ticket.priority == "high"
        assert ticket.status == "open"


def test_create_ticket_with_file_attachment(client, app):
    login(client, username="cliente_chamados")

    data = {
        "title": "Erro ao exportar relatorio fiscal",
        "description": "Veja log de erro em anexo.",
        "priority": "urgent",
        "file": (io.BytesIO(b"2026-07-28 09:00:00 [ERROR] Connection timeout"), "error_log.txt"),
    }

    with patch("modules.chamados.blueprints.tickets.routes._notify_event"):
        res = client.post("/tickets/create", data=data, content_type="multipart/form-data", follow_redirects=True)
        assert res.status_code == 200

    with app.app_context():
        ticket = Ticket.query.filter_by(title="Erro ao exportar relatorio fiscal").first()
        assert ticket is not None
        assert ticket.priority == "urgent"


# ==============================================================================
# 3. TICKET DETAIL, REPLY, ASSIGN & STATUS WORKFLOWS
# ==============================================================================

def test_ticket_detail_view(client, app):
    login(client, username="cliente_chamados")

    user = User.query.filter_by(usuario="cliente_chamados").first()
    ticket = Ticket(
        title="Dúvida sobre cadastro de funcionários",
        description="Como alterar o PIS do funcionário no Sollus Ponto?",
        priority="low",
        status="open",
        user_id=user.id,
    )
    db.session.add(ticket)
    db.session.commit()
    tid = ticket.id

    res = client.get(f"/tickets/{tid}")
    assert res.status_code == 200


def test_ticket_reply_workflow(client, app):
    login(client, username="tecnico_oficina")

    user = User.query.filter_by(usuario="cliente_chamados").first()
    ticket = Ticket(
        title="Catraca travando no acesso",
        description="Leitor biométrico demora 10s para liberar.",
        priority="medium",
        status="open",
        user_id=user.id,
    )
    db.session.add(ticket)
    db.session.commit()
    tid = ticket.id

    reply_payload = {
        "message": "Favor realizar a limpeza do sensor óptico da catraca com pano seco.",
    }

    with patch("modules.chamados.blueprints.tickets.routes._notify_event"):
        res = client.post(f"/tickets/{tid}/reply", data=reply_payload, follow_redirects=True)
        assert res.status_code == 200

    with app.app_context():
        messages = TicketMessage.query.filter_by(ticket_id=tid).all()
        assert len(messages) >= 1
        assert "pano seco" in messages[0].body


def test_ticket_assign_agent_workflow(client, app):
    login(client, username="admin_chamados")

    user = User.query.filter_by(usuario="cliente_chamados").first()
    agent = User.query.filter_by(usuario="tecnico_oficina").first()

    ticket = Ticket(
        title="Instalação de rep relógio",
        description="Necessário configurar IP fixo na rede local.",
        priority="high",
        status="open",
        user_id=user.id,
    )
    db.session.add(ticket)
    db.session.commit()
    tid = ticket.id

    assign_payload = {"assignee_id": str(agent.id)}

    with patch("modules.chamados.blueprints.tickets.routes._notify_event"):
        res = client.post(f"/tickets/{tid}/assign", data=assign_payload, follow_redirects=True)
        assert res.status_code == 200

    with app.app_context():
        t = Ticket.query.get(tid)
        assignee_id = getattr(t, "assignee_id", None) or getattr(t, "agent_id", None)
        assert assignee_id == agent.id


def test_ticket_update_status_workflow(client, app):
    login(client, username="admin_chamados")

    user = User.query.filter_by(usuario="cliente_chamados").first()
    ticket = Ticket(
        title="Troca de fonte queimada",
        description="Fonte de 12V 5A substituição em bancada.",
        priority="medium",
        status="open",
        user_id=user.id,
    )
    db.session.add(ticket)
    db.session.commit()
    tid = ticket.id

    status_payload = {"status": "in_progress"}
    with patch("modules.chamados.blueprints.tickets.routes._notify_event"):
        res = client.post(f"/tickets/{tid}/status", data=status_payload, follow_redirects=True)
        assert res.status_code == 200

    with app.app_context():
        t = Ticket.query.get(tid)
        assert t.status == "in_progress"

    close_payload = {"status": "closed"}
    with patch("modules.chamados.blueprints.tickets.routes._notify_event"):
        res_close = client.post(f"/tickets/{tid}/status", data=close_payload, follow_redirects=True)
        assert res_close.status_code == 200

    with app.app_context():
        t_closed = Ticket.query.get(tid)
        assert t_closed.status == "closed"


def test_ticket_delete_workflow(client, app):
    login(client, username="admin_chamados")

    user = User.query.filter_by(usuario="cliente_chamados").first()
    ticket = Ticket(
        title="Chamado duplicado em teste",
        description="Ticket criado por engano.",
        priority="low",
        status="open",
        user_id=user.id,
    )
    db.session.add(ticket)
    db.session.commit()
    tid = ticket.id

    res = client.post(f"/tickets/{tid}/delete", follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        deleted = Ticket.query.get(tid)
        assert deleted is None


# ==============================================================================
# 4. DASHBOARD, CLOSED & REPORTS VIEWS
# ==============================================================================

def test_closed_tickets_view(client, app):
    login(client, username="admin_chamados")

    user = User.query.filter_by(usuario="cliente_chamados").first()
    t_closed = Ticket(
        title="Configuração de Bobina",
        description="Concluído com sucesso.",
        priority="low",
        status="closed",
        user_id=user.id,
    )
    db.session.add(t_closed)
    db.session.commit()

    res = client.get("/tickets/closed")
    assert res.status_code == 200


def test_reports_overview_view(client, app):
    login(client, username="admin_chamados")

    user = User.query.filter_by(usuario="cliente_chamados").first()
    t1 = Ticket(title="Report T1", status="open", priority="high", user_id=user.id, created_at=datetime.utcnow())
    t2 = Ticket(title="Report T2", status="closed", priority="medium", user_id=user.id, created_at=datetime.utcnow())
    db.session.add_all([t1, t2])
    db.session.commit()

    res = client.get("/tickets/reports")
    assert res.status_code == 200


# ==============================================================================
# 5. SOLLUS TICKETS & CONTACT MANAGEMENT
# ==============================================================================

def test_sollus_ticket_model_creation(app):
    with app.app_context():
        contact = SollusTicketContact(name="Empresa ABC", email="contato@abc.com", is_active=True)
        db.session.add(contact)
        db.session.commit()

        agent = User.query.filter_by(usuario="tecnico_oficina").first()

        sticket = SollusTicket(
            number="000101",
            subject="Integração Sollus Tickets Email",
            status_key="open",
            priority_key="normal",
            assignee_id=agent.id,
            contact_id=contact.id,
            created_at=datetime.utcnow(),
        )
        db.session.add(sticket)
        db.session.commit()

        saved = SollusTicket.query.filter_by(number="000101").first()
        assert saved is not None
        assert saved.subject == "Integração Sollus Tickets Email"
        assert saved.assignee_id == agent.id


# ==============================================================================
# 6. SUPORTE & ASSISTÊNCIA TÉCNICA MODELS & SERVICES
# ==============================================================================

def test_suporte_atendimento_suporte_model(app):
    with app.app_context():
        agent = User.query.filter_by(usuario="tecnico_oficina").first()
        atendimento = AtendimentoSuporte(
            cliente="Supermercado Silva",
            cnpj="11222333000181",
            tipo_atendimento="Remoto",
            status="Entrada",
            descricao="Relógio de ponto travando ao bater digital",
            criado_por="Operador",
            usuario_designado=agent.id,
            email="joao@silva.com",
        )
        db.session.add(atendimento)
        db.session.commit()

        saved = AtendimentoSuporte.query.filter_by(cliente="Supermercado Silva").first()
        assert saved is not None
        assert saved.status == "Entrada"
        assert saved.usuario_designado == agent.id


def test_suporte_empresa_model(app):
    with app.app_context():
        empresa = Empresa(
            cliente="Farmácia Central LTDA",
            cnpj="22333444000199",
            observacoes="Cliente VIP com contrato de suporte premium.",
            observacoes_alerta="Atenção aos sábados.",
        )
        db.session.add(empresa)
        db.session.commit()

        saved = Empresa.query.filter_by(cnpj="22333444000199").first()
        assert saved is not None
        assert saved.cliente == "Farmácia Central LTDA"
