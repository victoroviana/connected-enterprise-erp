import unittest
from datetime import datetime
from io import BytesIO
from sqlalchemy.pool import StaticPool
from extensions import db
from platform_app import create_app
from modules.propostas.models import User
from modules.sollus_tickets.models import SollusTicket, SollusTicketAttachment, SollusTicketContact


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


class TestSollusTicketsAttachments(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create admin user
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
        db.session.add(self.admin_user)
        db.session.commit()

        # Create contact
        self.contact_x = SollusTicketContact(
            name="Client X",
            email="client_x@sollus.com",
            is_active=True
        )
        db.session.add(self.contact_x)
        db.session.commit()

        # Create ticket
        self.ticket = SollusTicket(
            number="000001",
            subject="Ticket Test Attachments",
            status_key="open",
            priority_key="normal",
            contact_id=self.contact_x.id,
            created_at=datetime.utcnow()
        )
        db.session.add(self.ticket)
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

    def test_reply_with_attachments(self):
        """Test replying to a ticket with multiple attachments."""
        self.login_as(self.admin_user)

        data = {
            "body": "Replying to ticket with attachments",
            "visibility": "public",
            "attachments": [
                (BytesIO(b"dummy image content 1"), "screenshot1.png"),
                (BytesIO(b"dummy log content 2"), "log_file2.log")
            ]
        }

        response = self.client.post(
            f"/sollus-tickets/{self.ticket.id}/responder",
            data=data,
            content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 302) # redirects back to detail page

        # Verify attachments are created in DB
        attachments = SollusTicketAttachment.query.filter_by(ticket_id=self.ticket.id).all()
        self.assertEqual(len(attachments), 2)
        names = {att.original_name for att in attachments}
        self.assertIn("screenshot1.png", names)
        self.assertIn("log_file2.log", names)
        # Verify uploader is set
        for att in attachments:
            self.assertEqual(att.uploaded_by_id, self.admin_user.id)
            self.assertIsNotNone(att.entry_id) # thread entry should be linked

    def test_direct_upload_attachments(self):
        """Test uploading attachments directly through the sidebar."""
        self.login_as(self.admin_user)

        data = {
            "attachments": [
                (BytesIO(b"document text"), "document.docx"),
                (BytesIO(b"excel sheet data"), "report.xlsx")
            ]
        }

        response = self.client.post(
            f"/sollus-tickets/{self.ticket.id}/upload-anexo",
            data=data,
            content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 302)

        # Verify attachments are created in DB
        attachments = SollusTicketAttachment.query.filter_by(ticket_id=self.ticket.id).all()
        self.assertEqual(len(attachments), 2)
        names = {att.original_name for att in attachments}
        self.assertIn("document.docx", names)
        self.assertIn("report.xlsx", names)
        for att in attachments:
            self.assertEqual(att.uploaded_by_id, self.admin_user.id)
            self.assertIsNone(att.entry_id) # direct uploads don't link a thread entry

    def test_download_attachment_scenarios(self):
        """Test download attachment scenarios including missing file, empty path, etc."""
        self.login_as(self.admin_user)

        # 1. Attachment with empty storage path
        att_empty = SollusTicketAttachment(
            ticket_id=self.ticket.id,
            original_name="empty_path.txt",
            storage_path="",
            content_type="text/plain"
        )
        # 2. Attachment with None storage path
        att_none = SollusTicketAttachment(
            ticket_id=self.ticket.id,
            original_name="none_path.txt",
            storage_path=None,
            content_type="text/plain"
        )
        # 3. Attachment with nonexistent path
        att_missing = SollusTicketAttachment(
            ticket_id=self.ticket.id,
            original_name="missing_file.txt",
            storage_path="sollus_tickets/99999/does_not_exist.txt",
            content_type="text/plain"
        )

        db.session.add_all([att_empty, att_none, att_missing])
        db.session.commit()

        # Try downloading empty path -> should return 404 (not 500!)
        response = self.client.get(f"/sollus-tickets/{self.ticket.id}/anexos/{att_empty.id}/download")
        self.assertEqual(response.status_code, 404)

        # Try downloading None path -> should return 404 (not 500!)
        response = self.client.get(f"/sollus-tickets/{self.ticket.id}/anexos/{att_none.id}/download")
        self.assertEqual(response.status_code, 404)

        # Try downloading missing file path -> should return 404 (not 500!)
        response = self.client.get(f"/sollus-tickets/{self.ticket.id}/anexos/{att_missing.id}/download")
        self.assertEqual(response.status_code, 404)

        # 4. Attachment with existing file path (relative to uploads)
        from pathlib import Path
        uploads_dir = Path(self.app.config.get("UPLOADS_DIR", "uploads"))
        uploads_dir.mkdir(exist_ok=True)
        ticket_dir = uploads_dir / "sollus_tickets" / str(self.ticket.id)
        ticket_dir.mkdir(parents=True, exist_ok=True)
        file_path = ticket_dir / "test_existing.txt"
        file_path.write_bytes(b"hello world")

        att_existing = SollusTicketAttachment(
            ticket_id=self.ticket.id,
            original_name="test_existing.txt",
            storage_path=f"sollus_tickets/{self.ticket.id}/test_existing.txt",
            content_type="text/plain"
        )
        db.session.add(att_existing)
        db.session.commit()

        # Try downloading existing path -> should return 200 OK!
        response = self.client.get(f"/sollus-tickets/{self.ticket.id}/anexos/{att_existing.id}/download")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"hello world")
        response.close()

        # Clean up
        if file_path.exists():
            file_path.unlink()



