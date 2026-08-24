import unittest
from datetime import datetime
from sqlalchemy.pool import StaticPool
from extensions import db
from platform_app import create_app
from modules.propostas.models import User
from modules.sollus_tickets.models import SollusTicket, SollusTicketContact


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False}
    }


class TestSollusTicketsRestrictions(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create agents
        self.agent_a = User(
            usuario="agent_a",
            nome_completo="Agent A",
            email="agent_a@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="agent",
            is_active=True,
            permissions={"chamados": True}
        )
        self.agent_b = User(
            usuario="agent_b",
            nome_completo="Agent B",
            email="agent_b@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="agent",
            is_active=True,
            permissions={"chamados": True}
        )
        self.admin_user = User(
            usuario="admin_u",
            nome_completo="Admin User",
            email="admin@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="admin",
            role="admin",
            is_active=True,
            permissions={"chamados": True}
        )
        db.session.add_all([self.agent_a, self.agent_b, self.admin_user])
        db.session.commit()

        # Create contacts
        self.contact_x = SollusTicketContact(
            name="Client X",
            email="client_x@sollus.com",
            is_active=True
        )
        db.session.add(self.contact_x)
        db.session.commit()

        # Create tickets
        self.ticket_a = SollusTicket(
            number="000001",
            subject="Ticket assigned to Agent A",
            status_key="open",
            priority_key="normal",
            assignee_id=self.agent_a.id,
            contact_id=self.contact_x.id,
            created_at=datetime.utcnow()
        )
        self.ticket_b = SollusTicket(
            number="000002",
            subject="Ticket assigned to Agent B",
            status_key="open",
            priority_key="normal",
            assignee_id=self.agent_b.id,
            contact_id=self.contact_x.id,
            created_at=datetime.utcnow()
        )
        db.session.add_all([self.ticket_a, self.ticket_b])
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login_as(self, user):
        with self.client.session_transaction() as sess:
            sess["usuario_id"] = user.id
            sess["user_id"] = user.id
            sess["_user_id"] = str(user.id)
            sess["tipo"] = user.tipo
            sess["logged_in_user"] = user.nome_completo

    def test_agent_a_can_only_see_own_assigned_tickets(self):
        """Test that Agent A can only see the ticket assigned to them."""
        self.login_as(self.agent_a)
        
        # Dashboard page access should render the list containing ticket_a but not ticket_b
        response = self.client.get("/sollus-tickets/")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("Ticket assigned to Agent A", html)
        self.assertNotIn("Ticket assigned to Agent B", html)

        # Accessing own ticket detail page should succeed
        response = self.client.get(f"/sollus-tickets/{self.ticket_a.id}")
        self.assertEqual(response.status_code, 200)

        # Accessing other agent's ticket detail page should return 404
        response = self.client.get(f"/sollus-tickets/{self.ticket_b.id}")
        self.assertEqual(response.status_code, 404)

    def test_admin_can_see_all_tickets(self):
        """Test that Admin can see all tickets."""
        self.login_as(self.admin_user)
        
        response = self.client.get("/sollus-tickets/")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("Ticket assigned to Agent A", html)
        self.assertIn("Ticket assigned to Agent B", html)

        # Accessing both ticket detail pages should succeed
        response = self.client.get(f"/sollus-tickets/{self.ticket_a.id}")
        self.assertEqual(response.status_code, 200)
        
        response = self.client.get(f"/sollus-tickets/{self.ticket_b.id}")
        self.assertEqual(response.status_code, 200)

    def test_solicitor_email_is_displayed_in_ticket_detail(self):
        """Test that the solicitor email is displayed in the ticket detail view sidebar."""
        self.login_as(self.admin_user)
        
        response = self.client.get(f"/sollus-tickets/{self.ticket_a.id}")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("client_x@sollus.com", html)


if __name__ == "__main__":
    unittest.main()
