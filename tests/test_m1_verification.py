import unittest
import os
import re
from flask import Flask
from jinja2 import Environment, FileSystemLoader

class M1VerificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def test_task1_orcamento_templates_extends_layout(self):
        """Task 1: templates/admin/assistencia/orcamento_templates.html must extend layout.html"""
        template_path = os.path.join(self.root_dir, "templates", "admin", "assistencia", "orcamento_templates.html")
        self.assertTrue(os.path.exists(template_path))
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn('{% extends "admin/base_admin.html" %}', content)
        self.assertIn('{% extends "layout.html" %}', content)

    def test_task2_sistemas_ponto_issuer_company_choices(self):
        """Task 2: modules/propostas/blueprints/sistemas_ponto/sistemas.py uses ISSUER_COMPANY_CHOICES"""
        sistemas_path = os.path.join(self.root_dir, "modules", "propostas", "blueprints", "sistemas_ponto", "sistemas.py")
        with open(sistemas_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("PROPOSAL_BRANCH_CHOICES", content)
        self.assertIn("from ...constants import ISSUER_COMPANY_CHOICES", content)
        self.assertIn("branch_map = dict(ISSUER_COMPANY_CHOICES)", content)
        self.assertIn("branch_choices=ISSUER_COMPANY_CHOICES", content)

        # Also test direct import
        from modules.propostas.blueprints.sistemas_ponto.sistemas import listar_sistemas_ponto
        from modules.propostas.constants import ISSUER_COMPANY_CHOICES
        self.assertTrue(len(ISSUER_COMPANY_CHOICES) > 0)

    def test_task3_chamados_layout_central_conhecimento(self):
        """Task 3: templates/chamados/layout.html uses central_conhecimento.board"""
        layout_path = os.path.join(self.root_dir, "templates", "chamados", "layout.html")
        with open(layout_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("url_for('kanban.board')", content)
        self.assertNotIn("request.endpoint.startswith('kanban.')", content)
        self.assertIn("url_for('central_conhecimento.board')", content)
        self.assertIn("request.endpoint.startswith('central_conhecimento.')", content)

    def test_task4_admin_tools_routes_agenda_redirects(self):
        """Task 4: modules/propostas/blueprints/admin_tools/routes.py redirects to assist_bp with entry_id"""
        routes_path = os.path.join(self.root_dir, "modules", "propostas", "blueprints", "admin_tools", "routes.py")
        with open(routes_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn('url_for("tech_bp.criar_agendamento")', content)
        self.assertNotIn('url_for("tech_bp.atualizar_agendamento"', content)
        self.assertNotIn('url_for("tech_bp.excluir_agendamento"', content)

        self.assertIn('redirect(url_for("assist_bp.criar_agendamento"))', content)
        self.assertIn('redirect(url_for("assist_bp.atualizar_agendamento", entry_id=agenda_id))', content)
        self.assertIn('redirect(url_for("assist_bp.excluir_agendamento", entry_id=agenda_id))', content)

    def test_task5_admin_settings_ajax_preview_url(self):
        """Task 5: templates/sollus_tickets/admin_settings.html uses /sollus-tickets/api/templates/"""
        settings_path = os.path.join(self.root_dir, "templates", "sollus_tickets", "admin_settings.html")
        with open(settings_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("fetch('/tickets/api/templates/'", content)
        self.assertIn("fetch('/sollus-tickets/api/templates/' + templateId + '/preview'", content)

    def test_task6a_fluxo_csrf_token(self):
        """Task 6a: templates/admin/assistencia/fluxo.html contains {{ create_form.hidden_tag() }}"""
        fluxo_path = os.path.join(self.root_dir, "templates", "admin", "assistencia", "fluxo.html")
        with open(fluxo_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Find modalNova form and ensure hidden_tag is inside it
        self.assertIn('{{ create_form.hidden_tag() }}', content)
        match = re.search(r'<form\s+method="post"\s+action="\{\{\s*url_for\(\'assist_bp\.assistencia_criar\'\)\s*\}\}"[^>]*>(.*?)</form>', content, re.DOTALL)
        self.assertIsNotNone(match, "modalNova form should exist")
        self.assertIn("{{ create_form.hidden_tag() }}", match.group(1))

    def test_task6b_historico_propostas_csrf_token(self):
        """Task 6b: templates/historico_propostas.html contains csrf_token in delete form"""
        hist_path = os.path.join(self.root_dir, "templates", "historico_propostas.html")
        with open(hist_path, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r'<form\s+method="post"[^>]*action="\{\{\s*url_for\(\'propostas_bp\.excluir_proposta\',\s*id=proposta\.id\)\s*\}\}"[^>]*>(.*?)</form>', content, re.DOTALL)
        self.assertIsNotNone(match, "Delete proposal form should exist")
        self.assertIn("csrf_token()", match.group(1))

    def test_url_resolution(self):
        """Test url_for resolution for fixed endpoints with Flask test app context."""
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test"
        
        from modules.suporte.blueprints.assistencia import assist_bp
        from modules.propostas.blueprints.admin_tools import admin_tools_bp
        from modules.chamados.blueprints.central_conhecimento import central_conhecimento_bp
        from modules.sollus_tickets.blueprints.tickets import sollus_tickets_bp
        
        app.register_blueprint(assist_bp)
        app.register_blueprint(admin_tools_bp)
        app.register_blueprint(central_conhecimento_bp)
        app.register_blueprint(sollus_tickets_bp)
        
        with app.test_request_context("/"):
            from flask import url_for
            # 1. central_conhecimento.board
            url_kb = url_for("central_conhecimento.board")
            self.assertTrue(url_kb.startswith("/"))

            # 2. assist_bp agenda endpoints
            url_criar = url_for("assist_bp.criar_agendamento")
            self.assertTrue("/agenda/criar" in url_criar or "/api/agenda/criar" in url_criar)

            url_atualizar = url_for("assist_bp.atualizar_agendamento", entry_id=42)
            self.assertTrue("42" in url_atualizar)

            url_excluir = url_for("assist_bp.excluir_agendamento", entry_id=42)
            self.assertTrue("42" in url_excluir)

            # 3. admin_tools agenda endpoints
            url_admin_criar = url_for("admin_tools_bp.criar_agendamento")
            self.assertEqual(url_admin_criar, "/agenda-tecnica/criar")

            url_admin_atualizar = url_for("admin_tools_bp.atualizar_agendamento", agenda_id=42)
            self.assertEqual(url_admin_atualizar, "/agenda-tecnica/42/atualizar")

            url_admin_excluir = url_for("admin_tools_bp.excluir_agendamento", agenda_id=42)
            self.assertEqual(url_admin_excluir, "/agenda-tecnica/42/excluir")

            # 4. sollus_tickets template preview
            url_preview = url_for("sollus_tickets.api_template_preview", template_id=10)
            self.assertEqual(url_preview, "/sollus-tickets/api/templates/10/preview")

    def test_jinja2_template_parsing(self):
        """Verify Jinja2 syntax and inheritance resolution for all affected templates."""
        app = Flask(__name__, template_folder=os.path.join(self.root_dir, "templates"))
        templates_to_test = [
            "admin/assistencia/orcamento_templates.html",
            "chamados/layout.html",
            "admin/assistencia/fluxo.html",
            "historico_propostas.html",
            "sollus_tickets/admin_settings.html",
        ]
        for t in templates_to_test:
            tmpl = app.jinja_env.get_template(t)
            self.assertIsNotNone(tmpl)

if __name__ == "__main__":
    unittest.main()
