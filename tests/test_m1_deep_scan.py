"""Deep scan adversarial verification for Milestone M1 across all templates and blueprints.
"""
import os
import re
import unittest
from platform_app import create_app


class M1DeepScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": True,
            "SECRET_KEY": "m1-deep-scan-key",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SERVER_NAME": "localhost",
        })
        cls.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def test_no_references_to_base_admin_html(self):
        """Verify no template in the entire codebase extends nonexistent base_admin.html."""
        templates_dir = os.path.join(self.root_dir, "templates")
        violating_files = []
        for root, _, files in os.walk(templates_dir):
            for file in files:
                if file.endswith((".html", ".jinja", ".j2")):
                    full_path = os.path.join(root, file)
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        if "base_admin.html" in content:
                            violating_files.append(os.path.relpath(full_path, self.root_dir))
        self.assertEqual(violating_files, [], f"Files referencing base_admin.html: {violating_files}")

    def test_no_unresolved_proposal_branch_choices(self):
        """Verify no Python file in modules/ imports or uses the obsolete PROPOSAL_BRANCH_CHOICES name."""
        modules_dir = os.path.join(self.root_dir, "modules")
        violating_files = []
        for root, _, files in os.walk(modules_dir):
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        if "PROPOSAL_BRANCH_CHOICES" in content:
                            violating_files.append(os.path.relpath(full_path, self.root_dir))
        self.assertEqual(violating_files, [], f"Files referencing PROPOSAL_BRANCH_CHOICES: {violating_files}")

    def test_no_broken_kanban_board_in_templates(self):
        """Verify no template calls url_for('kanban.board')."""
        templates_dir = os.path.join(self.root_dir, "templates")
        violating_files = []
        for root, _, files in os.walk(templates_dir):
            for file in files:
                if file.endswith((".html", ".jinja", ".j2")):
                    full_path = os.path.join(root, file)
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        if "kanban.board" in content:
                            violating_files.append(os.path.relpath(full_path, self.root_dir))
        self.assertEqual(violating_files, [], f"Files referencing kanban.board: {violating_files}")

    def test_no_tech_bp_agenda_redirects(self):
        """Verify no route redirects to nonexistent tech_bp agenda routes."""
        modules_dir = os.path.join(self.root_dir, "modules")
        violating_files = []
        for root, _, files in os.walk(modules_dir):
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        if "tech_bp.criar_agendamento" in content or "tech_bp.atualizar_agendamento" in content or "tech_bp.excluir_agendamento" in content:
                            violating_files.append(os.path.relpath(full_path, self.root_dir))
        self.assertEqual(violating_files, [], f"Files referencing tech_bp agenda routes: {violating_files}")

    def test_all_routes_in_full_app_url_map_buildable(self):
        """Verify all endpoints registered in the full application build valid URLs with sample parameters."""
        with self.app.test_request_context("/"):
            from flask import url_for
            endpoints = [rule.endpoint for rule in self.app.url_map.iter_rules()]
            self.assertTrue(len(endpoints) > 100, f"App should have > 100 endpoints, found {len(endpoints)}")
            self.assertIn("central_conhecimento.board", endpoints)
            self.assertIn("assist_bp.listar_orcamento_templates", endpoints)
            self.assertIn("assist_bp.agenda_tecnica", endpoints)
            self.assertIn("assist_bp.criar_agendamento", endpoints)
            self.assertIn("assist_bp.atualizar_agendamento", endpoints)
            self.assertIn("assist_bp.excluir_agendamento", endpoints)
            self.assertIn("admin_tools_bp.criar_agendamento", endpoints)
            self.assertIn("admin_tools_bp.atualizar_agendamento", endpoints)
            self.assertIn("admin_tools_bp.excluir_agendamento", endpoints)
            self.assertIn("sollus_tickets.api_template_preview", endpoints)


if __name__ == "__main__":
    unittest.main()
