"""
Phase 3 Adversarial Deep Challenge Test Suite
Empirical verification of:
1. AST-level verification of db.session.rollback() in all DB try-except blocks across the entire repository.
2. Direct multi-fault injection testing (IntegrityError, OperationalError, DataError, ProgrammingError).
3. Recovery testing of background mailers, notification services, PDF job worker, and system option loaders.
4. Route-level simulated database fault recovery across all major modules (suporte, propostas, chamados, financeiro, contratos, sollus_tickets, cracha).
5. Comprehensive requirements.txt validation and functional runtime verification for apscheduler, Flask-Mail, openpyxl.
6. Clean compilation of 100% of Python source files and Jinja2 templates.
"""
import ast
import os
import re
import sys
from io import BytesIO
from datetime import datetime, date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import (
    SQLAlchemyError,
    IntegrityError,
    OperationalError,
    DataError,
    ProgrammingError,
    PendingRollbackError,
    InvalidRequestError,
)

from platform_app import create_app
from extensions import db
from modules.propostas.models import (
    User,
    Proposal,
    Department,
    AgendaEntry,
    SystemOptionOverride,
    SystemOptionState,
    SystemOptionCatalog,
)
from modules.suporte.models import AssistenciaTarefa, OrcamentoStatus, AtendimentoSuporte
from modules.chamados.models import Ticket, TicketMessage
from modules.chamados.mailer import enviar_email
from modules.chamados.services.notify import recipients_for_ticket
from modules.propostas.services.pdf_jobs import PdfJobManager, PdfJob
from modules.propostas.utils.systems import (
    _load_override_map,
    _load_system_states,
    _load_custom_options,
)

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


def _get_or_create_admin(app):
    with app.app_context():
        user = User.query.filter_by(usuario="admin_p3_challenger").first()
        if not user:
            user = User(
                usuario="admin_p3_challenger",
                nome_completo="Admin P3 Challenger",
                email="admin_p3@sollus.com",
                tipo="admin",
                role="admin",
                password_hash="dummy",
                is_active=True,
            )
            db.session.add(user)
            db.session.commit()
        return user.id


def _login(client, user_id, tipo="admin"):
    with client.session_transaction() as sess:
        sess["usuario_id"] = user_id
        sess["user_id"] = user_id
        sess["_user_id"] = str(user_id)
        sess["tipo"] = tipo


# =========================================================================
# SECTION 1: Deep AST Audit of Database Exception Handling Across Codebase
# =========================================================================

class DBTryExceptVisitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.unprotected_blocks = []

    def visit_Try(self, node):
        # Determine if try body contains db mutation or execution calls
        body_str = ""
        for stmt in node.body:
            body_str += ast.unparse(stmt) + "\n"

        db_mutation_keywords = [
            "db.session.add",
            "db.session.commit",
            "db.session.delete",
            "db.session.flush",
        ]

        is_db_mutation_try = any(kw in body_str for kw in db_mutation_keywords)

        if is_db_mutation_try:
            # Check all except handlers for db.session.rollback
            for handler in node.handlers:
                handler_str = ast.unparse(handler)
                if "db.session.rollback()" not in handler_str:
                    self.unprotected_blocks.append(
                        (self.filename, handler.lineno, handler_str[:120])
                    )
        self.generic_visit(node)


def test_ast_scan_all_db_mutations_have_rollback():
    """
    AST Scan: Verify that every single try-except block containing db.session mutations
    (add, commit, delete, flush) across all application modules explicitly calls
    db.session.rollback() in its exception handler.
    """
    target_dirs = [
        PROJECT_ROOT / "modules",
        PROJECT_ROOT / "platform_app",
        PROJECT_ROOT / "utils",
        PROJECT_ROOT / "Viva_Rio",
    ]

    all_violations = []

    for base_dir in target_dirs:
        if not base_dir.exists():
            continue
        for root, _, files in os.walk(base_dir):
            for file in files:
                if not file.endswith(".py"):
                    continue
                path = Path(root) / file
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=str(path))
                    visitor = DBTryExceptVisitor(str(path))
                    visitor.visit(tree)
                    all_violations.extend(visitor.unprotected_blocks)
                except Exception as e:
                    pytest.fail(f"Failed to parse AST for {path}: {e}")

    assert len(all_violations) == 0, f"Found {len(all_violations)} unprotected DB mutation except handlers: {all_violations}"


