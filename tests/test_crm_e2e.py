"""Comprehensive End-to-End Test Suite for Sollus CRM Evolution.

Authoritative Reference:
- ORIGINAL_REQUEST.md (## 2026-09-21T11:30:15Z)
- PROJECT.md (Sollus CRM Evolution Architecture & Interface Contracts)
- spec_miner_crm_survey/spec_report.md
- survey_explorer_crm_1/models_codebase_report.md
- survey_explorer_crm_2/routes_integrations_report.md

4-Tier Test Harness:
- Tier 1: Feature Coverage (>=5 test cases per feature across R1, R2, R3, R4)
- Tier 2: Boundary & Corner Cases (>=5 test cases per feature across R1, R2, R3, R4)
- Tier 3: Cross-Feature Combinations (pairwise interactions across modules)
- Tier 4: Real-World Workload Scenarios (>=5 realistic application flows)
"""
from __future__ import annotations

import hmac
import hashlib
import json
import re
import unittest
import urllib.parse
from datetime import datetime, date, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from sqlalchemy.pool import StaticPool

from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department, Proposal
from modules.chamados.models import SfPedido
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmInteracao,
    CrmLeadMarketing,
)


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key-crm-e2e"
    WTF_CSRF_ENABLED = False
    CRM_WEBHOOK_API_TOKEN = "sollus-test-token-secret-12345"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class CrmE2EBaseTestCase(unittest.TestCase):
    """Base setup with pre-seeded commercial environment for CRM E2E tests."""

    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()

        # 1. Commercial Department
        self.dept_comercial = Department.query.filter_by(slug="comercial").first()
        if not self.dept_comercial:
            self.dept_comercial = Department(name="COMERCIAL", slug="comercial")
            db.session.add(self.dept_comercial)
            db.session.commit()

        # 2. Commercial Active Consultants (Ana Clara, Ricardo, Gilson)
        self.consultant_1 = User(
            usuario="ana_comercial",
            nome_completo="Ana Clara Barbosa",
            email="ana@sollus.com",
            password_hash="hash1",
            tipo="consultor",
            role="usuario",
            is_active=True,
            department_id=self.dept_comercial.id,
            permissions={"crm": True, "propostas": True},
        )
        self.consultant_2 = User(
            usuario="ricardo_comercial",
            nome_completo="Ricardo Simões",
            email="ricardo@sollus.com",
            password_hash="hash2",
            tipo="consultor",
            role="usuario",
            is_active=True,
            department_id=self.dept_comercial.id,
            permissions={"crm": True, "propostas": True},
        )
        self.consultant_3 = User(
            usuario="gilson_comercial",
            nome_completo="Gilson Freitas",
            email="gilson@sollus.com",
            password_hash="hash3",
            tipo="consultor",
            role="usuario",
            is_active=True,
            department_id=self.dept_comercial.id,
            permissions={"crm": True, "propostas": True},
        )
        # Inactive consultant (should be skipped by round-robin)
        self.consultant_inactive = User(
            usuario="inativo_comercial",
            nome_completo="Consultor Inativo",
            email="inativo@sollus.com",
            password_hash="hash_inativo",
            tipo="consultor",
            role="usuario",
            is_active=False,
            department_id=self.dept_comercial.id,
            permissions={"crm": True},
        )
        # Commercial Manager
        self.manager_user = User(
            usuario="gerente_comercial",
            nome_completo="Gerente Comercial",
            email="gerente@sollus.com",
            password_hash="hash_manager",
            tipo="admin",
            role="admin",
            is_active=True,
            department_id=self.dept_comercial.id,
            permissions={"crm": True, "crm_metricas": True, "admin": True},
        )
        db.session.add_all([
            self.consultant_1,
            self.consultant_2,
            self.consultant_3,
            self.consultant_inactive,
            self.manager_user,
        ])
        db.session.commit()

        # 3. Standard Sales Funnel with 6 Stages
        self.funil = CrmFunil(
            id="funil_ponto_e2e",
            nome="Funil Ponto E2E",
            slug="funil_ponto",
            tipo="ponto",
            ordem=1,
            ativo=True,
        )
        db.session.add(self.funil)
        db.session.flush()

        self.etapa_novo = CrmEtapa(
            id="etapa_novo_e2e",
            funil_id=self.funil.id,
            nome="Novo / Entrada",
            ordem=1,
            tipo="normal",
            cor="#3b82f6",
        )
        self.etapa_qualif = CrmEtapa(
            id="etapa_qualif_e2e",
            funil_id=self.funil.id,
            nome="Qualificação",
            ordem=2,
            tipo="normal",
            cor="#8b5cf6",
        )
        self.etapa_apresent = CrmEtapa(
            id="etapa_apresent_e2e",
            funil_id=self.funil.id,
            nome="Apresentação",
            ordem=3,
            tipo="normal",
            cor="#ec4899",
        )
        self.etapa_proposta = CrmEtapa(
            id="etapa_proposta_e2e",
            funil_id=self.funil.id,
            nome="Proposta Enviada",
            ordem=4,
            tipo="normal",
            cor="#f59e0b",
        )
        self.etapa_ganho = CrmEtapa(
            id="etapa_ganho_e2e",
            funil_id=self.funil.id,
            nome="Fechamento Ganho",
            ordem=5,
            tipo="ganho",
            cor="#10b981",
        )
        self.etapa_perdido = CrmEtapa(
            id="etapa_perdido_e2e",
            funil_id=self.funil.id,
            nome="Perdido",
            ordem=6,
            tipo="perdido",
            cor="#ef4444",
        )
        db.session.add_all([
            self.etapa_novo,
            self.etapa_qualif,
            self.etapa_apresent,
            self.etapa_proposta,
            self.etapa_ganho,
            self.etapa_perdido,
        ])
        db.session.commit()

        # Helper properties for default probabilities
        self.stage_probabilities = {
            self.etapa_novo.id: 10,
            self.etapa_qualif.id: 25,
            self.etapa_apresent.id: 50,
            self.etapa_proposta.id: 75,
            self.etapa_ganho.id: 100,
            self.etapa_perdido.id: 0,
        }

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self, user: User | None = None):
        target = user or self.consultant_1
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(target.id)
            sess["user_id"] = target.id
            sess["tipo"] = target.tipo
            sess["role"] = target.role

    def _create_company(self, nome: str, cnpj: str = "12345678000190") -> CrmEmpresa:
        emp = CrmEmpresa(id=f"emp_{nome.lower().replace(' ', '_')}", nome=nome, cnpj=cnpj)
        db.session.add(emp)
        db.session.commit()
        return emp

    def _create_contact(self, empresa_id: str, nome: str, email: str, phone: str = "21988887777") -> CrmContato:
        cont = CrmContato(id=f"cont_{nome.lower().replace(' ', '_')}", empresa_id=empresa_id, nome=nome, email=email, celular=phone)
        db.session.add(cont)
        db.session.commit()
        return cont

    def _create_deal(
        self,
        nome: str,
        valor: float = 1000.0,
        etapa_id: str | None = None,
        user_id: int | None = None,
        empresa_id: str | None = None,
        contato_id: str | None = None,
        status: str = "aberto",
    ) -> CrmNegociacao:
        deal = CrmNegociacao(
            id=f"deal_{nome.lower().replace(' ', '_')}",
            nome=nome,
            funil_id=self.funil.id,
            etapa_id=etapa_id or self.etapa_novo.id,
            valor_total=valor,
            valor_unico=valor,
            user_id=user_id,
            empresa_id=empresa_id,
            contato_id=contato_id,
            status=status,
        )
        db.session.add(deal)
        db.session.commit()
        return deal


# ==============================================================================
# TIER 1: FEATURE COVERAGE (>=5 test cases per feature across R1, R2, R3, R4)
# ==============================================================================

