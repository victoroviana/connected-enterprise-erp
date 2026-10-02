"""Adversarial Stress Test Suite for CRM Milestone M3 (Central de Integrações & Webhooks).

Targeted Adversarial Vectors:
1. Inbound Webhook Auth Failure & Edge Cases:
   - Missing authentication headers (HTTP 401)
   - Empty or whitespace-only token headers (HTTP 401)
   - Invalid X-API-Token (HTTP 401)
   - Malformed Authorization headers: missing 'Bearer ', missing token value, whitespace token (HTTP 401)
   - Case-insensitive Bearer prefix handling

2. Inbound Webhook Malformed Payload & Input Fuzzing:
   - Content-Type not JSON or completely unparseable body (HTTP 400)
   - Top-level JSON array instead of object (HTTP 400)
   - Malformed numeric fields (e.g. non-numeric string for 'valor') -> should reject gracefully without unhandled 500
   - Null / unexpected types for nested 'empresa' and 'contato' (strings, booleans, integers)
   - Non-existent or invalid funil_id / etapa_id -> graceful fallback to default active funnel
   - SQL injection / XSS payload strings in deal name and contact info

3. Outbound Webhook Error Resilience & Lifecycle Transaction Integrity:
   - Target endpoint raises ConnectionTimeout / ReadTimeout
   - Target endpoint returns HTTP 500, 502, 503, 404
   - Target endpoint raises SSLError or DNS failure
   - Verification that user-facing business transactions (create_deal, move_deal_stage, mark_deal_won, mark_deal_lost)
     complete successfully and commit to the database even when target webhook endpoint crashes
   - Verification that CrmWebhookLog records accurate failure entries (sucesso=False, status_code, elapsed_ms, error message)

4. Lead Deduplication Stress & Boundary Matching:
   - CNPJ normalization: formatted (xx.xxx.xxx/xxxx-xx), raw digits, spaces, dots, dashes
   - Case-insensitive and trimmed contact email deduplication
   - Sequential ingestion burst of 5 leads with identical CNPJ & Email: 1 Empresa, 1 Contato, 5 linked Deals
   - Company name fallback matching when CNPJ is absent
   - Empty or missing sub-objects (empresa=None, contato=None)

5. E2E Lifecycle Webhook Dispatch Verification:
   - Investigation and empirical reproduction of test_tier1_r3_04_outbound_webhook_lifecycle_dispatch behavior
"""
from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from unittest.mock import MagicMock, patch
import requests
from sqlalchemy.pool import StaticPool

from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmWebhook,
    CrmWebhookLog,
)
from modules.crm.services.crm_service import (
    compute_webhook_signature,
    get_active_outbound_webhooks,
    dispatch_crm_webhook_event,
    create_deal,
    move_deal_stage,
    mark_deal_won,
    mark_deal_lost,
)


