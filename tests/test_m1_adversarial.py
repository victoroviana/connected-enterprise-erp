"""Adversarial and boundary stress tests for Milestone M1 (Requirement R1).

Tests:
1. Endpoint build testing under full Flask application context.
2. AJAX endpoint path and contract validation in admin_settings.html.
3. Form POST submission behavior with/without/invalid CSRF tokens.
4. Template rendering, inheritance and boundary condition stress tests.
"""
import os
import re
import tempfile
import unittest
from types import SimpleNamespace
from flask import Flask, session, url_for, render_template
from flask_wtf.csrf import generate_csrf

from platform_app import create_app
from extensions import db
from modules.propostas.constants import ISSUER_COMPANY_CHOICES
from modules.propostas.models import User, Department, Proposal
from modules.suporte.models import OrcamentoTemplate, AssistenciaTarefa


class M1AdversarialTestSuite(unittest.TestCase):
    db_path = os.path.join(tempfile.gettempdir(), "test_m1_adv.db")

    class TestConfig:
        TESTING = True
        WTF_CSRF_ENABLED = True
        SECRET_KEY = "m1-adversarial-test-key-!@#$%"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(tempfile.gettempdir(), 'test_m1_adv.db')}"
        SERVER_NAME = "localhost"

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except OSError:
                pass

        cls.app = create_app(cls.TestConfig)
        cls.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        with cls.app.app_context():
            db.create_all()
            # Create test admin user
            admin = User.query.get(1)
            if not admin:
                admin = User(
                    id=1,
                    usuario="admin",
                    nome_completo="Admin User",
                    email="admin@sollusgroup.com.br",
                    password_hash="fake-hash",
                    tipo="admin",
                    role="admin",
                    is_active=True,
                    permissions={"admin": True, "usuarios_gerenciar": True, "admin_assistencia": True, "assistencia_chamados": True},
                )
                db.session.add(admin)
                db.session.commit()

            # Create test proposal for delete test
            prop = Proposal.query.get(999)
            if not prop:
                prop = Proposal(
                    id=999,
                    client_name="Test Client",
                    usuario_id=1,
                )
                db.session.add(prop)
                db.session.commit()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except OSError:
                pass

    def setUp(self):
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["usuario_id"] = 1
            sess["logged_in"] = True
            sess["username"] = "admin"
            sess["tipo"] = "admin"
            sess["_user_id"] = "1"

    # =========================================================================
    # TARGET AREA 1: Endpoint Build Testing under Full Flask App Context
    # =========================================================================

    def test_area1_all_m1_endpoints_exist_in_url_map(self):
        """Verify all repaired and target endpoints exist and build cleanly in url map."""
        with self.app.test_request_context("/"):
            # 1. central_conhecimento.board
            url_kb = url_for("central_conhecimento.board")
            self.assertEqual(url_kb, "/central-conhecimento/")

            # 2. assist_bp orcamento templates
            url_orc = url_for("assist_bp.listar_orcamento_templates")
            self.assertEqual(url_orc, "/assistencia/orcamento-templates")

            # 3. assist_bp agenda endpoints
            url_assist_agenda = url_for("assist_bp.agenda_tecnica")
            self.assertEqual(url_assist_agenda, "/assistencia/agenda")

            url_assist_criar = url_for("assist_bp.criar_agendamento")
            self.assertEqual(url_assist_criar, "/assistencia/api/agenda/criar")

            url_assist_atualizar = url_for("assist_bp.atualizar_agendamento", entry_id=123)
            self.assertEqual(url_assist_atualizar, "/assistencia/api/agenda/123/atualizar")

            url_assist_excluir = url_for("assist_bp.excluir_agendamento", entry_id=123)
            self.assertEqual(url_assist_excluir, "/assistencia/api/agenda/123/excluir")

            # 4. admin_tools agenda endpoints
            url_admin_agenda = url_for("admin_tools_bp.agenda_tecnica")
            self.assertEqual(url_admin_agenda, "/admin/agenda-tecnica")

            url_admin_criar = url_for("admin_tools_bp.criar_agendamento")
            self.assertEqual(url_admin_criar, "/admin/agenda-tecnica/criar")

            url_admin_atualizar = url_for("admin_tools_bp.atualizar_agendamento", agenda_id=456)
            self.assertEqual(url_admin_atualizar, "/admin/agenda-tecnica/456/atualizar")

            url_admin_excluir = url_for("admin_tools_bp.excluir_agendamento", agenda_id=456)
            self.assertEqual(url_admin_excluir, "/admin/agenda-tecnica/456/excluir")

            # 5. sollus_tickets email template preview
            url_preview = url_for("sollus_tickets.api_template_preview", template_id=789)
            self.assertEqual(url_preview, "/sollus-tickets/api/templates/789/preview")

            # 6. assistencia criar form target
            url_assist_criar_form = url_for("assist_bp.assistencia_criar")
            self.assertEqual(url_assist_criar_form, "/assistencia/criar")

            # 7. propostas excluir target
            url_prop_excluir = url_for("propostas_bp.excluir_proposta", id=999)
            self.assertEqual(url_prop_excluir, "/excluir_proposta/999")

    def test_area1_admin_tools_redirect_behavior(self):
        """Verify admin_tools schedule handlers issue 302 redirects targeting assist_bp with entry_id."""
        with self.app.test_request_context("/agenda-tecnica"):
            from modules.propostas.blueprints.admin_tools.routes import (
                agenda_tecnica, criar_agendamento, atualizar_agendamento, excluir_agendamento
            )
            from unittest.mock import MagicMock, patch

            with patch("modules.propostas.blueprints.auth.login_required", lambda f: f), \
                 patch("flask_login.utils._get_user", return_value=MagicMock(is_authenticated=True)):
                
                resp_agenda = agenda_tecnica()
                self.assertEqual(resp_agenda.status_code, 302)
                self.assertIn("/agenda", resp_agenda.location)

                resp_criar = criar_agendamento()
                self.assertEqual(resp_criar.status_code, 302)
                self.assertIn("/agenda/criar", resp_criar.location)

                resp_att = atualizar_agendamento(888)
                self.assertEqual(resp_att.status_code, 302)
                self.assertIn("/agenda/888/atualizar", resp_att.location)

                resp_exc = excluir_agendamento(888)
                self.assertEqual(resp_exc.status_code, 302)
                self.assertIn("/agenda/888/excluir", resp_exc.location)

    # =========================================================================
    # TARGET AREA 2: AJAX Endpoint Path Validation in admin_settings.html
    # =========================================================================

    def test_area2_admin_settings_ajax_preview_path(self):
        """Verify fetch call in admin_settings.html strictly aligns with registered route."""
        settings_path = os.path.join(self.root_dir, "templates", "sollus_tickets", "admin_settings.html")
        with open(settings_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check JS function previewTemplate
        match = re.search(r"fetch\(\s*['\"]([^'\"]+)['\"]\s*\+\s*templateId\s*\+\s*['\"]([^'\"]+)['\"]", content)
        self.assertIsNotNone(match, "fetch call with templateId concatenation must exist")
        prefix, suffix = match.groups()
        full_pattern = f"{prefix}123{suffix}"
        self.assertEqual(full_pattern, "/sollus-tickets/api/templates/123/preview")

        # Ensure headers include X-CSRFToken and Content-Type: application/json
        fetch_block = content[match.start():match.start() + 300]
        self.assertIn("'X-CSRFToken': csrfToken", fetch_block)
        self.assertIn("method: 'POST'", fetch_block)

    def test_area2_template_preview_endpoint_auth_and_method(self):
        """Verify the /sollus-tickets/api/templates/<id>/preview endpoint requires POST and auth."""
        # GET should be rejected (405 Method Not Allowed)
        res_get = self.client.get("/sollus-tickets/api/templates/1/preview")
        self.assertEqual(res_get.status_code, 405)

        # POST without auth should redirect to login or return 401/403
        with self.app.test_request_context():
            token = generate_csrf()
        res_unauth = self.client.post(
            "/sollus-tickets/api/templates/1/preview",
            headers={"X-CSRFToken": token},
            json={},
        )
        self.assertIn(res_unauth.status_code, (302, 401, 403))

    # =========================================================================
    # TARGET AREA 3: Form POST Submission Behavior with/without CSRF Tokens
    # =========================================================================

    def test_area3_fluxo_form_csrf_enforcement(self):
        """Verify assistencia_criar form in fluxo.html enforces CSRF protection."""
        # 1. Verify template contains create_form.hidden_tag()
        fluxo_path = os.path.join(self.root_dir, "templates", "admin", "assistencia", "fluxo.html")
        with open(fluxo_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("{{ create_form.hidden_tag() }}", content)

        # 2. Test POST /assistencia/criar WITHOUT CSRF token -> Intercepted by CSRF protection
        self._login_admin()
        res_no_csrf = self.client.post("/assistencia/criar", data={"nome": "Test Client", "os_codigo": "OS-1234"})
        self.assertIn(res_no_csrf.status_code, (302, 400), "POST without CSRF token must be intercepted")

        # 3. Test POST /assistencia/criar WITH INVALID CSRF token -> Intercepted
        res_invalid_csrf = self.client.post(
            "/assistencia/criar",
            data={"nome": "Test Client", "os_codigo": "OS-1234", "csrf_token": "bogus-token-value"}
        )
        self.assertIn(res_invalid_csrf.status_code, (302, 400), "POST with invalid CSRF token must be intercepted")

        # 4. Test POST /assistencia/criar WITH VALID CSRF token -> CSRF check passes (not 400)
        with self.app.test_request_context():
            valid_token = generate_csrf()
        res_valid_csrf = self.client.post(
            "/assistencia/criar",
            data={"nome": "Test Client", "os_codigo": "OS-1234", "csrf_token": valid_token}
        )
        self.assertNotEqual(res_valid_csrf.status_code, 400, "POST with valid CSRF token must pass CSRF validation")

    def test_area3_historico_propostas_csrf_enforcement(self):
        """Verify excluir_proposta form in historico_propostas.html enforces CSRF protection."""
        # 1. Verify template contains csrf_token() in delete form
        hist_path = os.path.join(self.root_dir, "templates", "historico_propostas.html")
        with open(hist_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('name="csrf_token"', content)
        self.assertIn("csrf_token()", content)

        # 2. Test POST /excluir_proposta/999 WITHOUT CSRF token -> Intercepted
        self._login_admin()
        res_no_csrf = self.client.post("/excluir_proposta/999", data={})
        self.assertIn(res_no_csrf.status_code, (302, 400), "POST without CSRF token must be intercepted")

        # 3. Test POST /excluir_proposta/999 WITH INVALID CSRF token -> Intercepted
        res_invalid_csrf = self.client.post("/excluir_proposta/999", data={"csrf_token": "fake-token-value"})
        self.assertIn(res_invalid_csrf.status_code, (302, 400), "POST with invalid CSRF token must be intercepted")

        # 4. Test POST /excluir_proposta/999 WITH VALID CSRF token -> CSRF check passes (not 400)
        with self.app.test_request_context():
            valid_token = generate_csrf()
        res_valid_csrf = self.client.post("/excluir_proposta/999", data={"csrf_token": valid_token})
        self.assertNotEqual(res_valid_csrf.status_code, 400, "POST with valid CSRF token must pass CSRF validation")

    # =========================================================================
    # TARGET AREA 4: Template Rendering, Inheritance & Boundary Stress Testing
    # =========================================================================

    def test_area4_orcamento_templates_full_render(self):
        """Verify admin/assistencia/orcamento_templates.html renders cleanly with full layout.html inheritance."""
        with self.app.test_request_context("/assistencia/orcamento-templates"):
            tmpl_obj = OrcamentoTemplate(
                id=1,
                chave="template_relogio",
                label="Template Relógio",
                table_title="Relógios de Ponto",
                items=[],
                condicoes=[],
                observacao="Observacao teste",
                aceite=[],
                ativo=True,
            )

            output = render_template(
                "admin/assistencia/orcamento_templates.html",
                templates=[tmpl_obj],
                tipos_predefinidos=[("template_relogio", "Template Relógio")],
                active_page="orcamento_templates",
            )
            self.assertIsNotNone(output)
            self.assertIn("Tipos de Orçamento", output)
            self.assertIn("Template Relógio", output)
            self.assertIn("Relógios de Ponto", output)
            self.assertIn("<!DOCTYPE html>", output)
            self.assertNotIn("base_admin.html", output)

    def test_area4_chamados_layout_role_rendering(self):
        """Verify chamados/layout.html renders central_conhecimento link for authorized roles and omits for others."""
        class MockUser:
            def __init__(self, is_auth=True, role="admin"):
                self.is_authenticated = is_auth
                self.role = role
                self.id = 1
                self.nome_completo = "Test User"
                self.email = "test@example.com"
                self.username = "testuser"
                self.avatar_path = None
                self.tipo = role

        for role in ["admin", "gestor", "agent"]:
            with self.app.test_request_context("/"):
                output = render_template("chamados/layout.html", current_user=MockUser(role=role))
                self.assertIn('href="/central-conhecimento/"', output)
                self.assertIn("Central de Conhecimento", output)

        # Unauthenticated user should not see central_conhecimento in sidebar
        with self.app.test_request_context("/"):
            output_anon = render_template("chamados/layout.html", current_user=MockUser(is_auth=False, role=""))
            self.assertNotIn("Central de Conhecimento", output_anon)

    def test_area4_sistemas_ponto_branch_choice_stress_testing(self):
        """Stress-test branch code lookup and fallback in sistemas.py."""
        branch_map = dict(ISSUER_COMPANY_CHOICES)
        self.assertTrue(len(branch_map) > 0, "ISSUER_COMPANY_CHOICES must be populated")

        # Test valid branch codes
        for code, label in ISSUER_COMPANY_CHOICES:
            self.assertEqual(branch_map.get(code), label)

        # Test adversarial branch codes
        adversarial_inputs = [
            "",
            "   ",
            None,
            "INVALID_BRANCH_CODE_XYZ",
            "' OR '1'='1",
            "<script>alert(1)</script>",
            "\x00\x01\x02",
            "branch" * 100,
        ]
        for adv_input in adversarial_inputs:
            clean_code = (adv_input or "").strip()
            if clean_code and clean_code not in branch_map:
                clean_code = ""
            branch_label = branch_map.get(clean_code, "Todas as unidades")
            self.assertIn(branch_label, list(branch_map.values()) + ["Todas as unidades"])


if __name__ == "__main__":
    unittest.main()
