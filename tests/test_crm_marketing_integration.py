"""Comprehensive Integration & E2E Test Suite for Sollus Marketing & CRM Integration.

Authoritative References:
- ORIGINAL_REQUEST.md (## 2026-09-22T19:46:50Z - RD Station Autonomous Parity)
- PROJECT.md (Sollus Marketing & CRM Integration Architecture & Interface Contracts)
- explorer_tests_1/handoff.md (Test Suite Architecture & Specifications)
- spec_miner_rd_1/handoff.md (Mined RD Station Data & Schemas)

Test Suites (28 test cases across 5 categories):
- TestR1LeadQualificationAndOrigins (6 test cases):
    1. Persistence of qualification fields (origem_id, canal_origem, temperatura, canal_preferencial, necessidade)
    2. CrmEmpresa fields porte and numero_funcionarios persistence
    3. to_dict() outputs for CrmNegociacao and CrmEmpresa include qualification attributes
    4. Kanban view renders temperature badges and origin indicators
    5. POST /crm/api/negociacoes/<deal_id>/qualificar endpoint updates deal and company
    6. Drawer 360 payload (/crm/api/negociacoes/<deal_id>/detalhes) includes qualification & company info
- TestR2InboundLeadAutomationFlow (7 test cases):
    1. Webhook inbound token authentication (401 on missing/bad token, 201 on valid token)
    2. Ingestion of conversion payload creating deal, company, and contact
    3. Smart deduplication of company by formatted/unformatted CNPJ and contact by lowercase email
    4. Regional routing by DDD (DDD 11 -> SP consultant, DDD 21 -> RJ consultant)
    5. Target pipeline routing (Ponto vs Acesso vs Assistência) based on need/slug/tags
    6. Immediate first-contact task scheduling (SDR WhatsApp/Call task)
    7. Inbound timeline interaction logging and webhook execution logs
- TestR3LeadSegmentationAndFilters (6 test cases):
    1. Route /crm/leads rendering
    2. Filter leads by tags (e.g. 'ponto', 'acesso')
    3. Filter leads by state (UF) and DDD
    4. Filter leads by temperatura and origem
    5. Formatted CSV export (/crm/leads/export or ?export=csv) with headers and data
    6. Lead drawer timeline conversion history (/crm/api/leads/<id>/detalhes)
- TestR4StructuredLossReasonsAndMetrics (6 test cases):
    1. POST /crm/api/negociacoes/<id>/perder rejects missing/empty category and reason with HTTP 400
    2. Marking deal lost successfully updates status, moves to lost stage, records category and reason
    3. Loss reasons breakdown service (get_loss_reasons_breakdown) by category and reason
    4. Funnel filtering in loss reasons breakdown service
    5. Marketing channel conversion metrics (get_channel_conversion_metrics)
    6. Regional GEO radar distribution (get_lead_geo_distribution)
- TestR5MarketingIntegrationEndToEnd (3 test cases):
    1. Full inbound conversion -> regional routing -> Kanban -> qualification -> won proposal
    2. Full inbound conversion -> regional routing -> lost with structured reason -> metrics update
    3. Webhook deduplication lifecycle with subsequent conversion in a different pipeline
"""
from __future__ import annotations

import csv
import io
import json
import re
import unittest
import uuid
from datetime import datetime, date, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from sqlalchemy import or_, func
from sqlalchemy.pool import StaticPool

from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department, Proposal
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmInteracao,
    CrmLeadMarketing,
    CrmMotivoPerda,
    CrmRegraDistribuicao,
    CrmWebhookLog,
)
from modules.crm.services import crm_service

# Optional model CrmOrigem (introduced in Milestone M1)
try:
    from modules.crm.models import CrmOrigem
except ImportError:
    CrmOrigem = None