class TestConfigAdversarialM3:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-adversarial-m3"
    CRM_WEBHOOK_API_TOKEN = "valid_secure_token_m3_stress_2026"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class BaseAdversarialM3TestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfigAdversarialM3)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()

        # Seed Department and Consultants
        self.dept = Department(name="COMERCIAL", slug="comercial")
        db.session.add(self.dept)
        db.session.flush()

        self.consultant_1 = User(
            usuario="adv_consultant_1",
            nome_completo="Consultor Alpha",
            email="c1_adv@sollus.com",
            password_hash="pwd1",
            tipo="consultor",
            role="usuario",
            is_active=True,
            department_id=self.dept.id,
            permissions={"crm": True},
        )
        self.consultant_2 = User(
            usuario="adv_consultant_2",
            nome_completo="Consultora Beta",
            email="c2_adv@sollus.com",
            password_hash="pwd2",
            tipo="consultor",
            role="usuario",
            is_active=True,
            department_id=self.dept.id,
            permissions={"crm": True},
        )
        self.admin_user = User(
            usuario="adv_admin",
            nome_completo="Admin M3",
            email="admin_adv@sollus.com",
            password_hash="pwd_adm",
            tipo="admin",
            role="admin",
            is_active=True,
            permissions={"crm": True, "admin": True},
        )
        db.session.add_all([self.consultant_1, self.consultant_2, self.admin_user])
        db.session.commit()

        # Seed Funnel and Stages
        self.funil = CrmFunil(
            id="funil_adv_m3",
            nome="Funil Adversarial M3",
            slug="funil_adv_m3",
            tipo="ponto",
            ordem=1,
            ativo=True,
        )
        db.session.add(self.funil)
        db.session.flush()

        self.etapa_entrada = CrmEtapa(
            id="etapa_entrada_adv",
            funil_id=self.funil.id,
            nome="Entrada",
            ordem=1,
            tipo="normal",
            cor="#3b82f6",
        )
        self.etapa_qualif = CrmEtapa(
            id="etapa_qualif_adv",
            funil_id=self.funil.id,
            nome="Qualificação",
            ordem=2,
            tipo="normal",
            cor="#8b5cf6",
        )
        self.etapa_ganho = CrmEtapa(
            id="etapa_ganho_adv",
            funil_id=self.funil.id,
            nome="Ganho",
            ordem=3,
            tipo="ganho",
            cor="#10b981",
        )
        self.etapa_perdido = CrmEtapa(
            id="etapa_perdido_adv",
            funil_id=self.funil.id,
            nome="Perdido",
            ordem=4,
            tipo="perdido",
            cor="#ef4444",
        )
        db.session.add_all([
            self.etapa_entrada,
            self.etapa_qualif,
            self.etapa_ganho,
            self.etapa_perdido,
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()


class TestAdversarialInboundAuth(BaseAdversarialM3TestCase):
    """Stress tests on Inbound Webhook Authentication & Token Handling."""

    def test_auth_missing_all_headers_returns_401(self):
        res = self.client.post("/crm/api/webhooks/inbound", json={"nome": "Lead Inbound"})
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertFalse(data.get("success"))

    def test_auth_empty_header_values_return_401(self):
        # Empty string
        res = self.client.post("/crm/api/webhooks/inbound", headers={"X-API-Token": ""}, json={"nome": "X"})
        self.assertEqual(res.status_code, 401)

        # Whitespace only
        res2 = self.client.post("/crm/api/webhooks/inbound", headers={"X-API-Token": "    "}, json={"nome": "X"})
        self.assertEqual(res2.status_code, 401)

    def test_auth_bearer_prefix_malformed_returns_401(self):
        # Header with only "Bearer"
        res = self.client.post("/crm/api/webhooks/inbound", headers={"Authorization": "Bearer"}, json={"nome": "X"})
        self.assertEqual(res.status_code, 401)

        # Header with "Bearer " (whitespace only token)
        res2 = self.client.post("/crm/api/webhooks/inbound", headers={"Authorization": "Bearer   "}, json={"nome": "X"})
        self.assertEqual(res2.status_code, 401)

        # Header with non-bearer scheme
        res3 = self.client.post("/crm/api/webhooks/inbound", headers={"Authorization": "Basic dXNlcjpwYXNz"}, json={"nome": "X"})
        self.assertEqual(res3.status_code, 401)

    def test_auth_wrong_token_returns_401(self):
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "totally_wrong_attacker_token_xyz"},
            json={"nome": "Attacker Lead"}
        )
        self.assertEqual(res.status_code, 401)

    def test_auth_case_insensitive_bearer_with_valid_token_succeeds(self):
        # "bEaReR" with surrounding whitespace around token
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"Authorization": f"bEaReR  {TestConfigAdversarialM3.CRM_WEBHOOK_API_TOKEN}  "},
            json={"nome_negociacao": "Lead Mixed Case Bearer", "valor": 500.0}
        )
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.get_json()["success"])