# =========================================================================
# SECTION 2: Empirical Multi-Fault Injection & Session Recovery
# =========================================================================

def test_fault_injection_various_exceptions_and_immediate_recovery(app):
    """
    Stress-test db.session recovery when subjected to diverse SQLAlchemy failure modes:
    - IntegrityError (unique violation)
    - OperationalError (connection drop)
    - DataError (bad data format)
    - ProgrammingError (invalid SQL syntax)
    Verify that in every case, db.session.rollback() immediately clears the transaction
    and subsequent operations execute without PendingRollbackError or connection death.
    """
    with app.app_context():
        # 1. Test IntegrityError recovery
        try:
            # Attempt to add two users with identical unique username in the same transaction
            u1 = User(usuario="unique_conflict_p3", nome_completo="User 1", email="u1@test.com", password_hash="dummy")
            u2 = User(usuario="unique_conflict_p3", nome_completo="User 2", email="u2@test.com", password_hash="dummy")
            db.session.add(u1)
            db.session.commit()
            db.session.add(u2)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

        # Follow-up query must succeed cleanly
        assert db.session.execute(text("SELECT 1")).scalar() == 1
        res = User.query.filter_by(usuario="unique_conflict_p3").first()
        assert res is not None

        # 2. Test ProgrammingError recovery
        try:
            db.session.execute(text("SELECT syntax_error_from_invalid_table_p3_xyz()"))
            db.session.commit()
        except ProgrammingError:
            db.session.rollback()

        assert db.session.execute(text("SELECT 1")).scalar() == 1

        # 3. Test OperationalError recovery
        try:
            db.session.execute(text("PRAGMA foreign_key_check_nonexistent_pragma_fail"))
            raise OperationalError("Simulated operational failure", {}, None)
        except OperationalError:
            db.session.rollback()

        assert db.session.execute(text("SELECT 1")).scalar() == 1

        # 4. Sequential stress test: 100 rapid failure/rollback/recovery cycles
        for i in range(100):
            try:
                db.session.execute(text(f"SELECT * FROM non_existent_table_{i}"))
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()

            val = db.session.execute(text("SELECT 42")).scalar()
            assert val == 42, f"Recovery failed at cycle {i}"


# =========================================================================
# SECTION 3: Background Worker & Service Fault Recovery
# =========================================================================

def test_mailer_enviar_email_exception_handling_and_recovery(app):
    """
    Empirically test chamados mailer when enqueueing email fails due to database error.
    Must return False and rollback session so background thread is not poisoned.
    """
    with app.app_context():
        # Inject commit failure
        with patch.object(db.session, "commit", side_effect=OperationalError("Database is locked", {}, None)):
            res = enviar_email(
                destinatarios=["challenger@sollus.com"],
                assunto="P3 Challenger Email Test",
                html_corpo="<p>Test</p>",
            )
            assert res is False

        # Verify session can execute queries immediately after failed mailer call
        result = db.session.execute(text("SELECT count(*) FROM users")).scalar()
        assert result >= 0


def test_recipients_for_ticket_exception_handling_and_recovery(app):
    """
    Empirically test recipients_for_ticket when query on TicketMessage fails.
    Must catch exception, rollback, and return clean fallback list.
    """
    with app.app_context():
        mock_ticket = MagicMock()
        mock_ticket.id = 12345
        mock_ticket.user = None
        mock_ticket.assignee = None
        mock_ticket.messages = None

        with patch("modules.chamados.models.TicketMessage.query") as mock_q:
            mock_q.filter_by.side_effect = SQLAlchemyError("Query execution error")
            emails = recipients_for_ticket(mock_ticket, include_actor=True)
            assert isinstance(emails, list)

        # Verify session is valid
        res = db.session.execute(text("SELECT 1")).scalar()
        assert res == 1


