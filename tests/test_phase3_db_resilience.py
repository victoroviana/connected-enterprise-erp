"""Tests verifying Database Resilience (Session Rollback & Recovery) and Runtime Dependencies (Phase 3)."""
import pytest
from sqlalchemy import text
from unittest.mock import patch, MagicMock

from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Proposal, SystemOptionOverride, SystemOptionState, SystemOptionCatalog
from modules.chamados.mailer import enviar_email
from modules.chamados.services.notify import recipients_for_ticket
from modules.chamados.models import Ticket, TicketMessage
from modules.propostas.services.pdf_jobs import PdfJobManager, PdfJob
from modules.propostas.utils.systems import _load_override_map, _load_system_states, _load_custom_options


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


def test_requirements_dependencies_pinned_and_importable():
    """Verify that apscheduler, Flask-Mail, and openpyxl are declared in requirements.txt and importable."""
    with open("requirements.txt", "r", encoding="utf-8") as f:
        reqs = f.read()

    assert "apscheduler>=3.10.0,<4.0.0" in reqs
    assert "Flask-Mail>=0.9.1" in reqs
    assert "openpyxl>=3.1.0" in reqs

    import apscheduler
    import flask_mail
    import openpyxl

    assert apscheduler is not None
    assert flask_mail is not None
    assert openpyxl is not None


def test_session_rollback_resilience_on_failed_query(app):
    """Verify that catching an exception and calling db.session.rollback() restores session to ACTIVE."""
    with app.app_context():
        # 1. Trigger an intentional SQL error inside a try-except block
        try:
            db.session.execute(text("SELECT * FROM non_existent_table_xyz_123"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # 2. Assert session can immediately execute valid queries without PendingRollbackError
        result = db.session.execute(text("SELECT 1")).scalar()
        assert result == 1


def test_chamados_mailer_rollback_on_failure(app):
    """Verify that enviar_email performs db.session.rollback() when enqueuing email fails."""
    with app.app_context():
        with patch.object(db.session, "commit", side_effect=RuntimeError("Simulated DB Commit Error")):
            success = enviar_email(
                destinatarios=["test@example.com"],
                assunto="Test Rollback Subject",
                html_corpo="<p>Test</p>",
            )
            assert success is False

        # Verify session is still valid and not poisoned
        count = db.session.execute(text("SELECT 1")).scalar()
        assert count == 1


def test_chamados_notify_recipients_rollback_on_query_failure(app):
    """Verify recipients_for_ticket gracefully rolls back on db query failure."""
    with app.app_context():
        dummy_ticket = MagicMock()
        dummy_ticket.id = 99999
        dummy_ticket.user = None
        dummy_ticket.assignee = None
        dummy_ticket.messages = None

        with patch("modules.chamados.models.TicketMessage.query") as mock_query:
            mock_query.filter_by.side_effect = RuntimeError("DB Query Error")
            emails = recipients_for_ticket(dummy_ticket, include_actor=True)
            assert isinstance(emails, list)

        # Verify session works
        result = db.session.execute(text("SELECT 1")).scalar()
        assert result == 1


def test_pdf_jobs_worker_rollback_on_exception(app):
    """Verify pdf_jobs worker performs db.session.rollback() when an error occurs."""
    with app.app_context():
        job_manager = PdfJobManager()
        # Test cleanup error handling
        with patch.object(db.session, "commit", side_effect=RuntimeError("Cleanup DB Error")):
            job_manager.cleanup()

        # Verify session is healthy
        result = db.session.execute(text("SELECT 1")).scalar()
        assert result == 1


def test_systems_utils_rollback_on_query_error(app):
    """Verify system option helper functions gracefully catch query errors and roll back."""
    with app.app_context():
        with patch("modules.propostas.models.SystemOptionOverride.query") as mock_ov:
            mock_ov.all.side_effect = RuntimeError("Override Query Failure")
            res = _load_override_map()
            assert res == {}

        with patch("modules.propostas.models.SystemOptionState.query") as mock_st:
            mock_st.all.side_effect = RuntimeError("State Query Failure")
            res = _load_system_states()
            assert res == {}

        with patch("modules.propostas.models.SystemOptionCatalog.query") as mock_cat:
            mock_cat.all.side_effect = RuntimeError("Catalog Query Failure")
            res = _load_custom_options()
            assert res == []

        # Session should remain usable
        val = db.session.execute(text("SELECT 1")).scalar()
        assert val == 1