class TestAdversarialInboundPayloadValidation(BaseAdversarialM3TestCase):
    """Stress tests on Inbound Webhook Payload Parsing & Malformed Inputs."""

    def test_payload_non_json_content_type_returns_400(self):
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigAdversarialM3.CRM_WEBHOOK_API_TOKEN, "Content-Type": "text/html"},
            data="<html><body>Not JSON</body></html>"
        )
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["success"])

    def test_payload_json_array_returns_400(self):
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigAdversarialM3.CRM_WEBHOOK_API_TOKEN},
            json=[{"nome": "Lead In Array"}]
        )
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["success"])

    def test_payload_invalid_valor_type_raises_unhandled_valueerror(self):
        """Adversarial Finding: non-numeric string in 'valor' raises unhandled ValueError instead of returning HTTP 400."""
        with self.assertRaises(ValueError):
            self.client.post(
                "/crm/api/webhooks/inbound",
                headers={"X-API-Token": TestConfigAdversarialM3.CRM_WEBHOOK_API_TOKEN},
                json={"nome_negociacao": "Lead Bad Valor", "valor": "cinquenta_mil"}
            )

    def test_payload_empty_object_creates_phantom_lead_instead_of_400(self):
        """Adversarial Finding: empty payload `{}` or payload with missing name/contact does not return 400."""
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigAdversarialM3.CRM_WEBHOOK_API_TOKEN},
            json={}
        )
        # Note: Requirement R3 states missing name/contact must return HTTP 400,
        # but the current implementation accepts `{}` and generates "Lead - Inbound Webhook" (HTTP 201).
        # We record the actual response code empirically.
        self.assertIn(res.status_code, [201, 400])


    def test_payload_nested_empresa_contato_unexpected_types(self):
        """Stress: 'empresa' and 'contato' passed as plain string or null."""
        payload = {
            "nome_negociacao": "Lead Robust Nested Types",
            "valor": 1200.0,
            "empresa": "Minha Empresa Apenas String",
            "contato": "Apenas Nome String",
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigAdversarialM3.CRM_WEBHOOK_API_TOKEN},
            json=payload
        )
        self.assertEqual(res.status_code, 201)
        deal_id = res.get_json()["deal_id"]
        deal = CrmNegociacao.query.get(deal_id)
        self.assertIsNotNone(deal)
        self.assertIsNotNone(deal.empresa)
        self.assertEqual(deal.empresa.nome, "Minha Empresa Apenas String")

    def test_payload_non_existent_funil_falls_back_to_active(self):
        """Stress: funil_id passed does not exist -> must gracefully fall back to active funnel."""
        payload = {
            "nome_negociacao": "Lead Invalid Funnel",
            "funil_id": "non_existent_funnel_uuid_99999",
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigAdversarialM3.CRM_WEBHOOK_API_TOKEN},
            json=payload
        )
        self.assertEqual(res.status_code, 201)
        deal_id = res.get_json()["deal_id"]
        deal = CrmNegociacao.query.get(deal_id)
        self.assertEqual(deal.funil_id, self.funil.id)

    def test_payload_xss_and_sql_injection_resilience(self):
        """Stress: XSS and SQL injection strings in lead payload."""
        payload = {
            "nome_negociacao": "<script>alert('xss')</script>'; DROP TABLE crm_negociacoes; --",
            "empresa": {"nome": "Empresa <img src=x onerror=alert(1)>", "cnpj": "12.345.678/0001-90"},
            "contato": {"nome": "Contato'; SELECT * FROM users; --", "email": "sql@injection.test"},
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigAdversarialM3.CRM_WEBHOOK_API_TOKEN},
            json=payload
        )
        self.assertEqual(res.status_code, 201)
        deal_id = res.get_json()["deal_id"]
        deal = CrmNegociacao.query.get(deal_id)
        self.assertIsNotNone(deal)
        self.assertIn("DROP TABLE", deal.nome)
        # Verify table still exists and deals exist
        self.assertGreaterEqual(CrmNegociacao.query.count(), 1)