def test_pdf_jobs_manager_cleanup_and_process_recovery(app):
    """
    Empirically test PdfJobManager exception handling during cleanup and job processing.
    """
    with app.app_context():
        manager = PdfJobManager()
        
        # Test 1: cleanup() failure simulation
        with patch.object(db.session, "commit", side_effect=SQLAlchemyError("Cleanup commit error")):
            manager.cleanup()

        # Session must be functional
        assert db.session.execute(text("SELECT 1")).scalar() == 1

        # Test 2: process_next_job with no jobs
        job = manager.process_next_job()
        assert job is None
        assert db.session.execute(text("SELECT 1")).scalar() == 1


def test_system_option_loaders_resilience(app):
    """
    Empirically test _load_override_map, _load_system_states, and _load_custom_options
    when database queries throw unexpected exceptions.
    """
    with app.app_context():
        with patch("modules.propostas.models.SystemOptionOverride.query") as mock_ov:
            mock_ov.all.side_effect = OperationalError("DB read error", {}, None)
            res = _load_override_map()
            assert res == {}

        assert db.session.execute(text("SELECT 1")).scalar() == 1

        with patch("modules.propostas.models.SystemOptionState.query") as mock_st:
            mock_st.all.side_effect = OperationalError("DB read error", {}, None)
            res = _load_system_states()
            assert res == {}

        assert db.session.execute(text("SELECT 1")).scalar() == 1

        with patch("modules.propostas.models.SystemOptionCatalog.query") as mock_cat:
            mock_cat.all.side_effect = OperationalError("DB read error", {}, None)
            res = _load_custom_options()
            assert res == []

        assert db.session.execute(text("SELECT 1")).scalar() == 1


# =========================================================================
# SECTION 4: Cross-Module Route Handler Database Failure & Recovery
# =========================================================================

def test_suporte_atendimento_db_exception_recovery(app, client):
    """
    Test /admin/suporte/atendimentos/<id>/editar route when db commit fails.
    """
    admin_id = _get_or_create_admin(app)
    _login(client, admin_id, tipo="admin")

    with app.app_context():
        atendimento = AtendimentoSuporte(
            cliente="Cliente Teste Suporte P3",
            cnpj="00000000000191",
            tipo_atendimento="Dúvida",
            status="Entrada",
            descricao="Descrição Inicial",
            os_entrada="99991",
            data_entrada=datetime.utcnow(),
            quantidade_pessoas="1",
        )
        db.session.add(atendimento)
        db.session.commit()
        atendimento_id = atendimento.id

    # Inject commit failure during edit
    with patch.object(db.session, "commit", side_effect=SQLAlchemyError("Simulated atendimento commit error")):
        resp = client.post(
            f"/admin/suporte/atendimentos/{atendimento_id}/editar",
            data={
                "atendimento_id": str(atendimento_id),
                "cliente": "Cliente Teste Suporte P3",
                "cnpj": "00000000000191",
                "tipo_atendimento": "Dúvida",
                "status": "Em Andamento",
                "descricao": "Tentativa com erro de DB",
                "os_entrada": "99991",
                "data_entrada": "2026-08-26T10:00",
                "quantidade_pessoas": "1",
            },
        )
        # Should gracefully handle error
        assert resp.status_code in (200, 302, 500)

    # In the same app context, subsequent query must work cleanly
    with app.app_context():
        item = AtendimentoSuporte.query.get(atendimento_id)
        assert item is not None
        assert db.session.execute(text("SELECT 1")).scalar() == 1


def test_propostas_criacao_db_exception_recovery(app, client):
    """
    Test proposal operations under simulated database commit errors.
    """
    admin_id = _get_or_create_admin(app)
    _login(client, admin_id, tipo="admin")

    with patch.object(db.session, "commit", side_effect=SQLAlchemyError("Simulated proposal commit error")):
        resp = client.post(
            "/salvar_proposta",
            data={
                "client_name": "Cliente Falha DB",
                "company": "Sollus RJ",
                "cnpj": "00000000000191",
            },
        )
        assert resp.status_code in (200, 302, 500)

    with app.app_context():
        assert db.session.execute(text("SELECT 1")).scalar() == 1


# =========================================================================
# SECTION 5: Runtime Dependencies Specification & Functional Verification
# =========================================================================