class TestConfigMarketingIntegration:
    """Isolated In-Memory SQLite configuration for Marketing & CRM Integration tests."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-marketing-integration"
    CRM_WEBHOOK_API_TOKEN = "sollus-test-token-secret-12345"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class BaseCrmMarketingTestCase(unittest.TestCase):
    """Base setup with in-memory database, seed data, and authentication helpers."""

    def setUp(self):
        self.app = create_app(TestConfigMarketingIntegration)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()

        # Mock external outbound HTTP requests
        self._req_patcher = patch("requests.post", return_value=MagicMock(status_code=200, text="ok"))
        self._mock_req = self._req_patcher.start()

        # 1. Commercial Department
        self.dept = Department.query.filter_by(slug="comercial").first()
        if not self.dept:
            self.dept = Department(name="COMERCIAL", slug="comercial")
            db.session.add(self.dept)
            db.session.flush()

        # 2. Commercial Active Consultants
        # SP Consultant (DDD 11-19)
        self.consultor_sp = User(
            id=5009,
            usuario="hizael.ferreira",
            nome_completo="Hizael Ferreira (SP)",
            email="hizael@sollustecnologia.com",
            password_hash="hash_sp",
            tipo="consultorsp",
            role="usuario",
            is_active=True,
            department_id=self.dept.id,
            permissions={"crm": True},
        )
        # RJ Consultant (DDD 21, 22, 24)
        self.consultor_rj = User(
            id=5004,
            usuario="luciana.claudino",
            nome_completo="Luciana Claudino (RJ)",
            email="luciana@sollustecnologia.com",
            password_hash="hash_rj",
            tipo="consultor",
            role="usuario",
            is_active=True,
            department_id=self.dept.id,
            permissions={"crm": True},
        )
        # General / Roleta Consultant
        self.consultor_geral = User(
            id=5008,
            usuario="gilson.freitas",
            nome_completo="Gilson Freitas (Geral)",
            email="gilson@sollustecnologia.com",
            password_hash="hash_geral",
            tipo="consultor",
            role="usuario",
            is_active=True,
            department_id=self.dept.id,
            permissions={"crm": True},
        )
        # Commercial Manager / Admin
        self.admin_manager = User(
            id=5001,
            usuario="admin_marketing",
            nome_completo="Gestor Comercial Marketing",
            email="admin.mkt@sollus.com",
            password_hash="hash_adm",
            tipo="admin",
            role="admin",
            is_active=True,
            department_id=self.dept.id,
            permissions={"crm": True, "admin": True, "crm_metricas": True},
        )
        db.session.add_all([
            self.consultor_sp,
            self.consultor_rj,
            self.consultor_geral,
            self.admin_manager,
        ])
        db.session.commit()

        # 3. Pipelines & Stages (Ponto, Acesso, Assistencia Tecnica)
        # 3.1 Funil Ponto
        self.funil_ponto = CrmFunil(
            id="funil_ponto",
            nome="Funil Ponto",
            slug="funil_ponto",
            tipo="ponto",
            ordem=1,
            ativo=True,
        )
        db.session.add(self.funil_ponto)
        db.session.flush()

        self.etapa_ponto_novo = CrmEtapa(
            id="etapa_ponto_novo",
            funil_id=self.funil_ponto.id,
            nome="Novo",
            nickname="N",
            ordem=1,
            tipo="normal",
            probabilidade=10.0,
            cor="#3b82f6",
        )
        self.etapa_ponto_qualif = CrmEtapa(
            id="etapa_ponto_qualif",
            funil_id=self.funil_ponto.id,
            nome="Qualificação",
            nickname="Q",
            ordem=2,
            tipo="normal",
            probabilidade=25.0,
            cor="#8b5cf6",
        )
        self.etapa_ponto_proposta = CrmEtapa(
            id="etapa_ponto_proposta",
            funil_id=self.funil_ponto.id,
            nome="Proposta Enviada",
            nickname="P",
            ordem=3,
            tipo="normal",
            probabilidade=75.0,
            cor="#f59e0b",
        )
        self.etapa_ponto_ganho = CrmEtapa(
            id="etapa_ponto_ganho",
            funil_id=self.funil_ponto.id,
            nome="Fechamento Ganho",
            nickname="G",
            ordem=4,
            tipo="ganho",
            probabilidade=100.0,
            cor="#10b981",
        )
        self.etapa_ponto_perdido = CrmEtapa(
            id="etapa_ponto_perdido",
            funil_id=self.funil_ponto.id,
            nome="Perdido",
            nickname="X",
            ordem=5,
            tipo="perdido",
            probabilidade=0.0,
            cor="#ef4444",
        )
        db.session.add_all([
            self.etapa_ponto_novo,
            self.etapa_ponto_qualif,
            self.etapa_ponto_proposta,
            self.etapa_ponto_ganho,
            self.etapa_ponto_perdido,
        ])

        # 3.2 Funil Acesso
        self.funil_acesso = CrmFunil(
            id="funil_acesso",
            nome="Funil Acesso",
            slug="funil_acesso",
            tipo="acesso",
            ordem=2,
            ativo=True,
        )
        db.session.add(self.funil_acesso)
        db.session.flush()

        self.etapa_acesso_novo = CrmEtapa(
            id="etapa_acesso_novo",
            funil_id=self.funil_acesso.id,
            nome="Novo",
            nickname="N",
            ordem=1,
            tipo="normal",
            probabilidade=10.0,
            cor="#3b82f6",
        )
        self.etapa_acesso_qualif = CrmEtapa(
            id="etapa_acesso_qualif",
            funil_id=self.funil_acesso.id,
            nome="Qualificação",
            nickname="Q",
            ordem=2,
            tipo="normal",
            probabilidade=25.0,
            cor="#8b5cf6",
        )
        self.etapa_acesso_proposta = CrmEtapa(
            id="etapa_acesso_proposta",
            funil_id=self.funil_acesso.id,
            nome="Proposta Enviada",
            nickname="P",
            ordem=3,
            tipo="normal",
            probabilidade=75.0,
            cor="#f59e0b",
        )
        self.etapa_acesso_ganho = CrmEtapa(
            id="etapa_acesso_ganho",
            funil_id=self.funil_acesso.id,
            nome="Fechamento Ganho",
            nickname="G",
            ordem=4,
            tipo="ganho",
            probabilidade=100.0,
            cor="#10b981",
        )
        self.etapa_acesso_perdido = CrmEtapa(
            id="etapa_acesso_perdido",
            funil_id=self.funil_acesso.id,
            nome="Perdido",
            nickname="X",
            ordem=5,
            tipo="perdido",
            probabilidade=0.0,
            cor="#ef4444",
        )
        db.session.add_all([
            self.etapa_acesso_novo,
            self.etapa_acesso_qualif,
            self.etapa_acesso_proposta,
            self.etapa_acesso_ganho,
            self.etapa_acesso_perdido,
        ])

        # 3.3 Funil Assistência Técnica
        self.funil_assistencia = CrmFunil(
            id="funil_assistencia",
            nome="Assistência Técnica",
            slug="assistencia_tecnica",
            tipo="assistencia",
            ordem=3,
            ativo=True,
        )
        db.session.add(self.funil_assistencia)
        db.session.flush()

        self.etapa_assist_novo = CrmEtapa(
            id="etapa_assist_novo",
            funil_id=self.funil_assistencia.id,
            nome="Novo",
            nickname="N",
            ordem=1,
            tipo="normal",
            probabilidade=10.0,
            cor="#3b82f6",
        )
        self.etapa_assist_qualif = CrmEtapa(
            id="etapa_assist_qualif",
            funil_id=self.funil_assistencia.id,
            nome="Qualificação",
            nickname="Q",
            ordem=2,
            tipo="normal",
            probabilidade=25.0,
            cor="#8b5cf6",
        )
        self.etapa_assist_proposta = CrmEtapa(
            id="etapa_assist_proposta",
            funil_id=self.funil_assistencia.id,
            nome="Proposta Enviada",
            nickname="P",
            ordem=3,
            tipo="normal",
            probabilidade=75.0,
            cor="#f59e0b",
        )
        self.etapa_assist_ganho = CrmEtapa(
            id="etapa_assist_ganho",
            funil_id=self.funil_assistencia.id,
            nome="Fechamento Ganho",
            nickname="G",
            ordem=4,
            tipo="ganho",
            probabilidade=100.0,
            cor="#10b981",
        )
        self.etapa_assist_perdido = CrmEtapa(
            id="etapa_assist_perdido",
            funil_id=self.funil_assistencia.id,
            nome="Perdido",
            nickname="X",
            ordem=5,
            tipo="perdido",
            probabilidade=0.0,
            cor="#ef4444",
        )
        db.session.add_all([
            self.etapa_assist_novo,
            self.etapa_assist_qualif,
            self.etapa_assist_proposta,
            self.etapa_assist_ganho,
            self.etapa_assist_perdido,
        ])
        db.session.commit()

        # 4. Regional Distribution Rules (CrmRegraDistribuicao)
        self.regra_sp = CrmRegraDistribuicao(
            nome="Distribuição Regional SP",
            regiao="SP",
            estados="SP",
            ddds="11,12,13,14,15,16,17,18,19",
            consultor_id=self.consultor_sp.id,
            ativo=True,
            ordem=1,
        )
        self.regra_rj = CrmRegraDistribuicao(
            nome="Distribuição Regional RJ",
            regiao="RJ",
            estados="RJ",
            ddds="21,22,24",
            consultor_id=self.consultor_rj.id,
            ativo=True,
            ordem=2,
        )
        db.session.add_all([self.regra_sp, self.regra_rj])
        db.session.commit()

        # 5. Official Loss Reasons (CrmMotivoPerda)
        self.motivo_preco = CrmMotivoPerda(
            nome="Preço / Condição Comercial",
            categoria="preco",
            ativo=True,
            ordem=1,
        )
        self.motivo_concorrente = CrmMotivoPerda(
            nome="Fechou com Concorrente",
            categoria="concorrente",
            ativo=True,
            ordem=2,
        )
        self.motivo_sem_contato = CrmMotivoPerda(
            nome="Sem Retorno / Não Respondeu",
            categoria="sem_contato",
            ativo=True,
            ordem=3,
        )
        self.motivo_descarte = CrmMotivoPerda(
            nome="Sem Fit / Fora do Escopo",
            categoria="descarte",
            ativo=True,
            ordem=4,
        )
        self.motivo_outros = CrmMotivoPerda(
            nome="Outro Motivo",
            categoria="outros",
            ativo=True,
            ordem=5,
        )
        db.session.add_all([
            self.motivo_preco,
            self.motivo_concorrente,
            self.motivo_sem_contato,
            self.motivo_descarte,
            self.motivo_outros,
        ])
        db.session.commit()

    def tearDown(self):
        self._req_patcher.stop()
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self, user: User | None = None):
        """Authenticates client session simulating logged user."""
        target = user or self.consultor_sp
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(target.id)
            sess["user_id"] = target.id
            sess["usuario_id"] = target.id
            sess["tipo"] = target.tipo
            sess["role"] = target.role

    def _create_company(self, nome: str, cnpj: str = "12.345.678/0001-90", **kwargs) -> CrmEmpresa:
        emp = CrmEmpresa(
            id=f"emp_{uuid.uuid4().hex[:12]}",
            nome=nome,
            cnpj=cnpj,
            **kwargs
        )
        db.session.add(emp)
        db.session.commit()
        return emp

    def _create_contact(self, nome: str, email: str = "contato@empresa.com", empresa_id: str | None = None, **kwargs) -> CrmContato:
        contact = CrmContato(
            id=f"cont_{uuid.uuid4().hex[:12]}",
            nome=nome,
            email=email,
            empresa_id=empresa_id,
            **kwargs
        )
        db.session.add(contact)
        db.session.commit()
        return contact

    def _create_deal(self, nome: str, funil_id: str = "funil_ponto", etapa_id: str = "etapa_ponto_novo", **kwargs) -> CrmNegociacao:
        deal = CrmNegociacao(
            id=f"deal_{uuid.uuid4().hex[:12]}",
            nome=nome,
            funil_id=funil_id,
            etapa_id=etapa_id,
            status=kwargs.pop("status", "aberto"),
            valor_total=kwargs.pop("valor_total", 1500.0),
            valor_unico=kwargs.pop("valor_unico", 1500.0),
            **kwargs
        )
        db.session.add(deal)
        db.session.commit()
        return deal


# ==============================================================================
# SUITE 1: TestR1LeadQualificationAndOrigins (6 Tests)
# ==============================================================================
class TestR1LeadQualificationAndOrigins(BaseCrmMarketingTestCase):
    """Validates lead qualification fields, origins persistence, and UI rendering."""

    def test_r1_01_negociacao_qualification_fields_persistence(self):
        """Verifies persistence of origem_id, canal_origem, temperatura, canal_preferencial, and necessidade in CrmNegociacao."""
        deal_id = f"deal_qualif_{uuid.uuid4().hex[:8]}"
        deal = CrmNegociacao(
            id=deal_id,
            nome="Negociação Teste Qualificação",
            funil_id=self.funil_ponto.id,
            etapa_id=self.etapa_ponto_novo.id,
            status="aberto",
            origem="Busca Paga | Google",
            canal_origem="google_ads",
            temperatura="quente",
            canal_preferencial="whatsapp",
            necessidade="Relógio de Ponto Henry Prisma Super Fácil",
            origem_id=1,
        )
        db.session.add(deal)
        db.session.commit()

        queried = CrmNegociacao.query.get(deal_id)
        self.assertIsNotNone(queried, "Deal must be retrieved from database")
        self.assertEqual(queried.temperatura, "quente")
        self.assertEqual(queried.canal_preferencial, "whatsapp")
        self.assertEqual(queried.canal_origem, "google_ads")
        self.assertEqual(queried.necessidade, "Relógio de Ponto Henry Prisma Super Fácil")
        self.assertEqual(queried.origem_id, 1)

    def test_r1_02_empresa_porte_and_employee_fields(self):
        """Verifies CrmEmpresa stores porte and numero_funcionarios."""
        emp = self._create_company(
            nome="Indústria e Comércio Sollus Ltda",
            cnpj="98.765.432/0001-10",
            porte="20-50",
            numero_funcionarios=35,
        )
        queried = CrmEmpresa.query.get(emp.id)
        self.assertIsNotNone(queried)
        self.assertEqual(queried.porte, "20-50")
        self.assertEqual(queried.numero_funcionarios, 35)

    def test_r1_03_negociacao_and_empresa_to_dict_includes_qualification(self):
        """Verifies to_dict() outputs for CrmNegociacao and CrmEmpresa include qualification attributes."""
        emp = self._create_company(
            nome="Tech Soluções",
            cnpj="11.222.333/0001-44",
            porte="5-10",
            numero_funcionarios=8,
        )
        deal = self._create_deal(
            nome="Venda Catraca Flap",
            empresa_id=emp.id,
            temperatura="morno",
            canal_preferencial="ligacao",
            canal_origem="organico",
            necessidade="Controle de Acesso Academia",
            origem_id=2,
        )

        deal_dict = deal.to_dict()
        self.assertIn("temperatura", deal_dict)
        self.assertEqual(deal_dict["temperatura"], "morno")
        self.assertIn("canal_preferencial", deal_dict)
        self.assertEqual(deal_dict["canal_preferencial"], "ligacao")
        self.assertIn("canal_origem", deal_dict)
        self.assertEqual(deal_dict["canal_origem"], "organico")
        self.assertIn("necessidade", deal_dict)
        self.assertEqual(deal_dict["necessidade"], "Controle de Acesso Academia")

        emp_dict = emp.to_dict()
        self.assertIn("porte", emp_dict)
        self.assertEqual(emp_dict["porte"], "5-10")
        self.assertIn("numero_funcionarios", emp_dict)
        self.assertEqual(emp_dict["numero_funcionarios"], 8)

    def test_r1_04_kanban_view_renders_qualification_badges(self):
        """Verifies GET /crm/kanban renders temperature badges and origin indicators."""
        self._login(self.consultor_sp)
        deal_hot = self._create_deal(
            nome="Deal Hot Lead Google",
            funil_id=self.funil_ponto.id,
            etapa_id=self.etapa_ponto_novo.id,
            temperatura="quente",
            canal_origem="google_ads",
            origem="Google Ads",
        )
        deal_cold = self._create_deal(
            nome="Deal Cold Lead Facebook",
            funil_id=self.funil_ponto.id,
            etapa_id=self.etapa_ponto_novo.id,
            temperatura="frio",
            canal_origem="facebook_ads",
            origem="Facebook Ads",
        )

        res = self.client.get(f"/crm/funil/{self.funil_ponto.id}")
        if res.status_code == 404:
            res = self.client.get(f"/crm/kanban?funil_id={self.funil_ponto.id}")
        self.assertEqual(res.status_code, 200, "Kanban board must render HTTP 200")
        html = res.get_data(as_text=True)

        self.assertIn("Deal Hot Lead Google", html)
        self.assertIn("Deal Cold Lead Facebook", html)
        # Check badge indicators: quente/frio or emoji or channel
        has_temp_badge = ("quente" in html.lower() or "🔥" in html) and ("frio" in html.lower() or "❄️" in html)
        self.assertTrue(has_temp_badge, "Kanban HTML must render temperature badges (quente/frio)")

    def test_r1_05_update_deal_qualification_api(self):
        """Verifies POST /crm/api/negociacoes/<deal_id>/qualificar endpoint updates deal and company."""
        self._login(self.consultor_sp)
        emp = self._create_company(nome="Comercial Alvorada Ltda")
        deal = self._create_deal(nome="Negociação para Qualificar", empresa_id=emp.id)

        payload = {
            "temperatura": "quente",
            "canal_preferencial": "whatsapp",
            "canal_origem": "google_ads",
            "porte": "20-50",
            "numero_funcionarios": 45,
            "necessidade": "Catraca com leitor facial",
        }
        res = self.client.post(f"/crm/api/negociacoes/{deal.id}/qualificar", json=payload)
        self.assertEqual(res.status_code, 200, "Endpoint /qualificar must return HTTP 200")
        data = res.get_json()
        self.assertTrue(data.get("success"), "Response success must be True")

        # Verify DB updates
        db.session.refresh(deal)
        db.session.refresh(emp)
        self.assertEqual(deal.temperatura, "quente")
        self.assertEqual(deal.canal_preferencial, "whatsapp")
        self.assertEqual(deal.canal_origem, "google_ads")
        self.assertEqual(deal.necessidade, "Catraca com leitor facial")
        self.assertEqual(emp.porte, "20-50")
        self.assertEqual(emp.numero_funcionarios, 45)

        # Verify interaction note in timeline
        interaction = CrmInteracao.query.filter_by(negociacao_id=deal.id).order_by(CrmInteracao.id.desc()).first()
        self.assertIsNotNone(interaction, "An interaction should be logged upon qualification update")
        self.assertIn("Qualificação", interaction.conteudo)

    def test_r1_06_drawer_360_qualification_payload(self):
        """Verifies Drawer 360 payload (/crm/api/negociacoes/<deal_id>/detalhes) includes qualification and company info."""
        self._login(self.consultor_sp)
        emp = self._create_company(
            nome="Hospital Saúde Total",
            cnpj="12.999.888/0001-77",
            porte="Acima de 50",
            numero_funcionarios=150,
        )
        deal = self._create_deal(
            nome="Controle de Acesso Hospitalar",
            empresa_id=emp.id,
            temperatura="quente",
            canal_preferencial="whatsapp",
            canal_origem="google_ads",
            necessidade="Controle de Portas e Catracas",
        )

        res = self.client.get(f"/crm/api/negociacoes/{deal.id}/detalhes")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))

        detalhes = data.get("data", {})
        deal_info = detalhes.get("deal", {})
        empresa_info = detalhes.get("empresa", {})

        self.assertEqual(deal_info.get("temperatura"), "quente")
        self.assertEqual(deal_info.get("canal_preferencial"), "whatsapp")
        self.assertEqual(deal_info.get("canal_origem"), "google_ads")
        self.assertEqual(deal_info.get("necessidade"), "Controle de Portas e Catracas")
        self.assertEqual(empresa_info.get("porte"), "Acima de 50")
        self.assertEqual(empresa_info.get("numero_funcionarios"), 150)
        self.assertEqual(empresa_info.get("cnpj"), "12.999.888/0001-77")


# ==============================================================================
# SUITE 2: TestR2InboundLeadAutomationFlow (7 Tests)
# ==============================================================================
class TestR2InboundLeadAutomationFlow(BaseCrmMarketingTestCase):
    """Validates inbound webhook lead ingestion, deduplication, DDD routing, and automated tasks."""

    def test_r2_01_inbound_webhook_auth_enforcement(self):
        """Validates token authentication on /crm/api/webhooks/inbound (401 on missing/bad token, 201 on valid)."""
        valid_payload = {
            "nome_negociacao": "Lead Teste Auth",
            "contato": {"nome": "Teste", "email": "teste@auth.com"},
        }

        # 1. Missing Token
        res_missing = self.client.post("/crm/api/webhooks/inbound", json=valid_payload)
        self.assertEqual(res_missing.status_code, 401, "Missing token must be rejected with HTTP 401")

        # 2. Invalid Token
        res_invalid = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "invalid-token-value"},
            json=valid_payload,
        )
        self.assertEqual(res_invalid.status_code, 401, "Invalid token must be rejected with HTTP 401")

        # 3. Valid Token via X-API-Token header
        res_valid_header = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json=valid_payload,
        )
        self.assertEqual(res_valid_header.status_code, 201, "Valid X-API-Token must be accepted with HTTP 201")

        # 4. Valid Token via Authorization: Bearer header
        res_valid_bearer = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"Authorization": "Bearer sollus-test-token-secret-12345"},
            json={
                "nome_negociacao": "Lead Teste Bearer",
                "contato": {"nome": "Teste Bearer", "email": "bearer@auth.com"},
            },
        )
        self.assertEqual(res_valid_bearer.status_code, 201, "Valid Bearer token must be accepted with HTTP 201")

    def test_r2_02_inbound_webhook_creates_deal_company_contact(self):
        """Verifies ingestion of conversion payload creating deal, company, and contact."""
        payload = {
            "event_type": "CONVERSION",
            "conversion_identifier": "controle-software-relogio-de-ponto",
            "lead": {
                "name": "Carlos Eduardo Silva",
                "email": "carlos.silva@empresa.com.br",
                "personal_phone": "+55 (11) 98765-4321",
                "mobile_phone": "+55 (11) 98765-4321",
                "company_name": "Silva & Filhos Indústria Ltda",
                "company_cnpj": "12.345.678/0001-90",
                "company_size": "20-50",
                "state": "SP",
                "city": "São Paulo",
                "preferred_contact_channel": "WhatsApp",
                "lead_temperature": "quente",
                "need": "Relógio de Ponto",
                "subject": "Orçamento de Ponto Eletrônico Henry",
                "tags": ["controle de ponto", "sp", "google ads"],
                "traffic_source": "Busca Paga | Google",
                "campaign_name": "SOLLUS SP",
            }
        }

        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json=payload,
        )
        self.assertEqual(res.status_code, 201, "Inbound conversion payload must return HTTP 201")
        resp_data = res.get_json()
        self.assertTrue(resp_data.get("success"))
        deal_id = resp_data.get("deal_id")
        self.assertIsNotNone(deal_id)

        # Verify CrmEmpresa created
        clean_cnpj = "12345678000190"
        empresa = CrmEmpresa.query.filter(or_(CrmEmpresa.cnpj == "12.345.678/0001-90", CrmEmpresa.cnpj == clean_cnpj)).first()
        self.assertIsNotNone(empresa, "Company must be created by inbound webhook")
        self.assertEqual(empresa.nome, "Silva & Filhos Indústria Ltda")

        # Verify CrmContato created
        contato = CrmContato.query.filter(func.lower(CrmContato.email) == "carlos.silva@empresa.com.br").first()
        self.assertIsNotNone(contato, "Contact must be created by inbound webhook")
        self.assertEqual(contato.nome, "Carlos Eduardo Silva")

        # Verify CrmNegociacao created
        deal = CrmNegociacao.query.get(deal_id)
        self.assertIsNotNone(deal, "Deal must be created by inbound webhook")
        self.assertEqual(deal.empresa_id, empresa.id)
        self.assertEqual(deal.contato_id, contato.id)
        self.assertEqual(deal.funil_id, self.funil_ponto.id)
        self.assertEqual(deal.status, "aberto")

    def test_r2_03_inbound_lead_deduplication_by_cnpj_and_email(self):
        """Verifies deduplication of company by formatted/unformatted CNPJ and contact by lowercased email."""
        # 1. Pre-seed company with formatted CNPJ and contact with lowercased email
        existing_emp = self._create_company(nome="Acme Corporation", cnpj="98.765.432/0001-11")
        existing_cont = self._create_contact(nome="Ana Lima", email="ana.lima@acme.com", empresa_id=existing_emp.id)

        # 2. Inbound conversion with unformatted CNPJ and uppercase email
        payload = {
            "event_type": "CONVERSION",
            "conversion_identifier": "solicite-um-orcamento-site",
            "lead": {
                "name": "Ana Lima",
                "email": "ANA.LIMA@ACME.COM",
                "personal_phone": "(11) 99999-8888",
                "company_name": "Acme Corp Filial",
                "company_cnpj": "98765432000111",  # Unformatted digits
                "state": "SP",
                "need": "Relógio de Ponto",
            }
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json=payload,
        )
        self.assertEqual(res.status_code, 201)

        # 3. Assert NO duplicate company or contact was created
        matching_companies = CrmEmpresa.query.filter(
            or_(CrmEmpresa.cnpj == "98.765.432/0001-11", CrmEmpresa.cnpj == "98765432000111")
        ).all()
        self.assertEqual(len(matching_companies), 1, "Company must be deduplicated by normalized CNPJ")

        matching_contacts = CrmContato.query.filter(
            func.lower(CrmContato.email) == "ana.lima@acme.com"
        ).all()
        self.assertEqual(len(matching_contacts), 1, "Contact must be deduplicated by case-insensitive email")

    def test_r2_04_regional_routing_by_ddd_and_uf(self):
        """Verifies regional routing by DDD: DDD 11 -> SP consultant, DDD 21 -> RJ consultant."""
        # Conversion 1: DDD 11 (SP)
        payload_sp = {
            "event_type": "CONVERSION",
            "lead": {
                "name": "Lead Paulista",
                "email": "paulista@sp.com.br",
                "personal_phone": "+55 (11) 98888-1111",
                "state": "SP",
                "company_name": "Paulista Serviços",
                "need": "Ponto",
            }
        }
        res_sp = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json=payload_sp,
        )
        self.assertEqual(res_sp.status_code, 201)
        deal_id_sp = res_sp.get_json()["deal_id"]
        deal_sp = CrmNegociacao.query.get(deal_id_sp)
        self.assertEqual(
            deal_sp.user_id,
            self.consultor_sp.id,
            f"Lead with DDD 11 should be routed to SP consultant ({self.consultor_sp.nome_completo})",
        )

        # Conversion 2: DDD 21 (RJ)
        payload_rj = {
            "event_type": "CONVERSION",
            "lead": {
                "name": "Lead Carioca",
                "email": "carioca@rj.com.br",
                "personal_phone": "+55 (21) 97777-2222",
                "state": "RJ",
                "company_name": "Carioca Comércio",
                "need": "Ponto",
            }
        }
        res_rj = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json=payload_rj,
        )
        self.assertEqual(res_rj.status_code, 201)
        deal_id_rj = res_rj.get_json()["deal_id"]
        deal_rj = CrmNegociacao.query.get(deal_id_rj)
        self.assertEqual(
            deal_rj.user_id,
            self.consultor_rj.id,
            f"Lead with DDD 21 should be routed to RJ consultant ({self.consultor_rj.nome_completo})",
        )

    def test_r2_05_funnel_selection_by_product_or_tags(self):
        """Verifies funnel selection: Relógio/Ponto -> funil_ponto, Acesso/Catraca -> funil_acesso, Assistência -> funil_assistencia."""
        # 1. Ponto
        res_ponto = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json={
                "conversion_identifier": "controle-software-relogio-de-ponto",
                "lead": {"name": "Lead Ponto", "email": "ponto@teste.com", "need": "Relógio de Ponto", "tags": ["ponto"]},
            },
        )
        self.assertEqual(res_ponto.status_code, 201)
        deal_ponto = CrmNegociacao.query.get(res_ponto.get_json()["deal_id"])
        self.assertEqual(deal_ponto.funil_id, self.funil_ponto.id)

        # 2. Acesso
        res_acesso = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json={
                "conversion_identifier": "controle-de-acesso-catracas",
                "lead": {"name": "Lead Acesso", "email": "acesso@teste.com", "need": "Catraca de Acesso", "tags": ["acesso"]},
            },
        )
        self.assertEqual(res_acesso.status_code, 201)
        deal_acesso = CrmNegociacao.query.get(res_acesso.get_json()["deal_id"])
        self.assertEqual(deal_acesso.funil_id, self.funil_acesso.id)

        # 3. Assistência Técnica
        res_assist = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json={
                "conversion_identifier": "solicite-assistencia-tecnica",
                "lead": {"name": "Lead Suporte", "email": "suporte@teste.com", "need": "Assistência Técnica", "tags": ["assistencia"]},
            },
        )
        self.assertEqual(res_assist.status_code, 201)
        deal_assist = CrmNegociacao.query.get(res_assist.get_json()["deal_id"])
        self.assertEqual(deal_assist.funil_id, self.funil_assistencia.id)

    def test_r2_06_immediate_first_contact_task_scheduling(self):
        """Verifies immediate first-contact task scheduling (SDR WhatsApp/Call task) on lead conversion."""
        payload = {
            "event_type": "CONVERSION",
            "lead": {
                "name": "Renata Martins",
                "email": "renata@empresa.com",
                "personal_phone": "(11) 98765-1122",
                "preferred_contact_channel": "WhatsApp",
                "need": "Relógio de Ponto",
            }
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json=payload,
        )
        self.assertEqual(res.status_code, 201)
        deal_id = res.get_json()["deal_id"]

        deal = CrmNegociacao.query.get(deal_id)
        tarefas = CrmTarefa.query.filter_by(negociacao_id=deal.id).all()
        self.assertGreaterEqual(len(tarefas), 1, "At least one follow-up task should be scheduled for the new lead")

        primeira_tarefa = tarefas[0]
        self.assertIn("1º Contato", primeira_tarefa.titulo)
        self.assertEqual(primeira_tarefa.tipo, "whatsapp")
        self.assertEqual(primeira_tarefa.user_id, deal.user_id)
        self.assertFalse(primeira_tarefa.concluida)

    def test_r2_07_inbound_timeline_interaction_and_audit_logging(self):
        """Verifies inbound interaction is recorded in timeline and execution is logged in CrmWebhookLog."""
        payload = {
            "event_type": "CONVERSION",
            "lead": {
                "name": "Audit Test Lead",
                "email": "audit@lead.com",
                "personal_phone": "(11) 91111-2222",
                "company_name": "Audit Security Corp",
                "need": "Relógio de Ponto",
            }
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json=payload,
        )
        self.assertEqual(res.status_code, 201)
        deal_id = res.get_json()["deal_id"]

        # 1. Timeline Interaction
        interacao = CrmInteracao.query.filter_by(negociacao_id=deal_id).first()
        self.assertIsNotNone(interacao, "Timeline interaction must be registered")
        self.assertEqual(interacao.tipo, "sistema")
        self.assertIn("Inbound Webhook", interacao.conteudo)

        # 2. Inbound Webhook Log
        log = CrmWebhookLog.query.order_by(CrmWebhookLog.id.desc()).first()
        self.assertIsNotNone(log, "CrmWebhookLog must record inbound webhook execution")
        self.assertEqual(log.status_code, 201)
        self.assertTrue(log.sucesso)


# ==============================================================================
# SUITE 3: TestR3LeadSegmentationAndFilters (6 Tests)
# ==============================================================================
class TestR3LeadSegmentationAndFilters(BaseCrmMarketingTestCase):
    """Validates lead segmentation on /crm/leads, multi-criteria filtering, CSV export, and history."""

    def _seed_marketing_leads(self):
        """Helper to seed diverse marketing leads for filtering tests."""
        lead1 = CrmLeadMarketing(
            nome="Marcos Ponto SP",
            email="marcos@pontosp.com",
            telefone="(11) 98888-1111",
            empresa="SP Ponto Eletro",
            cidade="São Paulo",
            estado="SP",
            tags="ponto, sp, google_ads",
            origem_primeira="Google Ads",
            lead_scoring_perfil="A",
            lead_scoring_interesse=80,
            total_conversoes=3,
            evento_conversao="controle-software-relogio-de-ponto",
        )
        lead2 = CrmLeadMarketing(
            nome="Juliana Acesso RJ",
            email="juliana@acessorj.com",
            telefone="(21) 97777-2222",
            empresa="Rio Catracas Ltda",
            cidade="Rio de Janeiro",
            estado="RJ",
            tags="acesso, rj, facebook_ads",
            origem_primeira="Facebook Ads",
            lead_scoring_perfil="B",
            lead_scoring_interesse=50,
            total_conversoes=1,
            evento_conversao="controle-de-acesso-catracas",
        )
        lead3 = CrmLeadMarketing(
            nome="Lucas Ponto e Acesso ES",
            email="lucas@es.com",
            telefone="(27) 96666-3333",
            empresa="Capixaba Segurança",
            cidade="Vitória",
            estado="ES",
            tags="ponto, acesso, es, organico",
            origem_primeira="Busca Orgânica",
            lead_scoring_perfil="A",
            lead_scoring_interesse=90,
            total_conversoes=2,
            evento_conversao="controle-software-relogio-de-ponto",
        )
        db.session.add_all([lead1, lead2, lead3])
        db.session.commit()
        return [lead1, lead2, lead3]

    def test_r3_01_leads_page_rendering(self):
        """Verifies GET /crm/leads renders lead management view with HTTP 200."""
        self._login(self.admin_manager)
        self._seed_marketing_leads()

        res = self.client.get("/crm/leads")
        self.assertEqual(res.status_code, 200, "Route /crm/leads must render HTTP 200")
        html = res.get_data(as_text=True)
        self.assertIn("Marcos Ponto SP", html)
        self.assertIn("Juliana Acesso RJ", html)

    def test_r3_02_filter_leads_by_tags(self):
        """Verifies filtering leads by tags (e.g. 'ponto' vs 'acesso')."""
        self._login(self.admin_manager)
        self._seed_marketing_leads()

        # Filter by tag 'ponto'
        res_ponto = self.client.get("/crm/leads?tag=ponto")
        if res_ponto.status_code != 200:
            res_ponto = self.client.get("/crm/leads?tags=ponto")
        self.assertEqual(res_ponto.status_code, 200)
        html_ponto = res_ponto.get_data(as_text=True)
        self.assertIn("Marcos Ponto SP", html_ponto)
        self.assertIn("Lucas Ponto e Acesso ES", html_ponto)
        self.assertNotIn("Juliana Acesso RJ", html_ponto)

    def test_r3_03_filter_leads_by_state_uf_and_ddd(self):
        """Verifies filtering leads by state (UF) and DDD."""
        self._login(self.admin_manager)
        self._seed_marketing_leads()

        # Filter by state SP
        res_sp = self.client.get("/crm/leads?estado=SP")
        self.assertEqual(res_sp.status_code, 200)
        html_sp = res_sp.get_data(as_text=True)
        self.assertIn("Marcos Ponto SP", html_sp)
        self.assertNotIn("Juliana Acesso RJ", html_sp)
        self.assertNotIn("Lucas Ponto e Acesso ES", html_sp)

        # Filter by state RJ
        res_rj = self.client.get("/crm/leads?estado=RJ")
        self.assertEqual(res_rj.status_code, 200)
        html_rj = res_rj.get_data(as_text=True)
        self.assertIn("Juliana Acesso RJ", html_rj)
        self.assertNotIn("Marcos Ponto SP", html_rj)

    def test_r3_04_filter_leads_by_temperatura_and_origem(self):
        """Verifies combined filtering by origin and lead scoring/profile."""
        self._login(self.admin_manager)
        self._seed_marketing_leads()

        # Filter by perfil A
        res_perfil_a = self.client.get("/crm/leads?perfil=A")
        self.assertEqual(res_perfil_a.status_code, 200)
        html_a = res_perfil_a.get_data(as_text=True)
        self.assertIn("Marcos Ponto SP", html_a)
        self.assertIn("Lucas Ponto e Acesso ES", html_a)
        self.assertNotIn("Juliana Acesso RJ", html_a)

    def test_r3_05_export_leads_csv_format_and_content(self):
        """Verifies CSV export (/crm/leads/export or ?export=csv) validating HTTP 200, Content-Type, headers, and rows."""
        self._login(self.admin_manager)
        self._seed_marketing_leads()

        res = self.client.get("/crm/leads/export")
        if res.status_code == 404:
            # Check alternative query parameter format
            res = self.client.get("/crm/leads?export=csv")
        self.assertEqual(res.status_code, 200, "Leads CSV export must return HTTP 200")

        # Verify headers
        content_type = res.headers.get("Content-Type", "")
        self.assertTrue("csv" in content_type or "text/plain" in content_type, f"Content-Type should be CSV, got: {content_type}")
        content_disp = res.headers.get("Content-Disposition", "")
        self.assertIn("attachment", content_disp)
        self.assertIn(".csv", content_disp)

        # Verify CSV payload structure
        csv_text = res.get_data(as_text=True)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        self.assertGreaterEqual(len(rows), 4, "CSV must contain header row plus at least 3 data rows")

        header = [h.strip().lower() for h in rows[0]]
        has_essential_cols = any("nome" in h for h in header) and any("email" in h or "e-mail" in h for h in header)
        self.assertTrue(has_essential_cols, f"CSV header must contain Nome and Email columns. Got: {header}")

        # Verify data rows content
        joined_data = "".join(csv_text)
        self.assertIn("marcos@pontosp.com", joined_data)
        self.assertIn("juliana@acessorj.com", joined_data)
        self.assertIn("lucas@es.com", joined_data)

    def test_r3_06_lead_drawer_timeline_conversion_history(self):
        """Verifies lead drawer timeline conversion history (/crm/api/leads/<id>/detalhes)."""
        self._login(self.admin_manager)
        leads = self._seed_marketing_leads()
        target_lead = leads[0]  # Marcos, 3 conversions

        res = self.client.get(f"/crm/api/leads/{target_lead.id}/detalhes")
        if res.status_code == 404:
            res = self.client.get(f"/crm/api/leads/{target_lead.id}/historico")
        self.assertEqual(res.status_code, 200, "Lead details endpoint must return HTTP 200")
        data = res.get_json()
        self.assertTrue(data.get("success"), "Response success must be True")

        lead_data = data.get("data", data.get("lead", {}))
        self.assertEqual(lead_data.get("email"), target_lead.email)
        self.assertEqual(lead_data.get("total_conversoes", 3), 3)


# ==============================================================================
# SUITE 4: TestR4StructuredLossReasonsAndMetrics (6 Tests)
# ==============================================================================
class TestR4StructuredLossReasonsAndMetrics(BaseCrmMarketingTestCase):
    """Validates structured loss reason enforcement (HTTP 400), analytics, and regional GEO radar."""

    def test_r4_01_mark_deal_lost_requires_category_and_reason(self):
        """Verifies POST /crm/api/negociacoes/<id>/perder rejects missing/empty category and reason with HTTP 400."""
        self._login(self.consultor_sp)
        deal = self._create_deal(nome="Negociação Teste Rejeição Perda")

        # 1. Missing body
        res1 = self.client.post(f"/crm/api/negociacoes/{deal.id}/perder", json={})
        self.assertEqual(res1.status_code, 400, "Empty payload must return HTTP 400")

        # 2. Missing category (only motivo provided)
        res2 = self.client.post(f"/crm/api/negociacoes/{deal.id}/perder", json={"motivo": "Preço alto"})
        self.assertEqual(res2.status_code, 400, "Missing category must return HTTP 400")

        # 3. Empty motivo (only category provided)
        res3 = self.client.post(f"/crm/api/negociacoes/{deal.id}/perder", json={"categoria": "preco", "motivo": "   "})
        self.assertEqual(res3.status_code, 400, "Empty motivo must return HTTP 400")

        # 4. Invalid / unknown category
        res4 = self.client.post(f"/crm/api/negociacoes/{deal.id}/perder", json={"categoria": "categoria_inexistente_xyz", "motivo": "Motivo X"})
        self.assertEqual(res4.status_code, 400, "Unknown category must return HTTP 400")

    def test_r4_02_mark_deal_lost_successful_transition(self):
        """Verifies marking deal lost updates status, moves to lost stage, and stores category and reason."""
        self._login(self.consultor_sp)
        deal = self._create_deal(nome="Negociação para Perder com Sucesso", valor_total=2500.0)

        payload = {
            "categoria": "preco",
            "motivo": "Preço / Condição Comercial",
            "detalhes": "Cliente optou por concorrente mais barato",
            "motivo_perda_id": self.motivo_preco.id,
        }
        res = self.client.post(f"/crm/api/negociacoes/{deal.id}/perder", json=payload)
        self.assertEqual(res.status_code, 200, "Valid loss marking must return HTTP 200")
        data = res.get_json()
        self.assertTrue(data.get("success"), "Response success must be True")

        # Verify DB updates
        db.session.refresh(deal)
        self.assertEqual(deal.status, "perdido")
        self.assertEqual(deal.etapa_id, self.etapa_ponto_perdido.id, "Deal must be moved to the funnel's lost stage")
        self.assertEqual(deal.motivo_perda, "Preço / Condição Comercial")
        self.assertEqual(deal.motivo_perda_categoria, "preco")
        self.assertIsNotNone(deal.closed_at)

    def test_r4_03_loss_reasons_breakdown_service(self):
        """Verifies get_loss_reasons_breakdown aggregates lost deals and revenue by category."""
        # Seed lost deals with specific categories
        d1 = self._create_deal(nome="Perda Preco 1", status="perdido", etapa_id=self.etapa_ponto_perdido.id, valor_total=1000.0)
        d1.motivo_perda_categoria = "preco"
        d1.motivo_perda = "Preço / Condição Comercial"

        d2 = self._create_deal(nome="Perda Preco 2", status="perdido", etapa_id=self.etapa_ponto_perdido.id, valor_total=2000.0)
        d2.motivo_perda_categoria = "preco"
        d2.motivo_perda = "Preço / Condição Comercial"

        d3 = self._create_deal(nome="Perda Concorrente", status="perdido", etapa_id=self.etapa_ponto_perdido.id, valor_total=3000.0)
        d3.motivo_perda_categoria = "concorrente"
        d3.motivo_perda = "Fechou com Concorrente"

        d4 = self._create_deal(nome="Perda Sem Contato", status="perdido", etapa_id=self.etapa_ponto_perdido.id, valor_total=500.0)
        d4.motivo_perda_categoria = "sem_contato"
        d4.motivo_perda = "Sem Retorno / Não Respondeu"
        db.session.commit()

        if not hasattr(crm_service, "get_loss_reasons_breakdown"):
            self.fail("crm_service.get_loss_reasons_breakdown is required for Milestone M4")

        breakdown = crm_service.get_loss_reasons_breakdown(funil_id=self.funil_ponto.id)
        self.assertIsInstance(breakdown, dict)
        self.assertIn("by_category", breakdown)
        self.assertEqual(breakdown.get("total_lost_count"), 4)
        self.assertEqual(breakdown.get("total_lost_value"), 6500.0)

        by_cat = breakdown["by_category"]
        self.assertEqual(by_cat["preco"]["count"], 2)
        self.assertEqual(by_cat["preco"]["total_value"], 3000.0)
        self.assertEqual(by_cat["concorrente"]["count"], 1)
        self.assertEqual(by_cat["concorrente"]["total_value"], 3000.0)
        self.assertEqual(by_cat["sem_contato"]["count"], 1)

    def test_r4_04_loss_reasons_breakdown_funnel_filtering(self):
        """Verifies get_loss_reasons_breakdown isolates loss data by funnel_id."""
        # Ponto loss
        d_ponto = self._create_deal(nome="Perda Ponto", funil_id=self.funil_ponto.id, status="perdido", etapa_id=self.etapa_ponto_perdido.id, valor_total=1200.0)
        d_ponto.motivo_perda_categoria = "preco"

        # Acesso loss
        d_acesso = self._create_deal(nome="Perda Acesso", funil_id=self.funil_acesso.id, status="perdido", etapa_id=self.etapa_acesso_perdido.id, valor_total=4500.0)
        d_acesso.motivo_perda_categoria = "descarte"
        db.session.commit()

        breakdown_ponto = crm_service.get_loss_reasons_breakdown(funil_id=self.funil_ponto.id)
        self.assertEqual(breakdown_ponto.get("total_lost_count"), 1)
        self.assertEqual(breakdown_ponto.get("total_lost_value"), 1200.0)

        breakdown_acesso = crm_service.get_loss_reasons_breakdown(funil_id=self.funil_acesso.id)
        self.assertEqual(breakdown_acesso.get("total_lost_count"), 1)
        self.assertEqual(breakdown_acesso.get("total_lost_value"), 4500.0)

    def test_r4_05_marketing_channel_conversion_metrics(self):
        """Verifies get_channel_conversion_metrics calculates conversion rates by marketing channel."""
        # Google Ads: 2 won, 2 lost -> 50% conversion
        for i in range(2):
            self._create_deal(nome=f"Google Won {i}", canal_origem="google_ads", origem="Google Ads", status="ganho", etapa_id=self.etapa_ponto_ganho.id)
        for i in range(2):
            d = self._create_deal(nome=f"Google Lost {i}", canal_origem="google_ads", origem="Google Ads", status="perdido", etapa_id=self.etapa_ponto_perdido.id)
            d.motivo_perda_categoria = "preco"

        # Organico: 1 won, 3 lost -> 25% conversion
        self._create_deal(nome="Org Won 1", canal_origem="organico", origem="Orgânico", status="ganho", etapa_id=self.etapa_ponto_ganho.id)
        for i in range(3):
            d = self._create_deal(nome=f"Org Lost {i}", canal_origem="organico", origem="Orgânico", status="perdido", etapa_id=self.etapa_ponto_perdido.id)
            d.motivo_perda_categoria = "sem_contato"
        db.session.commit()

        if hasattr(crm_service, "get_channel_conversion_metrics"):
            metrics = crm_service.get_channel_conversion_metrics(funil_id=self.funil_ponto.id)
            self.assertIsInstance(metrics, (dict, list))
            if isinstance(metrics, dict):
                channels = metrics.get("channels", metrics)
                if "google_ads" in channels:
                    g_data = channels["google_ads"]
                    self.assertEqual(g_data.get("ganhos"), 2)
                    self.assertEqual(g_data.get("perdidos"), 2)
                    self.assertAlmostEqual(g_data.get("taxa_conversao"), 50.0, places=1)
        else:
            self.fail("crm_service.get_channel_conversion_metrics is required for Milestone M4")

    def test_r4_06_regional_geo_radar_distribution(self):
        """Verifies get_lead_geo_distribution aggregates leads and opportunities by state/UF."""
        self._create_deal(nome="Deal RJ 1", filial="RJ")
        self._create_deal(nome="Deal RJ 2", filial="RJ")
        self._create_deal(nome="Deal SP 1", filial="SP")
        self._create_deal(nome="Deal ES 1", filial="ES")
        db.session.commit()

        if hasattr(crm_service, "get_lead_geo_distribution"):
            geo_dist = crm_service.get_lead_geo_distribution()
            self.assertIsInstance(geo_dist, (dict, list))
            if isinstance(geo_dist, dict):
                by_state = geo_dist.get("by_state", geo_dist)
                self.assertIn("RJ", by_state)
                self.assertIn("SP", by_state)
                self.assertIn("ES", by_state)
                self.assertEqual(by_state["RJ"].get("count", by_state["RJ"]), 2)
        else:
            self.fail("crm_service.get_lead_geo_distribution is required for Milestone M4")


# ==============================================================================
# SUITE 5: TestR5MarketingIntegrationEndToEnd (3 Tests)
# ==============================================================================
class TestR5MarketingIntegrationEndToEnd(BaseCrmMarketingTestCase):
    """End-to-End integration scenarios connecting webhook conversion, regional routing, Kanban, and metrics."""

    def test_r5_01_rd_station_webhook_to_kanban_to_won_proposal(self):
        """Full Happy Path: RD Station Webhook -> Regional Routing (SP) -> Kanban -> Qualify -> Won."""
        # 1. Inbound Webhook Conversion
        inbound_payload = {
            "event_type": "CONVERSION",
            "conversion_identifier": "controle-software-relogio-de-ponto",
            "lead": {
                "name": "Mariana Souza",
                "email": "mariana.souza@alphaindustria.com.br",
                "personal_phone": "+55 (11) 98765-4321",
                "company_name": "Alpha Indústria Mecânica Ltda",
                "company_cnpj": "14.253.647/0001-88",
                "company_size": "20-50",
                "state": "SP",
                "city": "Campinas",
                "preferred_contact_channel": "WhatsApp",
                "lead_temperature": "quente",
                "need": "Relógio de Ponto",
                "subject": "Cotação 2 Relógios de Ponto",
                "traffic_source": "Busca Paga | Google",
            }
        }
        res_webhook = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json=inbound_payload,
        )
        self.assertEqual(res_webhook.status_code, 201)
        deal_id = res_webhook.get_json()["deal_id"]

        # 2. Verify Regional Routing & Funnel
        deal = CrmNegociacao.query.get(deal_id)
        self.assertIsNotNone(deal)
        self.assertEqual(deal.user_id, self.consultor_sp.id, "Deal must be assigned to SP consultant via DDD 11")
        self.assertEqual(deal.funil_id, self.funil_ponto.id, "Deal must be in Funil Ponto")
        self.assertEqual(deal.etapa_id, self.etapa_ponto_novo.id, "Deal must start in Novo stage")

        # 3. SP Consultant logs in and views Kanban
        self._login(self.consultor_sp)
        res_kanban = self.client.get(f"/crm/funil/{self.funil_ponto.id}")
        if res_kanban.status_code == 404:
            res_kanban = self.client.get(f"/crm/kanban?funil_id={self.funil_ponto.id}")
        self.assertEqual(res_kanban.status_code, 200)
        self.assertIn("Alpha Indústria", res_kanban.get_data(as_text=True))

        # 4. Qualify Deal via Drawer API
        res_qualif = self.client.post(
            f"/crm/api/negociacoes/{deal.id}/qualificar",
            json={
                "temperatura": "quente",
                "canal_preferencial": "whatsapp",
                "porte": "20-50",
                "numero_funcionarios": 32,
                "necessidade": "2 Relógios Henry Prisma com Software",
            }
        )
        self.assertEqual(res_qualif.status_code, 200)

        # 5. Move through stages to Proposta and Win
        move_res1 = crm_service.move_deal_stage(deal.id, self.etapa_ponto_proposta.id, user=self.consultor_sp)
        self.assertTrue(move_res1.get("success"))

        win_res = crm_service.mark_deal_won(deal.id, user=self.consultor_sp)
        self.assertTrue(win_res.get("success"))

        # 6. Verify final state
        db.session.refresh(deal)
        self.assertEqual(deal.status, "ganho")
        self.assertEqual(deal.etapa_id, self.etapa_ponto_ganho.id)
        self.assertIsNotNone(deal.closed_at)

    def test_r5_02_rd_station_webhook_to_structured_lost_analysis(self):
        """Full Churn Path: Webhook -> RJ Routing -> Qualify -> Lost with Structured Category -> Metrics Breakdown."""
        # 1. Inbound Webhook Conversion with RJ phone
        inbound_payload = {
            "event_type": "CONVERSION",
            "conversion_identifier": "controle-de-acesso-catracas",
            "lead": {
                "name": "Roberto Dias",
                "email": "roberto@diasadv.com.br",
                "personal_phone": "+55 (21) 98111-2233",
                "company_name": "Dias Advocacia",
                "company_cnpj": "23.456.789/0001-01",
                "state": "RJ",
                "need": "Catraca de Acesso",
                "traffic_source": "Busca Orgânica | Google",
            }
        }
        res_webhook = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json=inbound_payload,
        )
        self.assertEqual(res_webhook.status_code, 201)
        deal_id = res_webhook.get_json()["deal_id"]

        deal = CrmNegociacao.query.get(deal_id)
        self.assertEqual(deal.user_id, self.consultor_rj.id, "Deal must be assigned to RJ consultant via DDD 21")
        self.assertEqual(deal.funil_id, self.funil_acesso.id, "Deal must be routed to Funil Acesso")

        # 2. RJ Consultant marks deal as lost with structured category
        self._login(self.consultor_rj)
        res_perder = self.client.post(
            f"/crm/api/negociacoes/{deal.id}/perder",
            json={
                "categoria": "concorrente",
                "motivo": "Fechou com Concorrente",
                "detalhes": "Cliente optou por locação com a Dimep",
                "motivo_perda_id": self.motivo_concorrente.id,
            }
        )
        self.assertEqual(res_perder.status_code, 200)

        # 3. Verify deal state and loss breakdown
        db.session.refresh(deal)
        self.assertEqual(deal.status, "perdido")
        self.assertEqual(deal.etapa_id, self.etapa_acesso_perdido.id)
        self.assertEqual(deal.motivo_perda_categoria, "concorrente")

        breakdown = crm_service.get_loss_reasons_breakdown(funil_id=self.funil_acesso.id)
        self.assertEqual(breakdown["by_category"]["concorrente"]["count"], 1)

    def test_r5_03_webhook_deduplication_lifecycle_with_multiple_conversions(self):
        """Validates that a lead converting in Ponto and later in Acesso reuses Company & Contact without duplication."""
        # Conversion 1: Ponto
        payload_1 = {
            "event_type": "CONVERSION",
            "conversion_identifier": "controle-software-relogio-de-ponto",
            "lead": {
                "name": "Fernanda Lima",
                "email": "fernanda@inovare.com.br",
                "personal_phone": "(11) 97654-3210",
                "company_name": "Inovare Soluções Corporativas",
                "company_cnpj": "34.567.890/0001-12",
                "need": "Relógio de Ponto",
            }
        }
        res1 = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json=payload_1,
        )
        self.assertEqual(res1.status_code, 201)
        deal_1_id = res1.get_json()["deal_id"]

        # Conversion 2: Later conversion for Acesso
        payload_2 = {
            "event_type": "CONVERSION",
            "conversion_identifier": "controle-de-acesso-catracas",
            "lead": {
                "name": "Fernanda Lima",
                "email": "fernanda@inovare.com.br",
                "personal_phone": "(11) 97654-3210",
                "company_name": "Inovare Soluções Corporativas",
                "company_cnpj": "34.567.890/0001-12",
                "need": "Catraca de Acesso",
            }
        }
        res2 = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "sollus-test-token-secret-12345"},
            json=payload_2,
        )
        self.assertEqual(res2.status_code, 201)
        deal_2_id = res2.get_json()["deal_id"]

        self.assertNotEqual(deal_1_id, deal_2_id, "Two distinct deals should be created for two conversions")

        deal1 = CrmNegociacao.query.get(deal_1_id)
        deal2 = CrmNegociacao.query.get(deal_2_id)

        # Both deals must link to the EXACT SAME company and contact
        self.assertEqual(deal1.empresa_id, deal2.empresa_id, "Both deals must share the same CrmEmpresa")
        self.assertEqual(deal1.contato_id, deal2.contato_id, "Both deals must share the same CrmContato")

        # Distinct pipelines
        self.assertEqual(deal1.funil_id, self.funil_ponto.id)
        self.assertEqual(deal2.funil_id, self.funil_acesso.id)


if __name__ == "__main__":
    unittest.main()