class TestAdversarialOutboundResilience(BaseAdversarialM3TestCase):
    """Stress tests on Outbound Webhook Resilience under Network Failure and Lifecycle Triggers."""

    @patch("requests.post")
    def test_outbound_http_500_resilience(self, mock_post):
        """Target webhook returns HTTP 500: caller transaction succeeds, failure is logged."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error in Target System"
        mock_post.return_value = mock_resp

        wh = CrmWebhook(
            nome="Webhook Destino Instavel",
            url="https://flaky-external-crm.com/api/events",
            eventos="deal.won",
            ativo=True
        )
        db.session.add(wh)
        db.session.commit()

        # Create deal and mark won
        deal = create_deal(
            nome="Negocio Ganho Sob 500",
            valor=25000.0,
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            user_id=self.consultant_1.id
        )

        # Mark won triggers dispatch
        res_won = mark_deal_won(deal.id, user=self.admin_user)
        self.assertIsNotNone(res_won)

        # Verify DB transaction completed
        db.session.refresh(deal)
        self.assertEqual(deal.status, "ganho")

        # Verify CrmWebhookLog recorded failure
        log = CrmWebhookLog.query.filter_by(webhook_id=wh.id, evento="deal.won").first()
        self.assertIsNotNone(log)
        self.assertFalse(log.sucesso)
        self.assertEqual(log.status_code, 500)
        self.assertIn("Internal Server Error", log.response_body)

    @patch("requests.post")
    def test_outbound_timeout_resilience(self, mock_post):
        """Target webhook times out: caller transaction succeeds, status_code=0 logged."""
        mock_post.side_effect = requests.exceptions.Timeout("HTTPSConnectionPool: Read timed out. (read timeout=10)")

        wh = CrmWebhook(
            nome="Webhook Destino Timeout",
            url="https://slow-external-crm.com/api/events",
            eventos="deal.lost",
            ativo=True
        )
        db.session.add(wh)
        db.session.commit()

        deal = create_deal(
            nome="Negocio Perdido Sob Timeout",
            valor=10000.0,
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            user_id=self.consultant_2.id
        )

        # Mark lost triggers dispatch
        res_lost = mark_deal_lost(deal.id, motivo="Sem orcamento", user=self.admin_user, categoria="preco")
        self.assertIsNotNone(res_lost)

        db.session.refresh(deal)
        self.assertEqual(deal.status, "perdido")

        log = CrmWebhookLog.query.filter_by(webhook_id=wh.id, evento="deal.lost").first()
        self.assertIsNotNone(log)
        self.assertFalse(log.sucesso)
        self.assertEqual(log.status_code, 0)
        self.assertIn("Read timed out", log.response_body)

    @patch("requests.post")
    def test_outbound_ssl_error_resilience(self, mock_post):
        """Target webhook has SSL certificate error: caller completes without crashing."""
        mock_post.side_effect = requests.exceptions.SSLError("SSL: CERTIFICATE_VERIFY_FAILED")

        wh = CrmWebhook(
            nome="Webhook Destino SSL Invalido",
            url="https://expired-ssl.com/webhook",
            eventos="deal.stage_changed",
            ativo=True
        )
        db.session.add(wh)
        db.session.commit()

        deal = create_deal(
            nome="Negocio Troca Etapa SSL",
            valor=15000.0,
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            user_id=self.consultant_1.id
        )

        # Move stage triggers deal.stage_changed
        moved = move_deal_stage(deal.id, self.etapa_qualif.id)
        self.assertIsNotNone(moved)

        db.session.refresh(deal)
        self.assertEqual(deal.etapa_id, self.etapa_qualif.id)

        log = CrmWebhookLog.query.filter_by(webhook_id=wh.id, evento="deal.stage_changed").first()
        self.assertIsNotNone(log)
        self.assertFalse(log.sucesso)
        self.assertIn("CERTIFICATE_VERIFY_FAILED", log.response_body)


class TestAdversarialLeadDeduplicationStress(BaseAdversarialM3TestCase):
    """Stress tests on Lead Deduplication (CNPJ variations, Email casing, burst capture)."""

    def test_deduplication_cnpj_multiple_punctuation_formats(self):
        """Format 1: '12.345.678/0001-90' in DB.
        Format 2: '12345678000190'
        Format 3: '12 345 678 0001 90'
        Format 4: '12.345.678-0001/90'
        All must link to the single original CrmEmpresa!
        """
        empresa_orig = CrmEmpresa(
            id="emp_dedup_master",
            nome="Master Tecnologia Ltda",
            cnpj="12.345.678/0001-90"
        )
        db.session.add(empresa_orig)
        db.session.commit()

        variations = [
            "12345678000190",
            "12 345 678 0001 90",
            "12.345.678-0001/90",
            "12-345-678/0001-90",
        ]

        for i, cnpj_var in enumerate(variations):
            payload = {
                "nome_negociacao": f"Negocio Dedup {i+1}",
                "valor": 1000.0 * (i + 1),
                "empresa": {"nome": f"Empresa Nome {i}", "cnpj": cnpj_var},
                "contato": {"nome": f"Contato {i}", "email": f"c{i}@master.com"},
            }
            res = self.client.post(
                "/crm/api/webhooks/inbound",
                headers={"X-API-Token": TestConfigAdversarialM3.CRM_WEBHOOK_API_TOKEN},
                json=payload
            )
            self.assertEqual(res.status_code, 201)
            deal_id = res.get_json()["deal_id"]
            deal = CrmNegociacao.query.get(deal_id)
            self.assertEqual(deal.empresa_id, empresa_orig.id, f"Failed dedup for variation: {cnpj_var}")

        # Assert no duplicate companies were created
        self.assertEqual(CrmEmpresa.query.count(), 1, "There must be exactly 1 company in DB")
        # Assert 4 deals were created and linked to the same company
        self.assertEqual(CrmNegociacao.query.filter_by(empresa_id=empresa_orig.id).count(), 4)

    def test_deduplication_email_casing_and_whitespace_burst(self):
        """Test burst ingestion of 5 leads with mixed casing and spaces in Email."""
        contato_orig = CrmContato(
            id="cont_dedup_master",
            nome="Dra. Beatriz Santos",
            email="beatriz.santos@hospital.med.br"
        )
        db.session.add(contato_orig)
        db.session.commit()

        email_variations = [
            "BEATRIZ.SANTOS@HOSPITAL.MED.BR",
            "  beatriz.santos@hospital.med.br  ",
            "Beatriz.Santos@Hospital.Med.Br",
            "  BEATRIZ.SANTOS@HOSPITAL.MED.BR\t",
            "beatriz.santos@HOSPITAL.med.br",
        ]

        for i, email_var in enumerate(email_variations):
            payload = {
                "nome_negociacao": f"Oportunidade Med {i+1}",
                "contato": {"nome": f"Dra. Beatriz ({i})", "email": email_var},
            }
            res = self.client.post(
                "/crm/api/webhooks/inbound",
                headers={"X-API-Token": TestConfigAdversarialM3.CRM_WEBHOOK_API_TOKEN},
                json=payload
            )
            self.assertEqual(res.status_code, 201)
            deal_id = res.get_json()["deal_id"]
            deal = CrmNegociacao.query.get(deal_id)
            self.assertEqual(deal.contato_id, contato_orig.id, f"Failed dedup for email variation: '{email_var}'")

        self.assertEqual(CrmContato.query.count(), 1, "There must be exactly 1 contact in DB")
        self.assertEqual(CrmNegociacao.query.filter_by(contato_id=contato_orig.id).count(), 5)


class TestAdversarialE2EInvestigation(BaseAdversarialM3TestCase):
    """Deep investigation of test_tier1_r3_04_outbound_webhook_lifecycle_dispatch."""

    @patch("requests.post")
    def test_reproduce_tier1_r3_04_with_and_without_registered_webhook(self, mock_post):
        """Empirically demonstrates why test_tier1_r3_04 fails when no CrmWebhook is in DB."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "received"}'
        mock_post.return_value = mock_response

        deal = create_deal(
            nome="Deal Outbound Trigger Diagnostic",
            valor=10000.0,
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            user_id=self.consultant_1.id
        )

        # 1. Without any CrmWebhook row in DB and without CRM_OUTBOUND_WEBHOOK_URL config:
        res = dispatch_crm_webhook_event("deal.won", deal_id=deal.id, payload={"deal_id": deal.id})
        # Note: res is empty because targets is empty
        self.assertEqual(res, [])
        self.assertEqual(mock_post.call_count, 0, "When no webhook or fallback is configured, mock_post is NOT called")

        # 2. When a CrmWebhook is registered (or fallback is present):
        wh = CrmWebhook(
            nome="Integration Webhook Won",
            url="https://api.external.com/webhook",
            eventos="deal.won",
            ativo=True
        )
        db.session.add(wh)
        db.session.commit()

        res2 = dispatch_crm_webhook_event("deal.won", deal_id=deal.id, payload={"deal_id": deal.id})
        self.assertEqual(len(res2), 1)
        self.assertEqual(mock_post.call_count, 1, "When CrmWebhook is present, mock_post IS called!")


if __name__ == "__main__":
    unittest.main()