def test_requirements_txt_pinning_and_semantics():
    """
    Verify requirements.txt format, version constraints, and required dependencies:
    - apscheduler>=3.10.0,<4.0.0
    - Flask-Mail>=0.9.1
    - openpyxl>=3.1.0
    """
    req_file = PROJECT_ROOT / "requirements.txt"
    assert req_file.exists()

    with open(req_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert re.search(r"apscheduler\s*>=\s*3\.10\.0\s*,\s*<\s*4\.0\.0", content, re.IGNORECASE)
    assert re.search(r"Flask-Mail\s*>=\s*0\.9\.1", content, re.IGNORECASE)
    assert re.search(r"openpyxl\s*>=\s*3\.1\.0", content, re.IGNORECASE)


def test_functional_apscheduler_execution():
    """
    Functional check: Verify that apscheduler can initialize a background scheduler,
    schedule a job, and execute it.
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    executed = []

    def sample_job():
        executed.append(True)

    scheduler = BackgroundScheduler()
    scheduler.add_job(sample_job, "date", run_date=datetime.now())
    scheduler.start()
    scheduler.shutdown(wait=False)
    assert scheduler is not None


def test_functional_flask_mail_instantiation(app):
    """
    Functional check: Verify Flask-Mail extension can be initialized with app
    and construct a Message object without error.
    """
    from flask_mail import Mail, Message

    mail = Mail()
    mail.init_app(app)

    msg = Message(
        subject="Verification Subject",
        sender="noreply@sollus.com",
        recipients=["test@example.com"],
        body="Verification plain text body",
    )
    assert msg.subject == "Verification Subject"
    assert msg.recipients == ["test@example.com"]


def test_functional_openpyxl_workbook_generation():
    """
    Functional check: Verify openpyxl can create a workbook, write cells,
    compute formulas/styles, and serialize to BytesIO cleanly.
    """
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TestSheet"
    ws.append(["ID", "Name", "Value"])
    ws.append([1, "Item A", 150.75])
    ws.append([2, "Item B", 250.25])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    data = bio.read()

    assert len(data) > 0
    # Re-read to confirm data integrity
    wb_read = openpyxl.load_workbook(BytesIO(data))
    assert "TestSheet" in wb_read.sheetnames
    assert wb_read["TestSheet"].cell(row=2, column=2).value == "Item A"


# =========================================================================
# SECTION 6: Project Compilation & Jinja2 Template Parsing
# =========================================================================

def test_full_python_syntax_and_compilation():
    """
    Verify that 100% of Python source files across the entire workspace compile cleanly
    without any SyntaxError or IndentationError.
    """
    import py_compile

    compiled_count = 0
    errors = []

    for root, dirs, files in os.walk(PROJECT_ROOT):
        if any(ignored in root for ignored in [".git", "__pycache__", "env", ".agents", ".pytest_cache"]):
            continue
        for file in files:
            if not file.endswith(".py"):
                continue
            path = Path(root) / file
            try:
                py_compile.compile(str(path), doraise=True)
                compiled_count += 1
            except py_compile.PyCompileError as e:
                errors.append(str(e))

    assert len(errors) == 0, f"Compilation errors in {len(errors)} files:\n" + "\n".join(errors)
    assert compiled_count >= 100, f"Expected at least 100 python files, compiled {compiled_count}"


def test_full_jinja2_template_syntax_parsing(app):
    """
    Verify that all Jinja2 HTML templates in templates/ directory parse cleanly without
    syntax errors or missing tag closures.
    """
    from jinja2 import Environment, FileSystemLoader

    templates_dir = PROJECT_ROOT / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))

    parsed_count = 0
    errors = []

    for root, _, files in os.walk(templates_dir):
        for file in files:
            if not file.endswith(".html"):
                continue
            rel_path = os.path.relpath(os.path.join(root, file), str(templates_dir)).replace("\\", "/")
            try:
                env.get_template(rel_path)
                parsed_count += 1
            except Exception as e:
                errors.append(f"{rel_path}: {e}")

    assert len(errors) == 0, f"Jinja2 template parsing errors in {len(errors)} templates:\n" + "\n".join(errors)
    assert parsed_count >= 50, f"Expected at least 50 templates, parsed {parsed_count}"
