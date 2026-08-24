import unittest
from datetime import datetime, timedelta
from sqlalchemy.pool import StaticPool
from extensions import db
from platform_app import create_app
from modules.propostas.models import User
from modules.sollus_tickets.models import SollusTicket, SollusTicketContact, SollusTicketLock


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


class TestSollusTicketsLockConflict(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create users (make user_trying an admin to ensure they have access to all tickets)
        self.user_locking = User(
            usuario="victor.viana",
            nome_completo="Victor Viana",
            email="ti2@sollusgroup.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="admin",
            role="admin",
            is_active=True,
            permissions={"chamados": True}
        )
        self.user_trying = User(
            usuario="larissa.anjos",
            nome_completo="Larissa Anjos",
            email="adm3@sollusgroup.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="admin",
            role="admin",
            is_active=True,
            permissions={"chamados": True}
        )
        db.session.add_all([self.user_locking, self.user_trying])
        db.session.commit()

        # Create contact
        self.contact = SollusTicketContact(
            name="Client X",
            email="client_x@sollus.com",
            is_active=True
        )
        db.session.add(self.contact)
        db.session.commit()

        # Create ticket
        self.ticket = SollusTicket(
            number="001672",
            subject="teste",
            status_key="open",
            priority_key="normal",
            contact_id=self.contact.id,
            created_at=datetime.utcnow()
        )
        db.session.add(self.ticket)
        db.session.commit()

        # Add active lock on ticket owned by user_locking
        self.lock = SollusTicketLock(
            ticket_id=self.ticket.id,
            user_id=self.user_locking.id,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=15)
        )
        db.session.add(self.lock)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_reply_on_locked_ticket_returns_custom_409_page(self):
        # Log in as user_trying (Larissa Anjos)
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(self.user_trying.id)
            sess["_fresh"] = True

        # Try to reply to the locked ticket
        response = self.client.post(
            f"/sollus-tickets/{self.ticket.id}/responder",
            data={"body": "Resposta teste", "visibility": "public"}
        )

        # Assert status code 409 Conflict
        self.assertEqual(response.status_code, 409)

        # Assert custom error page text is rendered
        html = response.data.decode("utf-8")
        self.assertIn("Ticket em Uso", html)
        self.assertIn("Victor Viana", html)
        self.assertIn("O chamado está temporariamente bloqueado", html)

    def test_direct_upload_on_locked_ticket_returns_custom_409_page(self):
        # Log in as user_trying (Larissa Anjos)
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(self.user_trying.id)
            sess["_fresh"] = True

        # Try to upload file to the locked ticket
        response = self.client.post(
            f"/sollus-tickets/{self.ticket.id}/upload-anexo"
        )

        # Assert status code 409 Conflict
        self.assertEqual(response.status_code, 409)

        # Assert custom error page text is rendered
        html = response.data.decode("utf-8")
        self.assertIn("Ticket em Uso", html)
        self.assertIn("Victor Viana", html)
