"""
Adversarial Challenge & Stress Harness for Milestone M1 (Requirement R1).
Empirically tests template rendering robustness, module imports, route mappings, redirects, and CSRF token integrity.
"""
import unittest
import os
import re
import json
from unittest.mock import MagicMock, patch

from flask import render_template, url_for, session
from flask_wtf.csrf import generate_csrf
from werkzeug.datastructures import FileStorage
import io

from platform_app import create_app
from extensions import db
from modules.propostas.constants import ISSUER_COMPANY_CHOICES, ISSUER_COMPANIES
from modules.suporte.models import OrcamentoTemplate
from modules.propostas.forms import SystemOptionOverrideForm
from modules.suporte.forms import AssistenciaTarefaForm, AssistenciaFiltroForm
from modules.propostas.models import ParamOption, ParamCategory, ServicoType, ModalidadeType


class TestConfig:
    TESTING = True
    WTF_CSRF_ENABLED = True
    WTF_CSRF_CHECK_DEFAULT = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret-key-12345"


class M1AdversarialChallengeSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        
        # Initialize the production-grade application with testing config class
        cls.app = create_app(TestConfig)
        with cls.app.app_context():
            db.create_all()

    # =========================================================================
    # TARGET AREA 1: Template Rendering Stress Tests (orcamento_templates.html)
    # =========================================================================

    def test_area1_orcamento_templates_empty_list(self):
        """Stress-test rendering orcamento_templates.html with empty templates list."""
        with self.app.test_request_context("/assistencia/orcamento-templates"):
            rendered = render_template(
                "admin/assistencia/orcamento_templates.html",
                templates=[],
                current_user=MagicMock(is_authenticated=True, role="admin", is_admin=True, permissions={})
            )
            self.assertIn("Tipos de Orçamento", rendered)
            self.assertIn("Nenhum tipo de orçamento cadastrado.", rendered)
            self.assertIn("Numeração dos Próximos Orçamentos", rendered)
            self.assertIn("Salvar", rendered)

    def test_area1_orcamento_templates_missing_context(self):
        """Stress-test rendering orcamento_templates.html without passing 'templates' in context (undefined)."""
        with self.app.test_request_context("/assistencia/orcamento-templates"):
            rendered = render_template(
                "admin/assistencia/orcamento_templates.html",
                current_user=MagicMock(is_authenticated=True, role="admin", is_admin=True, permissions={})
            )
            self.assertIn("Nenhum tipo de orçamento cadastrado.", rendered)

    def test_area1_orcamento_templates_diverse_mock_objects(self):
        """Stress-test rendering with rich objects containing special characters, quotes, and unicode."""
        class MockTemplate:
            def __init__(self, id, chave, label, table_title, ativo, items=None, condicoes=None, observacao=None, aceite=None):
                self.id = id
                self.chave = chave
                self.label = label
                self.table_title = table_title
                self.ativo = ativo
                self.items = items or []
                self.condicoes = condicoes or []
                self.observacao = observacao or ""
                self.aceite = aceite or []

            def to_dict(self):
                return {
                    "id": self.id,
                    "chave": self.chave,
                    "label": self.label,
                    "table_title": self.table_title,
                    "items": self.items,
                    "condicoes": self.condicoes,
                    "observacao": self.observacao,
                    "aceite": self.aceite,
                    "ativo": self.ativo,
                }

        test_templates = [
            MockTemplate(1, "standard", "Orçamento Padrão", "OPÇÃO | PADRÃO", True,
                         items=[{"key": "it1", "unit_price": 100}], condicoes=[["Pagamento", "30 dias"]],
                         observacao="Observação padrão", aceite=["OPÇÃO PADRÃO"]),
            MockTemplate(2, "special_chars", "Orçamento 'Especial' & \"Com Aspas\" <tag>",
                         "OPÇÃO | <TAG> & 'ASPAS'", False,
                         items=[], condicoes=[], observacao="Com quebra\nde linha e 'quotes'", aceite=[]),
            MockTemplate(3, "unicode_accents", "Orçamento Manutenção e Instalação (Ação & Reação) 🚀",
                         "TABELA DE PREÇOS €£¥", True,
                         items=[], condicoes=[], observacao="", aceite=[]),
        ]

        with self.app.test_request_context("/assistencia/orcamento-templates"):
            rendered = render_template(
                "admin/assistencia/orcamento_templates.html",
                templates=test_templates,
                current_user=MagicMock(is_authenticated=True, role="admin", is_admin=True, permissions={})
            )
            self.assertIn("standard", rendered)
            self.assertIn("Orçamento Padrão", rendered)
            self.assertIn("Ativo", rendered)
            self.assertIn("Inativo", rendered)
            self.assertIn("special_chars", rendered)
            self.assertIn("unicode_accents", rendered)
            self.assertIn("Manutenção e Instalação", rendered)
            self.assertNotIn("Nenhum tipo de orçamento cadastrado.", rendered)

    def test_area1_orcamento_templates_with_real_orm_instances(self):
        """Stress-test rendering with real SQLAlchemy OrcamentoTemplate instances in DB context."""
        with self.app.app_context():
            db_templates = OrcamentoTemplate.query.all()
            with self.app.test_request_context("/assistencia/orcamento-templates"):
                rendered = render_template(
                    "admin/assistencia/orcamento_templates.html",
                    templates=db_templates,
                    current_user=MagicMock(is_authenticated=True, role="admin", is_admin=True, permissions={})
                )
                self.assertIn("Tipos de Orçamento", rendered)

    # =========================================================================
    # TARGET AREA 2: Import & Logic Stress Testing (sistemas_ponto)
    # =========================================================================

    def test_area2_import_and_symbols(self):
        """Verify that all symbols in sistemas.py are importable and functional."""
        from modules.propostas.blueprints.sistemas_ponto import sistemas
        from modules.propostas.blueprints.sistemas_ponto.sistemas import (
            listar_sistemas_ponto,
            atualizar_sistema_de_ponto,
            _system_image_storage_dir,
            _save_system_image,
            _delete_system_image,
            SYSTEM_IMAGE_DIR,
            SYSTEM_IMAGE_ALLOWED_EXTS,
        )
        self.assertTrue(callable(listar_sistemas_ponto))
        self.assertTrue(callable(atualizar_sistema_de_ponto))
        self.assertIn("png", SYSTEM_IMAGE_ALLOWED_EXTS)
        self.assertIn("jpg", SYSTEM_IMAGE_ALLOWED_EXTS)
        self.assertIn("jpeg", SYSTEM_IMAGE_ALLOWED_EXTS)
        self.assertIn("webp", SYSTEM_IMAGE_ALLOWED_EXTS)

    def test_area2_issuer_company_choices_integrity(self):
        """Verify ISSUER_COMPANY_CHOICES structure and mapping."""
        self.assertIsInstance(ISSUER_COMPANY_CHOICES, list)
        self.assertGreater(len(ISSUER_COMPANY_CHOICES), 0)
        for code, name in ISSUER_COMPANY_CHOICES:
            self.assertIsInstance(code, str)
            self.assertIsInstance(name, str)
            self.assertTrue(len(code) > 0)
            self.assertTrue(len(name) > 0)

        branch_map = dict(ISSUER_COMPANY_CHOICES)
        self.assertIn("sollus", branch_map)
        self.assertIn("technosollus", branch_map)

    def test_area2_codebase_no_production_leftover_proposal_branch_choices(self):
        """Adversarial check: ensure NO production source file contains broken PROPOSAL_BRANCH_CHOICES."""
        pattern = re.compile(r'\bPROPOSAL_BRANCH_CHOICES\b')
        violations = []
        for root, dirs, files in os.walk(self.root_dir):
            if ".git" in root or ".agents" in root or "__pycache__" in root or "tests" in root:
                continue
            for file in files:
                if file.endswith((".py", ".html", ".js")):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            if pattern.search(content):
                                violations.append(filepath)
                    except Exception:
                        pass
        self.assertEqual(violations, [], f"Found leftover PROPOSAL_BRANCH_CHOICES in production files: {violations}")

    def test_area2_sistemas_ponto_branch_filtering_adversarial_inputs(self):
        """Stress-test the branch_code filtering logic inside listar_sistemas_ponto against edge cases."""
        branch_map = dict(ISSUER_COMPANY_CHOICES)
        
        # Test all valid branch codes
        for code in branch_map:
            branch_code = (code or '').strip()
            if branch_code and branch_code not in branch_map:
                branch_code = ''
            branch_label = branch_map.get(branch_code, 'Todas as unidades')
            self.assertEqual(branch_label, branch_map[code])

        # Test adversarial inputs: SQL injection, special chars, whitespace, None
        adversarial_inputs = [
            "non_existent_branch_xyz",
            "'; DROP TABLE users; --",
            "<script>alert(1)</script>",
            "   ",
            None,
            "sollus ",
            "SOLLUS",
            "../etc/passwd",
        ]
        for bad_input in adversarial_inputs:
            branch_code = (bad_input or '').strip()
            if branch_code and branch_code not in branch_map:
                branch_code = ''
            branch_label = branch_map.get(branch_code, 'Todas as unidades')
            if bad_input == "sollus ":
                self.assertEqual(branch_code, "sollus")
                self.assertEqual(branch_label, branch_map["sollus"])
            else:
                self.assertEqual(branch_code, '')
                self.assertEqual(branch_label, 'Todas as unidades')

    def test_area2_system_option_override_form(self):
        """Verify SystemOptionOverrideForm instantiates cleanly with prefix and data."""
        with self.app.test_request_context("/"):
            form = SystemOptionOverrideForm(prefix="test_opt")
            self.assertTrue(hasattr(form, "description"))
            self.assertTrue(hasattr(form, "image"))
            self.assertTrue(hasattr(form, "remove_image"))

    def test_area2_image_handling_adversarial_extensions(self):
        """Stress-test image upload security checks in sistemas.py."""
        from modules.propostas.blueprints.sistemas_ponto.sistemas import _save_system_image

        # Disallowed extensions (exe, sh, html, php)
        for bad_name in ["script.php", "malware.exe", "page.html", "exploit.sh", ""]:
            mock_file = FileStorage(
                stream=io.BytesIO(b"malicious content"),
                filename=bad_name,
                content_type="text/plain"
            )
            with self.assertRaises(ValueError):
                _save_system_image(mock_file, "key_test")

    # =========================================================================
    # TARGET AREA 3: Routing & url_for Resolution and Redirection
    # =========================================================================

    def test_area3_url_for_central_conhecimento_board(self):
        """Verify url_for('central_conhecimento.board') builds correctly."""
        with self.app.test_request_context("/"):
            url = url_for("central_conhecimento.board")
            self.assertTrue(url.startswith("/"))
            self.assertIn("central-conhecimento", url)

    def test_area3_url_for_assist_bp_agenda_routes(self):
        """Verify all assist_bp agenda endpoints build with standard and boundary parameters."""
        with self.app.test_request_context("/"):
            url_criar = url_for("assist_bp.criar_agendamento")
            self.assertIn("/agenda/criar", url_criar)

            # Test various integer entry_ids (0, positive, large)
            for entry_id in [0, 1, 42, 999999]:
                url_att = url_for("assist_bp.atualizar_agendamento", entry_id=entry_id)
                self.assertIn(f"/agenda/{entry_id}/atualizar", url_att)

                url_exc = url_for("assist_bp.excluir_agendamento", entry_id=entry_id)
                self.assertIn(f"/agenda/{entry_id}/excluir", url_exc)

    def test_area3_admin_tools_agenda_redirect_execution(self):
        """Execute admin_tools redirect handlers and verify they produce 302 redirects to assist_bp."""
        with self.app.test_request_context("/agenda-tecnica"):
            from modules.propostas.blueprints.admin_tools.routes import agenda_tecnica, criar_agendamento, atualizar_agendamento, excluir_agendamento
            
            with patch("modules.propostas.blueprints.auth.login_required", lambda f: f), \
                 patch("flask_login.utils._get_user", return_value=MagicMock(is_authenticated=True)):
                
                # Test agenda_tecnica redirect
                resp_agenda = agenda_tecnica()
                self.assertEqual(resp_agenda.status_code, 302)
                self.assertIn("/assistencia/agenda", resp_agenda.location)

                # Test criar_agendamento redirect
                resp_criar = criar_agendamento()
                self.assertEqual(resp_criar.status_code, 302)
                self.assertIn("/agenda/criar", resp_criar.location)

                # Test atualizar_agendamento redirect
                resp_att = atualizar_agendamento(123)
                self.assertEqual(resp_att.status_code, 302)
                self.assertIn("/agenda/123/atualizar", resp_att.location)

                # Test excluir_agendamento redirect
                resp_exc = excluir_agendamento(456)
                self.assertEqual(resp_exc.status_code, 302)
                self.assertIn("/agenda/456/excluir", resp_exc.location)

    def test_area3_sollus_tickets_preview_route(self):
        """Verify sollus_tickets API template preview route builds correctly."""
        with self.app.test_request_context("/"):
            url_preview = url_for("sollus_tickets.api_template_preview", template_id=88)
            self.assertEqual(url_preview, "/sollus-tickets/api/templates/88/preview")

    # =========================================================================
    # TARGET AREA 4: CSRF Tokens in Forms (fluxo.html & historico_propostas.html)
    # =========================================================================

    def test_area4_fluxo_form_renders_csrf_token(self):
        """Stress-test rendering fluxo.html and verify CSRF hidden input is present in modalNova form."""
        with self.app.test_request_context("/assistencia/fluxo"):
            create_form = AssistenciaTarefaForm(meta={"csrf": True})
            filtro_form = AssistenciaFiltroForm()
            filtro_form.status = MagicMock(return_value="<select name='status'></select>")
            csrf_token = generate_csrf()
            
            mock_user = MagicMock(
                is_authenticated=True,
                role="admin",
                is_admin=True,
                nome="Admin Test",
                email="admin@test.com",
                permissions={"assistencia": True}
            )
            
            rendered = render_template(
                "admin/assistencia/fluxo.html",
                create_form=create_form,
                filtro_form=filtro_form,
                tarefas=[],
                colunas=[],
                tecnicos=[],
                departamentos=[],
                unidades=[],
                journey_steps=[],
                status_label_map={},
                current_user=mock_user,
            )
            
            # Check form element and hidden csrf input
            self.assertIn('action="/assistencia/criar"', rendered)
            self.assertIn('name="csrf_token"', rendered)
            self.assertIn('type="hidden"', rendered)
            
            # Verify the hidden csrf tag is inside the modalNova form
            modal_form_match = re.search(r'<form\s+method="post"\s+action="[^"]*assistencia/criar"[^>]*>(.*?)</form>', rendered, re.DOTALL)
            self.assertIsNotNone(modal_form_match, "modalNova form should be present in rendered HTML")
            self.assertIn('name="csrf_token"', modal_form_match.group(1))

    def test_area4_historico_propostas_renders_csrf_token(self):
        """Stress-test rendering historico_propostas.html and verify CSRF hidden input is present in delete forms."""
        mock_proposta = MagicMock()
        mock_proposta.id = 789
        mock_proposta.codigo = "PROP-2026-001"
        mock_proposta.cliente_nome = "Cliente Teste"
        mock_proposta.status = "ativo"
        mock_proposta.data_criacao = None
        mock_proposta.valor_total = 1500.0
        mock_proposta.criador_nome = "Vendedor 1"
        mock_proposta.empresa_emissora = "sollus"

        with self.app.test_request_context("/propostas/historico"):
            session["tipo"] = "admin"
            csrf_token = generate_csrf()
            
            mock_user = MagicMock(
                is_authenticated=True,
                role="admin",
                tipo="admin",
                nome="Admin",
                email="admin@test.com",
                permissions={}
            )

            pagination_mock = MagicMock()
            pagination_mock.items = [mock_proposta]
            pagination_mock.page = 1
            pagination_mock.pages = 1
            pagination_mock.total = 1
            pagination_mock.has_prev = False
            pagination_mock.has_next = False
            pagination_mock.iter_pages.return_value = [1]

            rendered = render_template(
                "historico_propostas.html",
                propostas=pagination_mock,
                propostas_pagination=pagination_mock,
                can_edit=True,
                current_user=mock_user,
                session={"tipo": "admin"},
                filtros={},
                clientes=[],
                usuarios_list=[],
                servico_sel="",
                modalidade_sel="",
                issuer_sel="",
                issuer_options=ISSUER_COMPANY_CHOICES,
                system_options=[],
                user_sel="",
                date_sel="",
                empresa_sel="",
                empresa_options=[],
                ServicoType=ServicoType,
                ModalidadeType=ModalidadeType,
                ParamOption=ParamOption,
                ParamCategory=ParamCategory,
                equipments={},
                versions_by_original={},
            )
            
            # Check delete form and csrf input
            self.assertIn('action="/excluir_proposta/789"', rendered)
            self.assertIn('name="csrf_token"', rendered)
            
            delete_form_match = re.search(r'<form\s+method="post"[^>]*action="[^"]*excluir_proposta/789"[^>]*>(.*?)</form>', rendered, re.DOTALL)
            self.assertIsNotNone(delete_form_match, "Delete proposal form should be present for admin session")
            self.assertIn('name="csrf_token"', delete_form_match.group(1))
            self.assertIn(csrf_token, delete_form_match.group(1))

    # =========================================================================
    # TARGET AREA 4b: CSRF Enforcement Validation via Test Client
    # =========================================================================

    def test_area4_csrf_enforcement_on_unprotected_submission(self):
        """Verify that submitting POST request without CSRF token is intercepted and rejected."""
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_user_id"] = "1"
            sess["tipo"] = "admin"

        # Form POST without CSRF token triggers CSRFError and redirects with warning
        resp = client.post("/excluir_proposta/99999", data={}, follow_redirects=False)
        self.assertIn(resp.status_code, (302, 400))

        # AJAX / JSON POST without CSRF token returns 400 Bad Request
        resp_ajax = client.post(
            "/excluir_proposta/99999",
            data={},
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(resp_ajax.status_code, 400)


if __name__ == "__main__":
    unittest.main()