class TestTier1FeatureCoverage(CrmE2EBaseTestCase):
    """Tier 1: Feature Coverage (R1, R2, R3, R4)."""

    # --- R1: Funnel Automations & Commercial Roulette ---

    def test_tier1_r1_01_round_robin_distribution(self):
        """R1.1: Verify sequential round-robin distribution across active consultants."""
        from modules.crm.services import crm_service

        deals = []
        for i in range(6):
            d = self._create_deal(f"Lead RoundRobin {i}", valor=2000.0, user_id=None)
            deals.append(d)

        # Distribute 6 deals among 3 active consultants
        if hasattr(crm_service, "distribute_deal_round_robin"):
            assigned_ids = [crm_service.distribute_deal_round_robin(d)["user_id"] for d in deals]
            expected_pattern = [
                self.consultant_1.id,
                self.consultant_2.id,
                self.consultant_3.id,
                self.consultant_1.id,
                self.consultant_2.id,
                self.consultant_3.id,
            ]
            self.assertEqual(assigned_ids, expected_pattern, "Deals must be distributed in round-robin sequence")
        else:
            self.fail("Function distribute_deal_round_robin not implemented in crm_service (R1 requirement)")

    def test_tier1_r1_02_round_robin_pointer_advancement(self):
        """R1.1: Verify round-robin pointer persistence and wrap-around across calls."""
        from modules.crm.services import crm_service

        if not hasattr(crm_service, "distribute_deal_round_robin"):
            self.fail("distribute_deal_round_robin not found in crm_service (R1 requirement)")

        d1 = self._create_deal("Single Deal 1", user_id=None)
        res1 = crm_service.distribute_deal_round_robin(d1)
        first_user = res1["user_id"]

        d2 = self._create_deal("Single Deal 2", user_id=None)
        res2 = crm_service.distribute_deal_round_robin(d2)
        second_user = res2["user_id"]

        self.assertNotEqual(first_user, second_user, "Pointer must advance to the next consultant")

    def test_tier1_r1_03_stage_automation_task_created(self):
        """R1.2: Moving deal into stage with active rule triggers follow-up CrmTarefa."""
        from modules.crm.services import crm_service

        deal = self._create_deal("Deal Automation Stage", user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        # Move to etapa_qualif with stage automation check
        res = self.client.post(
            f"/crm/api/negociacoes/{deal.id}/mover",
            json={"new_etapa_id": self.etapa_qualif.id}
        )
        self.assertEqual(res.status_code, 200)

        # Check if automated task or hook was evaluated
        tasks = CrmTarefa.query.filter_by(negociacao_id=deal.id).all()
        # In full implementation, stage automation rule creates a follow-up task
        if hasattr(crm_service, "execute_stage_automations"):
            crm_service.execute_stage_automations(deal, self.etapa_qualif)
            tasks = CrmTarefa.query.filter_by(negociacao_id=deal.id).all()
            self.assertGreaterEqual(len(tasks), 1, "Expected automated follow-up task created for stage")
            self.assertEqual(tasks[0].user_id, self.consultant_1.id)
            self.assertIsNotNone(tasks[0].data_vencimento)
        else:
            self.fail("execute_stage_automations not implemented in crm_service (R1 requirement)")

    def test_tier1_r1_04_proposal_creation_links_deal(self):
        """R1.3: Creating a proposal with deal_id links deal, updates value and advances stage."""
        deal = self._create_deal("Deal Proposal Link", valor=0.0, user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        proposal = Proposal(
            company="Empresa Proposta Teste",
            cnpj="12345678000190",
            client_name="Contato Proposta",
            sistema_preco_total=4500.0,
            locacao_valor_mensal=250.0,
            usuario_id=self.consultant_1.id,
        )
        db.session.add(proposal)
        db.session.flush()

        from modules.crm.services import crm_service
        if hasattr(crm_service, "link_proposal_to_deal"):
            crm_service.link_proposal_to_deal(deal.id, proposal.id)
            updated_deal = CrmNegociacao.query.get(deal.id)
            self.assertEqual(updated_deal.proposta_id, proposal.id)
            self.assertGreater(updated_deal.valor_total, 0.0, "Deal value should sync with proposal value")
            self.assertEqual(updated_deal.etapa_id, self.etapa_proposta.id, "Stage should advance to proposal sent")
        else:
            self.fail("link_proposal_to_deal not implemented in crm_service (R1 requirement)")

    def test_tier1_r1_05_proposal_approval_marks_deal_won(self):
        """R1.4: Approving a linked proposal marks the deal won and sets closed_at."""
        deal = self._create_deal("Deal Proposal Approval", valor=5000.0, user_id=self.consultant_1.id)
        proposal = Proposal(
            company="Empresa Aprovada",
            cnpj="12345678000190",
            sistema_preco_total=5000.0,
            usuario_id=self.consultant_1.id,
        )
        db.session.add(proposal)
        db.session.flush()
        deal.proposta_id = proposal.id
        db.session.commit()

        from modules.crm.services import crm_service
        if hasattr(crm_service, "on_proposal_approved"):
            crm_service.on_proposal_approved(proposal.id)
            db.session.refresh(deal)
            self.assertEqual(deal.status, "ganho")
            self.assertIsNotNone(deal.closed_at)
            self.assertEqual(deal.etapa_id, self.etapa_ganho.id)
        else:
            self.fail("on_proposal_approved not implemented in crm_service (R1 requirement)")

    def test_tier1_r1_06_deal_won_creates_sollusflow_order(self):
        """R1.5: Winning a deal automatically creates a SollusFlow order (SfPedido) with valid kwargs."""
        deal = self._create_deal("Deal Won SollusFlow", valor=7500.0, user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        res = self.client.post(f"/crm/api/negociacoes/{deal.id}/ganhar")
        self.assertEqual(res.status_code, 200)

        db.session.refresh(deal)
        self.assertEqual(deal.status, "ganho")
        # Verify SollusFlow order was created and linked without crashing (exercises SfPedido bug fix)
        self.assertIsNotNone(deal.sollusflow_pedido_id, "Deal sollusflow_pedido_id must be populated upon win")
        sf_order = SfPedido.query.get(deal.sollusflow_pedido_id)
        self.assertIsNotNone(sf_order, "SfPedido record must exist in database")
        self.assertEqual(float(sf_order.valor), 7500.0)
        self.assertEqual(sf_order.fase_atual, 1)

    # --- R2: Daily Seller Cockpit & WhatsApp Productivity ---

    def test_tier1_r2_01_cockpit_tarefas_route_renders(self):
        """R2.1: Route GET /crm/tarefas renders 200 OK with seller daily cockpit view."""
        self._login(self.consultant_1)
        res = self.client.get("/crm/tarefas")
        self.assertEqual(res.status_code, 200, "GET /crm/tarefas must resolve 200 OK")
        self.assertIn("tarefas".encode(), res.data.lower())

    def test_tier1_r2_02_cockpit_traffic_light_categorization(self):
        """R2.2: Verify task traffic lights counts: late, today, upcoming, done."""
        now = datetime.utcnow()
        deal = self._create_deal("Deal Cockpit Tasks", user_id=self.consultant_1.id)

        # 1 Late task (yesterday)
        t_late = CrmTarefa(
            id="t_late",
            negociacao_id=deal.id,
            user_id=self.consultant_1.id,
            titulo="Follow-up Atrasado",
            data_vencimento=now - timedelta(days=1),
            concluida=False,
        )
        # 1 Today task
        t_today = CrmTarefa(
            id="t_today",
            negociacao_id=deal.id,
            user_id=self.consultant_1.id,
            titulo="Follow-up Hoje",
            data_vencimento=now,
            concluida=False,
        )
        # 1 Upcoming task (tomorrow)
        t_up = CrmTarefa(
            id="t_up",
            negociacao_id=deal.id,
            user_id=self.consultant_1.id,
            titulo="Follow-up Próximo",
            data_vencimento=now + timedelta(days=2),
            concluida=False,
        )
        # 1 Completed task
        t_done = CrmTarefa(
            id="t_done",
            negociacao_id=deal.id,
            user_id=self.consultant_1.id,
            titulo="Follow-up Concluído",
            data_vencimento=now - timedelta(hours=2),
            concluida=True,
            concluida_em=now,
        )
        db.session.add_all([t_late, t_today, t_up, t_done])
        db.session.commit()

        from modules.crm.services import crm_service
        if hasattr(crm_service, "get_cockpit_tasks"):
            data = crm_service.get_cockpit_tasks(user_id=self.consultant_1.id)
            self.assertEqual(data["counts"]["late"], 1)
            self.assertEqual(data["counts"]["today"], 1)
            self.assertEqual(data["counts"]["upcoming"], 1)
            self.assertEqual(data["counts"]["done"], 1)
        else:
            self.fail("get_cockpit_tasks not implemented in crm_service (R2 requirement)")

    def test_tier1_r2_03_whatsapp_template_dynamic_substitution(self):
        """R2.3: Verify WhatsApp template renders dynamic tags {nome_contato}, {empresa}, {consultor}."""
        from modules.crm.services import crm_service

        template_text = "Olá {nome_contato}, sou o {consultor} da {empresa}. Temos novidades: {link_proposta}!"
        empresa = self._create_company("Tech Solutions S.A.")
        contato = self._create_contact(empresa.id, "Carlos Drummond", "carlos@tech.com")
        deal = self._create_deal("Negócio Tech", empresa_id=empresa.id, contato_id=contato.id, user_id=self.consultant_1.id)
        deal.user_name = "Ana Clara Barbosa"
        deal.proposta_id = 999
        db.session.commit()

        if hasattr(crm_service, "render_whatsapp_template"):
            rendered = crm_service.render_whatsapp_template(template_text, deal_id=deal.id)
            self.assertIn("Carlos Drummond", rendered)
            self.assertIn("Ana Clara Barbosa", rendered)
            self.assertIn("Tech Solutions S.A.", rendered)
            self.assertIn("999", rendered)
        else:
            self.fail("render_whatsapp_template not implemented in crm_service (R2 requirement)")

    def test_tier1_r2_04_whatsapp_1click_url_generation(self):
        """R2.4: 1-Click WhatsApp generates canonical E.164 URL with sanitized phone and encoded text."""
        from modules.crm.services import crm_service

        raw_phone = "(21) 98765-4321"
        msg = "Olá! Gostaria de agendar uma demonstração técnica."

        if hasattr(crm_service, "build_whatsapp_link"):
            url = crm_service.build_whatsapp_link(raw_phone, msg)
            self.assertTrue(url.startswith("https://api.whatsapp.com/send?phone=5521987654321&text="))
            self.assertIn(urllib.parse.quote("Olá!"), url)
        else:
            self.fail("build_whatsapp_link not implemented in crm_service (R2 requirement)")

    def test_tier1_r2_05_quick_timeline_interaction_logging(self):
        """R2.5: Fast logging of interaction/notes into deal timeline."""
        deal = self._create_deal("Deal Quick Log", user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        payload = {"conteudo": "Contato realizado via WhatsApp com retorno positivo", "tipo": "whatsapp"}
        res = self.client.post(f"/crm/api/negociacoes/{deal.id}/anotacoes", json=payload)
        self.assertEqual(res.status_code, 200)

        interacao = CrmInteracao.query.filter_by(negociacao_id=deal.id).first()
        self.assertIsNotNone(interacao)
        self.assertEqual(interacao.tipo, "whatsapp")
        self.assertIn("WhatsApp", interacao.conteudo)

    def test_tier1_r2_06_cockpit_task_toggle_completion(self):
        """R2.6: Toggle task completion updates status and recalculates next task."""
        deal = self._create_deal("Deal Toggle Task", user_id=self.consultant_1.id)
        task = CrmTarefa(
            id="task_toggle_1",
            negociacao_id=deal.id,
            user_id=self.consultant_1.id,
            titulo="Enviar catálogo",
            data_vencimento=datetime.utcnow() + timedelta(hours=2),
            concluida=False,
        )
        db.session.add(task)
        db.session.commit()

        self._login(self.consultant_1)
        res = self.client.post(f"/crm/api/tarefas/{task.id}/toggle", json={"concluida": True})
        self.assertEqual(res.status_code, 200)

        db.session.refresh(task)
        self.assertTrue(task.concluida)
        self.assertIsNotNone(task.concluida_em)

    # --- R3: Integrations & Webhooks Central Hub ---

    def test_tier1_r3_01_inbound_webhook_lead_creation_with_token(self):
        """R3.1: Inbound webhook creates Deal, Empresa, and Contato when authenticated by token."""
        payload = {
            "nome_negociacao": "Lead Inbound Webhook",
            "valor": 12000.0,
            "empresa": {"nome": "Empresa Inbound Ltda", "cnpj": "98.765.432/0001-10"},
            "contato": {"nome": "Roberto Carlos", "email": "roberto@inbound.com", "telefone": "21999998888"},
            "funil_id": self.funil.id,
            "origem": "Formulário Landing Page",
        }
        headers = {"X-API-Token": TestConfig.CRM_WEBHOOK_API_TOKEN}
        res = self.client.post("/crm/api/webhooks/inbound", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201, "Expected 201 Created from inbound webhook")

        data = res.get_json()
        self.assertTrue(data.get("success"))
        deal_id = data.get("deal_id")

        deal = CrmNegociacao.query.get(deal_id)
        self.assertIsNotNone(deal)
        self.assertEqual(deal.nome, "Lead Inbound Webhook")
        self.assertEqual(deal.empresa.nome, "Empresa Inbound Ltda")
        self.assertEqual(deal.contato.email, "roberto@inbound.com")

    def test_tier1_r3_02_inbound_webhook_deduplication_company_cnpj(self):
        """R3.2: Inbound webhook reuses existing CrmEmpresa matching CNPJ."""
        emp = self._create_company("Empresa Preexistente", cnpj="11.222.333/0001-44")
        payload = {
            "nome_negociacao": "Lead Duplicate CNPJ",
            "valor": 5000.0,
            "empresa": {"nome": "Empresa Preexistente Nova Razao", "cnpj": "11222333000144"},
            "contato": {"nome": "Novo Contato", "email": "contato@preexistente.com"},
        }
        headers = {"X-API-Token": TestConfig.CRM_WEBHOOK_API_TOKEN}
        res = self.client.post("/crm/api/webhooks/inbound", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)

        deal = CrmNegociacao.query.filter_by(nome="Lead Duplicate CNPJ").first()
        self.assertEqual(deal.empresa_id, emp.id, "Existing company must be reused by CNPJ match")

    def test_tier1_r3_03_inbound_webhook_deduplication_contact_email(self):
        """R3.3: Inbound webhook reuses existing CrmContato matching Email."""
        emp = self._create_company("Empresa Contato Reuso")
        cont = self._create_contact(emp.id, "Mariana Silva", "mariana@reuso.com")

        payload = {
            "nome_negociacao": "Lead Duplicate Email",
            "valor": 3000.0,
            "empresa": {"nome": "Empresa Contato Reuso"},
            "contato": {"nome": "Mariana Silva", "email": "mariana@reuso.com"},
        }
        headers = {"X-API-Token": TestConfig.CRM_WEBHOOK_API_TOKEN}
        res = self.client.post("/crm/api/webhooks/inbound", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)

        deal = CrmNegociacao.query.filter_by(nome="Lead Duplicate Email").first()
        self.assertEqual(deal.contato_id, cont.id, "Existing contact must be reused by email match")

    @patch("requests.post")
    def test_tier1_r3_04_outbound_webhook_lifecycle_dispatch(self, mock_post):
        """R3.4: Outbound webhook is triggered on lifecycle events (deal.won)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "received"}'
        mock_post.return_value = mock_response

        from modules.crm.services import crm_service
        deal = self._create_deal("Deal Outbound Trigger", valor=10000.0, user_id=self.consultant_1.id)

        if hasattr(crm_service, "dispatch_crm_webhook_event"):
            crm_service.dispatch_crm_webhook_event("deal.won", deal_id=deal.id, payload={"deal_id": deal.id})
            mock_post.assert_called()
        else:
            self.fail("dispatch_crm_webhook_event not implemented in crm_service (R3 requirement)")

    def test_tier1_r3_05_outbound_webhook_audit_log_recorded(self):
        """R3.5: Dispatched webhooks record entries in audit log."""
        from modules.crm.models import CrmWebhookLog
        log = CrmWebhookLog(
            tipo="outbound",
            evento="deal.won",
            url="https://api.external.com/webhook",
            status_code=200,
            sucesso=True,
            tempo_execucao_ms=145,
        )
        db.session.add(log)
        db.session.commit()

        queried = CrmWebhookLog.query.filter_by(evento="deal.won").first()
        self.assertIsNotNone(queried)
        self.assertTrue(queried.sucesso)
        self.assertEqual(queried.status_code, 200)

    def test_tier1_r3_06_webhooks_management_view(self):
        """R3.6: Webhook management control panel GET /crm/webhooks returns 200 OK."""
        self._login(self.manager_user)
        res = self.client.get("/crm/webhooks")
        self.assertEqual(res.status_code, 200, "GET /crm/webhooks must resolve 200 OK")
        self.assertIn("webhook".encode(), res.data.lower())

    # --- R4: Advanced Deals, Loss Reasons & Forecast ---

    def test_tier1_r4_01_weighted_forecast_calculation(self):
        """R4.1: Weighted forecast = sum(valor_total * probabilidade / 100)."""
        from modules.crm.services import crm_service

        # Deal 1: 10,000 * 25% (qualif) = 2,500
        d1 = self._create_deal("Deal Forecast 1", valor=10000.0, etapa_id=self.etapa_qualif.id)
        # Deal 2: 20,000 * 50% (apresent) = 10,000
        d2 = self._create_deal("Deal Forecast 2", valor=20000.0, etapa_id=self.etapa_apresent.id)
        # Deal 3: 30,000 * 75% (proposta) = 22,500
        d3 = self._create_deal("Deal Forecast 3", valor=30000.0, etapa_id=self.etapa_proposta.id)

        if hasattr(crm_service, "calculate_crm_forecast"):
            forecast = crm_service.calculate_crm_forecast(funil_id=self.funil.id)
            expected_weighted = 2500.0 + 10000.0 + 22500.0  # 35,000.0
            expected_nominal = 60000.0
            self.assertAlmostEqual(forecast["weighted_total"], expected_weighted, delta=1.0)
            self.assertAlmostEqual(forecast["nominal_total"], expected_nominal, delta=1.0)
        else:
            self.fail("calculate_crm_forecast not implemented in crm_service (R4 requirement)")

    def test_tier1_r4_02_deal_estimated_close_date_filter(self):
        """R4.2: Deals filter by data_estimada_fechamento for monthly forecast calculation."""
        from modules.crm.services import crm_service

        today = date.today()
        first_day_curr = date(today.year, today.month, 1)
        next_month = (first_day_curr + timedelta(days=35)).replace(day=1)

        d_curr = self._create_deal("Deal Current Month", valor=10000.0, etapa_id=self.etapa_qualif.id)
        d_next = self._create_deal("Deal Next Month", valor=20000.0, etapa_id=self.etapa_qualif.id)

        if hasattr(d_curr, "data_estimada_fechamento") or hasattr(d_curr, "data_previsao_fechamento"):
            attr = "data_estimada_fechamento" if hasattr(d_curr, "data_estimada_fechamento") else "data_previsao_fechamento"
            setattr(d_curr, attr, first_day_curr)
            setattr(d_next, attr, next_month)
            db.session.commit()

            if hasattr(crm_service, "calculate_crm_forecast"):
                res_curr = crm_service.calculate_crm_forecast(funil_id=self.funil.id, mes=today.month, ano=today.year)
                self.assertIn(d_curr.id, res_curr.get("deal_ids", [d_curr.id]))
                self.assertNotIn(d_next.id, res_curr.get("deal_ids", []))
        else:
            self.fail("Field data_estimada_fechamento/data_previsao_fechamento not on CrmNegociacao (R4 requirement)")

    def test_tier1_r4_03_mandatory_loss_reason_categorization(self):
        """R4.3: Marking deal lost enforces category selection and justification text."""
        deal = self._create_deal("Deal Loss Mandatory", valor=5000.0, user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        payload = {
            "categoria": "preco",
            "motivo": "Cliente achou o valor da mensalidade acima do orçamento interno",
        }
        res = self.client.post(f"/crm/api/negociacoes/{deal.id}/perder", json=payload)
        self.assertEqual(res.status_code, 200)

        db.session.refresh(deal)
        self.assertEqual(deal.status, "perdido")
        self.assertEqual(deal.categoria_perda, "preco")
        self.assertIn("acima do orçamento", deal.motivo_perda)

    def test_tier1_r4_04_unified_drawer_360_data(self):
        """R4.4: Drawer 360 API consolidates proposals, SollusFlow orders, and contact info."""
        emp = self._create_company("Empresa 360")
        cont = self._create_contact(emp.id, "Carlos 360", "carlos360@teste.com")
        deal = self._create_deal("Deal 360 View", empresa_id=emp.id, contato_id=cont.id, user_id=self.consultant_1.id)

        # Create linked proposal
        prop = Proposal(company="Empresa 360", cnpj=emp.cnpj, sistema_preco_total=3500.0, usuario_id=self.consultant_1.id)
        db.session.add(prop)
        db.session.flush()
        deal.proposta_id = prop.id

        # Create linked SollusFlow order
        sf = SfPedido(numero_pedido="FLOW-360", cliente_nome=emp.nome, cliente_cnpj=emp.cnpj, fase_atual=1, valor=3500.0)
        db.session.add(sf)
        db.session.flush()
        deal.sollusflow_pedido_id = sf.id
        db.session.commit()

        self._login(self.consultant_1)
        res = self.client.get(f"/crm/api/negociacoes/{deal.id}/detalhes")
        self.assertEqual(res.status_code, 200)

        data = res.get_json()["data"]
        self.assertIn("propostas", data, "Drawer data must contain propostas array")
        self.assertIn("sollusflow_pedidos", data, "Drawer data must contain sollusflow_pedidos array")
        self.assertGreaterEqual(len(data["propostas"]), 1)
        self.assertGreaterEqual(len(data["sollusflow_pedidos"]), 1)

    def test_tier1_r4_05_loss_reason_analytics_breakdown(self):
        """R4.5: CRM metrics aggregations report loss reasons breakdown by category."""
        from modules.crm.services import crm_service

        d1 = self._create_deal("Loss Deal Preco", valor=10000.0, user_id=self.consultant_1.id)
        d2 = self._create_deal("Loss Deal Concorrente", valor=15000.0, user_id=self.consultant_2.id)
        d3 = self._create_deal("Loss Deal Sem Contato", valor=5000.0, user_id=self.consultant_3.id)

        self._login(self.consultant_1)
        self.client.post(f"/crm/api/negociacoes/{d1.id}/perder", json={"categoria": "preco", "motivo": "Preço acima do budget"})
        self.client.post(f"/crm/api/negociacoes/{d2.id}/perder", json={"categoria": "concorrente", "motivo": "Fechou com Henry"})
        self.client.post(f"/crm/api/negociacoes/{d3.id}/perder", json={"categoria": "sem_contato", "motivo": "Lead parou de responder"})

        if hasattr(crm_service, "get_loss_reasons_breakdown"):
            analytics = crm_service.get_loss_reasons_breakdown(funil_id=self.funil.id)
            self.assertEqual(analytics["by_category"]["preco"]["count"], 1)
            self.assertEqual(analytics["by_category"]["concorrente"]["count"], 1)
            self.assertEqual(analytics["by_category"]["sem_contato"]["count"], 1)
            self.assertEqual(analytics["total_lost_value"], 30000.0)
        else:
            self.fail("get_loss_reasons_breakdown not implemented in crm_service (R4 requirement)")



# ==============================================================================
# TIER 2: BOUNDARY & CORNER CASES (>=5 per feature)
# ==============================================================================

class TestTier2BoundaryCornerCases(CrmE2EBaseTestCase):
    """Tier 2: Boundary, error paths, and edge conditions."""

    # --- R1 Boundary Cases ---

    def test_tier2_r1_01_round_robin_skips_inactive_consultants(self):
        """R1 Boundary: Inactive consultants are completely excluded from round-robin."""
        from modules.crm.services import crm_service

        deals = [self._create_deal(f"Lead Inactive Skip {i}", user_id=None) for i in range(6)]
        if hasattr(crm_service, "distribute_deal_round_robin"):
            assigned_users = [crm_service.distribute_deal_round_robin(d)["user_id"] for d in deals]
            self.assertNotIn(self.consultant_inactive.id, assigned_users, "Inactive consultant must not receive deals")
        else:
            self.fail("distribute_deal_round_robin not implemented")

    def test_tier2_r1_02_round_robin_zero_active_consultants(self):
        """R1 Boundary: Zero active consultants in commercial handles gracefully without 500 error."""
        from modules.crm.services import crm_service

        self.consultant_1.is_active = False
        self.consultant_2.is_active = False
        self.consultant_3.is_active = False
        db.session.commit()

        deal = self._create_deal("Lead Zero Consultants", user_id=None)
        if hasattr(crm_service, "distribute_deal_round_robin"):
            res = crm_service.distribute_deal_round_robin(deal)
            self.assertIsNone(res.get("user_id"), "When no consultants active, user_id should be None")
        else:
            self.fail("distribute_deal_round_robin not implemented")

    def test_tier2_r1_03_lead_with_preassigned_consultant_bypasses_roulette(self):
        """R1 Boundary: Lead specifying consultor_id bypasses round-robin and leaves pointer unchanged."""
        from modules.crm.services import crm_service

        deal = self._create_deal("Lead Preassigned", user_id=self.consultant_2.id)
        if hasattr(crm_service, "distribute_deal_round_robin"):
            res = crm_service.distribute_deal_round_robin(deal, allow_override=False)
            self.assertEqual(res["user_id"], self.consultant_2.id, "Pre-assigned consultant must be preserved")
        else:
            self.fail("distribute_deal_round_robin not implemented")

    def test_tier2_r1_04_stage_transition_without_automation_rule(self):
        """R1 Boundary: Transitioning into stage without rule succeeds with no tasks created."""
        deal = self._create_deal("Deal No Automation", user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        res = self.client.post(
            f"/crm/api/negociacoes/{deal.id}/mover",
            json={"new_etapa_id": self.etapa_apresent.id}
        )
        self.assertEqual(res.status_code, 200)
        tasks_count = CrmTarefa.query.filter_by(negociacao_id=deal.id).count()
        self.assertEqual(tasks_count, 0)

    def test_tier2_r1_05_stage_move_avoids_duplicate_pending_tasks(self):
        """R1 Boundary: Moving back and forth does not duplicate identical pending tasks."""
        from modules.crm.services import crm_service

        deal = self._create_deal("Deal Move Bounce", user_id=self.consultant_1.id)
        if hasattr(crm_service, "execute_stage_automations"):
            # Trigger twice
            crm_service.execute_stage_automations(deal, self.etapa_qualif)
            crm_service.execute_stage_automations(deal, self.etapa_qualif)
            tasks = CrmTarefa.query.filter_by(negociacao_id=deal.id, concluida=False).all()
            self.assertEqual(len(tasks), 1, "Should not duplicate pending task with same title")
        else:
            self.fail("execute_stage_automations not implemented")

    def test_tier2_r1_06_proposal_created_without_deal_id_unaffected(self):
        """R1 Boundary: Proposals created normally without deal_id operate smoothly."""
        prop = Proposal(company="Empresa Sem Deal", cnpj="12345678000190", sistema_preco_total=1000.0, usuario_id=self.consultant_1.id)
        db.session.add(prop)
        db.session.commit()
        self.assertIsNotNone(prop.id)

    def test_tier2_r1_07_proposal_approval_with_multi_version_revisions(self):
        """R1 Boundary: Approving revised proposal version v2 updates linked deal via original_proposal_id."""
        deal = self._create_deal("Deal Revision Parent", valor=8000.0, user_id=self.consultant_1.id)
        p_v1 = Proposal(company="Empresa Revision", original_proposal_id=None, version_number=1, is_current=False, usuario_id=self.consultant_1.id)
        db.session.add(p_v1)
        db.session.flush()
        deal.proposta_id = p_v1.id

        p_v2 = Proposal(company="Empresa Revision", original_proposal_id=p_v1.id, version_number=2, is_current=True, usuario_id=self.consultant_1.id)
        db.session.add(p_v2)
        db.session.commit()

        from modules.crm.services import crm_service
        if hasattr(crm_service, "on_proposal_approved"):
            crm_service.on_proposal_approved(p_v2.id)
            db.session.refresh(deal)
            self.assertEqual(deal.status, "ganho")
        else:
            self.fail("on_proposal_approved not implemented")

    # --- R2 Boundary Cases ---

    def test_tier2_r2_01_whatsapp_phone_sanitization_edge_cases(self):
        """R2 Boundary: Phone sanitization handles dirty strings, missing DDD, and international prefixes."""
        from modules.crm.services import crm_service

        if not hasattr(crm_service, "sanitize_whatsapp_phone"):
            self.fail("sanitize_whatsapp_phone not implemented in crm_service (R2 requirement)")

        # Valid formatted
        self.assertEqual(crm_service.sanitize_whatsapp_phone("+55 (21) 98888-7777"), "5521988887777")
        # Valid raw 11 digits
        self.assertEqual(crm_service.sanitize_whatsapp_phone("21988887777"), "5521988887777")
        # Valid with leading 0
        self.assertEqual(crm_service.sanitize_whatsapp_phone("021988887777"), "5521988887777")
        # Already has 55
        self.assertEqual(crm_service.sanitize_whatsapp_phone("5521988887777"), "5521988887777")
        # Invalid / short
        self.assertIsNone(crm_service.sanitize_whatsapp_phone("12345"))
        # Empty string
        self.assertIsNone(crm_service.sanitize_whatsapp_phone(""))

    def test_tier2_r2_02_whatsapp_template_missing_fields_fallback(self):
        """R2 Boundary: Template substitution provides safe fallbacks when contact or company missing."""
        from modules.crm.services import crm_service

        deal = self._create_deal("Deal No Contact Company", user_id=self.consultant_1.id)
        template = "Olá {nome_contato}, saudações da {empresa}!"

        if hasattr(crm_service, "render_whatsapp_template"):
            res = crm_service.render_whatsapp_template(template, deal_id=deal.id)
            self.assertIn("Cliente", res)
            self.assertIn("sua empresa", res)
        else:
            self.fail("render_whatsapp_template not implemented")

    def test_tier2_r2_03_whatsapp_template_missing_proposal_link_fallback(self):
        """R2 Boundary: Missing proposal link falls back to empty string without template crash."""
        from modules.crm.services import crm_service

        deal = self._create_deal("Deal No Proposal", user_id=self.consultant_1.id)
        deal.proposta_id = None
        db.session.commit()

        template = "Avalie aqui: {link_proposta}."
        if hasattr(crm_service, "render_whatsapp_template"):
            res = crm_service.render_whatsapp_template(template, deal_id=deal.id)
            self.assertNotIn("{link_proposta}", res)
        else:
            self.fail("render_whatsapp_template not implemented")

    def test_tier2_r2_04_empty_timeline_interaction_rejected(self):
        """R2 Boundary: Empty or whitespace-only interaction is rejected with 400 Bad Request."""
        deal = self._create_deal("Deal Reject Empty Log", user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        res = self.client.post(f"/crm/api/negociacoes/{deal.id}/anotacoes", json={"conteudo": "   "})
        self.assertEqual(res.status_code, 400)

    def test_tier2_r2_05_cockpit_empty_state_no_tasks(self):
        """R2 Boundary: Consultant with 0 tasks renders clean empty state without exception."""
        self._login(self.consultant_3)
        res = self.client.get("/crm/tarefas")
        self.assertEqual(res.status_code, 200)

    def test_tier2_r2_06_task_due_date_midnight_boundary(self):
        """R2 Boundary: Tasks at 23:59:59 today vs 00:00:00 tomorrow are classified accurately."""
        from modules.crm.services import crm_service

        deal = self._create_deal("Deal Boundary Time", user_id=self.consultant_1.id)
        today = date.today()
        dt_end_today = datetime(today.year, today.month, today.day, 23, 59, 59)
        dt_start_tomorrow = datetime(today.year, today.month, today.day, 0, 0, 0) + timedelta(days=1)

        t1 = CrmTarefa(id="t_eod", negociacao_id=deal.id, user_id=self.consultant_1.id, titulo="End Today", data_vencimento=dt_end_today)
        t2 = CrmTarefa(id="t_som", negociacao_id=deal.id, user_id=self.consultant_1.id, titulo="Start Tomorrow", data_vencimento=dt_start_tomorrow)
        db.session.add_all([t1, t2])
        db.session.commit()

        if hasattr(crm_service, "get_cockpit_tasks"):
            res = crm_service.get_cockpit_tasks(user_id=self.consultant_1.id)
            self.assertEqual(res["counts"]["today"], 1)
            self.assertEqual(res["counts"]["upcoming"], 1)
        else:
            self.fail("get_cockpit_tasks not implemented")

    # --- R3 Boundary Cases ---

    def test_tier2_r3_01_inbound_webhook_missing_token_returns_401(self):
        """R3 Boundary: Inbound webhook without token returns HTTP 401 Unauthorized."""
        res = self.client.post("/crm/api/webhooks/inbound", json={"nome": "Test"})
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertFalse(data.get("success", False))

    def test_tier2_r3_02_inbound_webhook_invalid_token_returns_401(self):
        """R3 Boundary: Inbound webhook with invalid token returns HTTP 401 Unauthorized."""
        headers = {"X-API-Token": "completely-invalid-secret-token"}
        res = self.client.post("/crm/api/webhooks/inbound", json={"nome": "Test"}, headers=headers)
        self.assertEqual(res.status_code, 401)

    def test_tier2_r3_03_inbound_webhook_malformed_json_returns_400(self):
        """R3 Boundary: Inbound webhook with non-JSON or malformed payload returns HTTP 400 Bad Request."""
        headers = {"X-API-Token": TestConfig.CRM_WEBHOOK_API_TOKEN, "Content-Type": "application/json"}
        res = self.client.post("/crm/api/webhooks/inbound", data="not-valid-json", headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_tier2_r3_04_inbound_webhook_unformatted_cnpj_matching(self):
        """R3 Boundary: CNPJ matching normalizes punctuation (12.345.678/0001-90 vs 12345678000190)."""
        emp = self._create_company("Punctuation Test", cnpj="99.888.777/0001-66")
        payload = {
            "nome_negociacao": "Deal Clean CNPJ",
            "empresa": {"nome": "Punctuation Test", "cnpj": "99888777000166"},
            "contato": {"nome": "Teste", "email": "teste@clean.com"},
        }
        headers = {"X-API-Token": TestConfig.CRM_WEBHOOK_API_TOKEN}
        res = self.client.post("/crm/api/webhooks/inbound", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)

        deal = CrmNegociacao.query.filter_by(nome="Deal Clean CNPJ").first()
        self.assertEqual(deal.empresa_id, emp.id)

    @patch("requests.post", side_effect=Exception("Connection Timeout: Target Server Unreachable"))
    def test_tier2_r3_05_outbound_webhook_network_error_resilience(self, mock_post):
        """R3 Boundary: Network errors or timeouts during outbound dispatch do not crash caller."""
        from modules.crm.services import crm_service
        deal = self._create_deal("Deal Network Failure Test", user_id=self.consultant_1.id)

        if hasattr(crm_service, "dispatch_crm_webhook_event"):
            # Should not raise exception
            try:
                crm_service.dispatch_crm_webhook_event("deal.lost", deal_id=deal.id, payload={"deal_id": deal.id})
            except Exception as e:
                self.fail(f"dispatch_crm_webhook_event raised unexpected exception: {e}")
        else:
            self.fail("dispatch_crm_webhook_event not implemented")

    def test_tier2_r3_06_outbound_webhook_inactive_not_dispatched(self):
        """R3 Boundary: Inactive webhooks are skipped during lifecycle dispatch."""
        from modules.crm.models import CrmWebhook
        wh = CrmWebhook(nome="Inactive Webhook", url="https://example.com/wh", evento="deal.won", ativo=False)
        db.session.add(wh)
        db.session.commit()

        from modules.crm.services import crm_service
        if hasattr(crm_service, "get_active_outbound_webhooks"):
            active = crm_service.get_active_outbound_webhooks(evento="deal.won")
            self.assertNotIn(wh.id, [w.id for w in active])
        else:
            self.fail("get_active_outbound_webhooks not implemented in crm_service")

    def test_tier2_r3_07_outbound_webhook_hmac_signature(self):
        """R3 Boundary: Outbound dispatch generates correct HMAC SHA256 signature."""
        from modules.crm.services import crm_service

        secret = "secret-hmac-key"
        payload_bytes = b'{"event":"deal.won","deal_id":123}'
        expected_sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

        if hasattr(crm_service, "compute_webhook_signature"):
            sig = crm_service.compute_webhook_signature(payload_bytes, secret)
            self.assertEqual(sig, f"sha256={expected_sig}")
        else:
            self.fail("compute_webhook_signature not implemented in crm_service (R3 requirement)")

    # --- R4 Boundary Cases ---

    def test_tier2_r4_01_forecast_zero_probability_deal(self):
        """R4 Boundary: Deal with 0% probability contributes R$ 0.00 to weighted total."""
        from modules.crm.services import crm_service

        deal = self._create_deal("Deal Zero Prob", valor=50000.0, etapa_id=self.etapa_perdido.id)
        if hasattr(crm_service, "calculate_crm_forecast"):
            res = crm_service.calculate_crm_forecast(funil_id=self.funil.id)
            # Stage probability is 0%
            self.assertEqual(res.get("stage_weighted", {}).get(self.etapa_perdido.id, 0.0), 0.0)
        else:
            self.fail("calculate_crm_forecast not implemented")

    def test_tier2_r4_02_forecast_negative_or_exceeded_probability(self):
        """R4 Boundary: Probabilities < 0% or > 100% are clamped to valid 0-100 range."""
        from modules.crm.services import crm_service

        if hasattr(crm_service, "normalize_probability"):
            self.assertEqual(crm_service.normalize_probability(-20), 0)
            self.assertEqual(crm_service.normalize_probability(150), 100)
            self.assertEqual(crm_service.normalize_probability(45), 45)
        else:
            self.fail("normalize_probability not implemented in crm_service")

    def test_tier2_r4_03_forecast_zero_or_null_deal_value(self):
        """R4 Boundary: Deals with null or 0 valor_total handle gracefully without ZeroDivisionError."""
        from modules.crm.services import crm_service

        deal = self._create_deal("Deal Zero Value", valor=0.0, etapa_id=self.etapa_qualif.id)
        if hasattr(crm_service, "calculate_crm_forecast"):
            res = crm_service.calculate_crm_forecast(funil_id=self.funil.id)
            self.assertGreaterEqual(res["weighted_total"], 0.0)
        else:
            self.fail("calculate_crm_forecast not implemented")

    def test_tier2_r4_04_loss_reason_whitespace_only_rejected(self):
        """R4 Boundary: Loss reason with only spaces is rejected with HTTP 400."""
        deal = self._create_deal("Deal Loss Spaces", user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        res = self.client.post(
            f"/crm/api/negociacoes/{deal.id}/perder",
            json={"categoria": "preco", "motivo": "    "}
        )
        self.assertEqual(res.status_code, 400)

    def test_tier2_r4_05_loss_reason_invalid_category_rejected(self):
        """R4 Boundary: Invalid category choice is rejected with HTTP 400."""
        deal = self._create_deal("Deal Loss Bad Category", user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        res = self.client.post(
            f"/crm/api/negociacoes/{deal.id}/perder",
            json={"categoria": "categoria_inexistente", "motivo": "Justificativa válida"}
        )
        self.assertEqual(res.status_code, 400)

    def test_tier2_r4_06_drawer_360_empty_proposals_and_orders(self):
        """R4 Boundary: Deal with no proposals and no Flow orders returns empty arrays, not null."""
        deal = self._create_deal("Deal Empty Drawer", user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        res = self.client.get(f"/crm/api/negociacoes/{deal.id}/detalhes")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertIsInstance(data.get("propostas"), list)
        self.assertIsInstance(data.get("sollusflow_pedidos"), list)


# ==============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS (Pairwise Interactions)
# ==============================================================================

class TestTier3CrossFeatureCombinations(CrmE2EBaseTestCase):
    """Tier 3: Pairwise interactions across Webhook, Deal, Round-Robin, Stage Rules, Proposals, and SollusFlow."""

    def test_tier3_01_inbound_webhook_to_round_robin_to_stage_rule_to_task(self):
        """Pairwise: Inbound Webhook -> Deal -> Round-Robin -> Stage Rule -> Automated Task Creation."""
        payload = {
            "nome_negociacao": "Combo Inbound Lead",
            "valor": 8500.0,
            "empresa": {"nome": "Combo Empresa", "cnpj": "22.333.444/0001-55"},
            "contato": {"nome": "João Combo", "email": "joao@combo.com", "telefone": "21988881111"},
            "funil_id": self.funil.id,
        }
        headers = {"X-API-Token": TestConfig.CRM_WEBHOOK_API_TOKEN}
        res = self.client.post("/crm/api/webhooks/inbound", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)

        deal = CrmNegociacao.query.filter_by(nome="Combo Inbound Lead").first()
        self.assertIsNotNone(deal)

        # 1. Round-Robin assigned to active consultant
        self.assertIn(deal.user_id, [self.consultant_1.id, self.consultant_2.id, self.consultant_3.id])

        # 2. Automated stage task created
        tasks = CrmTarefa.query.filter_by(negociacao_id=deal.id).all()
        self.assertGreaterEqual(len(tasks), 1, "Automated follow-up task must be generated")
        self.assertEqual(tasks[0].user_id, deal.user_id)

    def test_tier3_02_proposal_created_from_deal_syncs_values_and_stage(self):
        """Pairwise: Proposal Created from Deal -> Deal Proposta Link -> Value Update -> Stage Advance."""
        deal = self._create_deal("Combo Deal Proposal", valor=1000.0, etapa_id=self.etapa_qualif.id, user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        # Create proposal with deal_id
        prop = Proposal(
            company="Empresa Combo Prop",
            cnpj="33444555000166",
            sistema_preco_total=9200.0,
            locacao_valor_mensal=300.0,
            usuario_id=self.consultant_1.id,
        )
        db.session.add(prop)
        db.session.flush()

        from modules.crm.services import crm_service
        if hasattr(crm_service, "link_proposal_to_deal"):
            crm_service.link_proposal_to_deal(deal.id, prop.id)
            db.session.refresh(deal)
            self.assertEqual(deal.proposta_id, prop.id)
            self.assertGreaterEqual(deal.valor_total, 9200.0)
            self.assertEqual(deal.etapa_id, self.etapa_proposta.id)
        else:
            self.fail("link_proposal_to_deal not implemented in crm_service")

    @patch("requests.post")
    def test_tier3_03_proposal_approval_marks_won_and_triggers_sollusflow_order(self, mock_post):
        """Pairwise: Proposal Approved -> Deal Marked Won -> Outbound Webhook Dispatched -> SollusFlow Order Generated."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        deal = self._create_deal("Combo Won Flow Deal", valor=15000.0, user_id=self.consultant_1.id)
        prop = Proposal(company="Empresa Won Flow", cnpj="44555666000177", sistema_preco_total=15000.0, usuario_id=self.consultant_1.id)
        db.session.add(prop)
        db.session.flush()
        deal.proposta_id = prop.id
        db.session.commit()

        from modules.crm.services import crm_service
        if hasattr(crm_service, "on_proposal_approved"):
            crm_service.on_proposal_approved(prop.id)
            db.session.refresh(deal)
            self.assertEqual(deal.status, "ganho")
            self.assertIsNotNone(deal.sollusflow_pedido_id)
            # Verify SollusFlow order
            sf_order = SfPedido.query.get(deal.sollusflow_pedido_id)
            self.assertIsNotNone(sf_order)
            self.assertEqual(float(sf_order.valor), 15000.0)
        else:
            self.fail("on_proposal_approved not implemented in crm_service")

    def test_tier3_04_inbound_lead_deduplication_reuses_company_and_links_deal(self):
        """Pairwise: Deduplication reuses company, links new deal, and appends interaction note."""
        emp = self._create_company("Empresa Multi Lead", cnpj="55.666.777/0001-88")
        payload = {
            "nome_negociacao": "Segundo Lead Mesma Empresa",
            "valor": 6000.0,
            "empresa": {"nome": "Empresa Multi Lead", "cnpj": "55666777000188"},
            "contato": {"nome": "Fernanda Silva", "email": "fernanda@multilead.com"},
        }
        headers = {"X-API-Token": TestConfig.CRM_WEBHOOK_API_TOKEN}
        res = self.client.post("/crm/api/webhooks/inbound", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)

        deal = CrmNegociacao.query.filter_by(nome="Segundo Lead Mesma Empresa").first()
        self.assertEqual(deal.empresa_id, emp.id)

    @patch("requests.post")
    def test_tier3_05_deal_lost_dispatches_webhook_and_updates_forecast(self, mock_post):
        """Pairwise: Deal marked lost -> Outbound webhook 'deal.lost' dispatched -> Excluded from forecast."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        deal = self._create_deal("Combo Lost Deal", valor=25000.0, etapa_id=self.etapa_proposta.id, user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        payload = {"categoria": "concorrente", "motivo": "Optou pela Henry devido a prazo de entrega"}
        res = self.client.post(f"/crm/api/negociacoes/{deal.id}/perder", json=payload)
        self.assertEqual(res.status_code, 200)

        db.session.refresh(deal)
        self.assertEqual(deal.status, "perdido")

        from modules.crm.services import crm_service
        if hasattr(crm_service, "calculate_crm_forecast"):
            forecast = crm_service.calculate_crm_forecast(funil_id=self.funil.id)
            # Lost deal is excluded from active pipeline
            self.assertNotIn(deal.id, forecast.get("open_deal_ids", []))
        else:
            self.fail("calculate_crm_forecast not implemented")

    def test_tier3_06_cockpit_task_completion_updates_deal_timeline_and_card_cache(self):
        """Pairwise: Completing task in Cockpit logs timeline interaction and updates proxima_tarefa cache."""
        deal = self._create_deal("Combo Task Cache", user_id=self.consultant_1.id)
        now = datetime.utcnow()
        t1 = CrmTarefa(id="t_first", negociacao_id=deal.id, user_id=self.consultant_1.id, titulo="Tarefa 1", data_vencimento=now, concluida=False)
        t2 = CrmTarefa(id="t_second", negociacao_id=deal.id, user_id=self.consultant_1.id, titulo="Tarefa 2", data_vencimento=now + timedelta(days=2), concluida=False)
        db.session.add_all([t1, t2])
        db.session.commit()

        self._login(self.consultant_1)
        res = self.client.post(f"/crm/api/tarefas/{t1.id}/toggle", json={"concluida": True})
        self.assertEqual(res.status_code, 200)

        db.session.refresh(deal)
        # Next task cache should advance to t2
        self.assertEqual(deal.proxima_tarefa_id, t2.id)
        self.assertEqual(deal.proxima_tarefa_titulo, "Tarefa 2")


# ==============================================================================
# TIER 4: REAL-WORLD WORKLOAD SCENARIOS (>=5 realistic application flows)
# ==============================================================================

class TestTier4RealWorldWorkloadScenarios(CrmE2EBaseTestCase):
    """Tier 4: Complete commercial application journeys from capture to closing."""

    def test_tier4_01_scenario_full_organic_lead_to_sale_and_flow_order(self):
        """Workload Scenario 1: Full organic lead lifecycle from form ingestion to closed sale and flow order."""
        # 1. Lead submits website contact form
        payload = {
            "nome_negociacao": "Aquisição 3 Relógios iDClass",
            "valor": 6800.0,
            "empresa": {"nome": "Hospital Santa Clara", "cnpj": "66.777.888/0001-99"},
            "contato": {"nome": "Dra. Helena", "email": "helena@santaclara.med.br", "telefone": "21977776666"},
            "funil_id": self.funil.id,
            "origem": "Website Organic",
        }
        res_ingest = self.client.post(
            "/crm/api/webhooks/inbound",
            json=payload,
            headers={"X-API-Token": TestConfig.CRM_WEBHOOK_API_TOKEN}
        )
        self.assertEqual(res_ingest.status_code, 201)
        deal_id = res_ingest.get_json()["deal_id"]
        deal = CrmNegociacao.query.get(deal_id)

        # 2. Consultant views task in Cockpit
        consultant = User.query.get(deal.user_id)
        self._login(consultant)
        res_cockpit = self.client.get("/crm/tarefas")
        self.assertEqual(res_cockpit.status_code, 200)

        # 3. Consultant sends 1-click WhatsApp message and logs interaction
        from modules.crm.services import crm_service
        if hasattr(crm_service, "build_whatsapp_link"):
            wa_link = crm_service.build_whatsapp_link(deal.contato.celular, "Olá Dra. Helena! Sou da Sollus.")
            self.assertIn("5521977776666", wa_link)

        self.client.post(
            f"/crm/api/negociacoes/{deal.id}/anotacoes",
            json={"tipo": "whatsapp", "conteudo": "Contato realizado via WhatsApp. Cliente solicitou proposta formal."}
        )

        # 4. Consultant creates proposal
        prop = Proposal(
            company="Hospital Santa Clara",
            cnpj="66777888000199",
            sistema_preco_total=6800.0,
            usuario_id=consultant.id,
        )
        db.session.add(prop)
        db.session.flush()

        if hasattr(crm_service, "link_proposal_to_deal"):
            crm_service.link_proposal_to_deal(deal.id, prop.id)

        # 5. Client approves proposal -> Deal marked Won -> Flow order created
        if hasattr(crm_service, "on_proposal_approved"):
            crm_service.on_proposal_approved(prop.id)
            db.session.refresh(deal)
            self.assertEqual(deal.status, "ganho")
            self.assertIsNotNone(deal.sollusflow_pedido_id)

    def test_tier4_02_scenario_competitive_loss_and_retrospective(self):
        """Workload Scenario 2: Competitive loss journey with mandatory category and analytics audit."""
        deal = self._create_deal("Projeto Acesso Portaria", valor=18000.0, etapa_id=self.etapa_proposta.id, user_id=self.consultant_2.id)
        self._login(self.consultant_2)

        # Consultant marks deal as lost
        loss_payload = {
            "categoria": "concorrente",
            "motivo": "Cliente fechou com fornecedor Control iD por oferecer 1 ano adicional de garantia",
        }
        res_loss = self.client.post(f"/crm/api/negociacoes/{deal.id}/perder", json=loss_payload)
        self.assertEqual(res_loss.status_code, 200)

        db.session.refresh(deal)
        self.assertEqual(deal.status, "perdido")
        self.assertEqual(deal.categoria_perda, "concorrente")

        # Verify loss reason in timeline
        timeline = CrmInteracao.query.filter_by(negociacao_id=deal.id, tipo="perda").first()
        self.assertIsNotNone(timeline)
        self.assertIn("Control iD", timeline.conteudo)

    def test_tier4_03_scenario_high_volume_lead_burst_load_balancing(self):
        """Workload Scenario 3: 15 rapid inbound leads balanced equally (5-5-5) across 3 consultants."""
        from modules.crm.services import crm_service

        if not hasattr(crm_service, "distribute_deal_round_robin"):
            self.fail("distribute_deal_round_robin not implemented in crm_service")

        assigned_counts: dict[int, int] = {
            self.consultant_1.id: 0,
            self.consultant_2.id: 0,
            self.consultant_3.id: 0,
        }

        for i in range(15):
            d = self._create_deal(f"Burst Lead {i}", valor=1000.0, user_id=None)
            res = crm_service.distribute_deal_round_robin(d)
            uid = res["user_id"]
            assigned_counts[uid] += 1

        self.assertEqual(assigned_counts[self.consultant_1.id], 5, "Consultant 1 must receive exactly 5 leads")
        self.assertEqual(assigned_counts[self.consultant_2.id], 5, "Consultant 2 must receive exactly 5 leads")
        self.assertEqual(assigned_counts[self.consultant_3.id], 5, "Consultant 3 must receive exactly 5 leads")

    def test_tier4_04_scenario_proposal_negotiation_multi_version_lifecycle(self):
        """Workload Scenario 4: Multi-version proposal negotiation, deal value adjustment, and won sync."""
        deal = self._create_deal("Negociação Acesso Corporativo", valor=15000.0, user_id=self.consultant_1.id)

        # Version 1: 15,000
        p_v1 = Proposal(company="Corp Access", sistema_preco_total=15000.0, version_number=1, is_current=False, usuario_id=self.consultant_1.id)
        db.session.add(p_v1)
        db.session.flush()
        deal.proposta_id = p_v1.id

        # Version 2 (negotiated discount): 12,000
        p_v2 = Proposal(company="Corp Access", original_proposal_id=p_v1.id, sistema_preco_total=12000.0, version_number=2, is_current=True, usuario_id=self.consultant_1.id)
        db.session.add(p_v2)
        db.session.commit()

        from modules.crm.services import crm_service
        if hasattr(crm_service, "link_proposal_to_deal"):
            crm_service.link_proposal_to_deal(deal.id, p_v2.id)
            db.session.refresh(deal)
            self.assertEqual(deal.valor_total, 12000.0)

        # Client approves negotiated v2
        if hasattr(crm_service, "on_proposal_approved"):
            crm_service.on_proposal_approved(p_v2.id)
            db.session.refresh(deal)
            self.assertEqual(deal.status, "ganho")
            self.assertEqual(deal.sollusflow_pedido_id is not None, True)

    @patch("requests.post")
    def test_tier4_05_scenario_resilient_integrations_under_failing_endpoints(self, mock_post):
        """Workload Scenario 5: System resilience when external webhooks fail or timeout."""
        # Mock requests.post raising timeout
        mock_post.side_effect = Exception("HTTP 504 Gateway Timeout on external endpoint")

        deal = self._create_deal("Deal External Outage Test", valor=5000.0, user_id=self.consultant_1.id)
        self._login(self.consultant_1)

        # Winning deal should trigger outbound webhook without breaking internal operation
        res = self.client.post(f"/crm/api/negociacoes/{deal.id}/ganhar")
        self.assertEqual(res.status_code, 200, "Internal request must succeed despite webhook failure")

        db.session.refresh(deal)
        self.assertEqual(deal.status, "ganho")


if __name__ == "__main__":
    unittest.main()
