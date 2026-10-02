"""Testes automatizados do Milestone M3 - Central de Integrações & Webhooks (Requirement R3).

Abrange:
1. Inbound Webhook Endpoint (/crm/api/webhooks/inbound):
   - Autenticação por token via header X-API-Token e Bearer Token (Authorization)
   - Validação de payload e rejeição de requisições malformadas ou vazias (400)
   - Deduplicação inteligente de Empresa por dígitos normalizados do CNPJ
   - Deduplicação inteligente de Contato por e-mail normalizado (case-insensitive)
   - Distribuição do lead pela Roleta Comercial determinística (Round-Robin)
   - Disparo automático de regras e tarefas de automação da etapa inicial
   - Registro detalhado de log de auditoria inbound (CrmWebhookLog)
   - Disparo de evento outbound 'deal.created' em background

2. Outbound Webhook Lifecycle Dispatcher:
   - Assinatura criptográfica HMAC-SHA256 (compute_webhook_signature)
   - Filtragem por evento específico e suporte a coringa ('*')
   - Ignorância e não envio para webhooks inativos (ativo=False)
   - Resiliência total contra timeout e erros de rede/SSL do endpoint destino
   - Registro de histórico de entrega com status_code, tempo_execucao_ms e response_body
   - Gatilhos automáticos no ciclo de vida da negociação (deal.created, deal.stage_changed, deal.won, deal.lost)

3. Webhooks Management Hub (UI e APIs REST):
   - Renderização da página /crm/webhooks com KPIs, documentação e tabelas
   - Listagem (GET /crm/api/webhooks)
   - Criação (POST /crm/api/webhooks) com validações e geração de secret
   - Ativação/Desativação rápida (POST /crm/api/webhooks/<id>/toggle)
   - Disparo de teste manual / ping (POST /crm/api/webhooks/<id>/test)
   - Remoção de webhook (DELETE /crm/api/webhooks/<id>)
   - Consulta de logs de entrega (GET /crm/api/webhooks/logs)
"""
from __future__ import annotations

import hmac
import hashlib
import json
import unittest
from unittest.mock import MagicMock, patch
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
    CrmRegraAutomacao,
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


class TestConfigM3:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key-crm-m3"
    CRM_WEBHOOK_API_TOKEN = "token_inbound_secreto_test_123"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class BaseCrmM3TestCase(unittest.TestCase):
    """Base setup com app context, funil, etapas, usuários consultores e admin."""

    def setUp(self):
        self.app = create_app(TestConfigM3)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()

        # Departamento Comercial
        self.dept_comercial = Department(name="COMERCIAL", slug="comercial")
        db.session.add(self.dept_comercial)
        db.session.flush()

        # Consultores comerciais ativos para a roleta
        self.consultant_1 = User(
            usuario="c1_m3",
            nome_completo="Carlos Consultor M3",
            email="c1@sollus.com",
            password_hash="hash1",
            tipo="consultor",
            role="usuario",
            is_active=True,
            department_id=self.dept_comercial.id,
            permissions={"crm": True},
        )
        self.consultant_2 = User(
            usuario="c2_m3",
            nome_completo="Camila Consultora M3",
            email="c2@sollus.com",
            password_hash="hash2",
            tipo="consultor",
            role="usuario",
            is_active=True,
            department_id=self.dept_comercial.id,
            permissions={"crm": True},
        )
        self.consultant_inactive = User(
            usuario="c_inativo_m3",
            nome_completo="Inativo Consultor M3",
            email="inativo@sollus.com",
            password_hash="hash_inativo",
            tipo="consultor",
            role="usuario",
            is_active=False,
            department_id=self.dept_comercial.id,
            permissions={"crm": True},
        )
        # Usuário Admin
        self.admin_user = User(
            usuario="admin_m3",
            nome_completo="Gestor M3",
            email="admin_m3@sollus.com",
            password_hash="hash_adm",
            tipo="admin",
            role="admin",
            is_active=True,
            permissions={"crm": True, "admin": True},
        )
        db.session.add_all([
            self.consultant_1,
            self.consultant_2,
            self.consultant_inactive,
            self.admin_user,
        ])
        db.session.commit()

        # Funil de Vendas Padrão
        self.funil = CrmFunil(
            id="funil_m3_test",
            nome="Funil Vendas M3",
            slug="funil_m3",
            tipo="ponto",
            ordem=1,
            ativo=True,
        )
        db.session.add(self.funil)
        db.session.flush()

        self.etapa_entrada = CrmEtapa(
            id="etapa_entrada_m3",
            funil_id=self.funil.id,
            nome="Entrada / Novo",
            ordem=1,
            tipo="normal",
            cor="#3b82f6",
        )
        self.etapa_qualif = CrmEtapa(
            id="etapa_qualif_m3",
            funil_id=self.funil.id,
            nome="Qualificação",
            ordem=2,
            tipo="normal",
            cor="#8b5cf6",
        )
        self.etapa_ganho = CrmEtapa(
            id="etapa_ganho_m3",
            funil_id=self.funil.id,
            nome="Fechamento Ganho",
            ordem=3,
            tipo="ganho",
            cor="#10b981",
        )
        self.etapa_perdido = CrmEtapa(
            id="etapa_perdido_m3",
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

    def _login(self, user: User | None = None):
        target = user or self.admin_user
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(target.id)
            sess["user_id"] = target.id
            sess["usuario_id"] = target.id
            sess["tipo"] = target.tipo
            sess["role"] = target.role


class TestCrmM3InboundWebhook(BaseCrmM3TestCase):
    """Testes completos do endpoint de entrada Inbound Webhook."""

    def test_inbound_missing_token_returns_401(self):
        """Requisição sem header de token deve ser rejeitada com 401."""
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            json={"nome_negociacao": "Lead Sem Token"}
        )
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertFalse(data.get("success"))
        self.assertIn("Token", data.get("error", ""))

    def test_inbound_invalid_token_returns_401(self):
        """Requisição com token incorreto deve ser rejeitada com 401."""
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": "token_completamente_errado"},
            json={"nome_negociacao": "Lead Token Invalido"}
        )
        self.assertEqual(res.status_code, 401)

    def test_inbound_valid_x_api_token_creates_deal_201(self):
        """Autenticação via X-API-Token cria oportunidade com status 201."""
        payload = {
            "nome_negociacao": "Lead Inbound X-API-Token",
            "valor": 3500.0,
            "origem": "RD Station Inbound",
            "empresa": {"nome": "Clinica Santa Luzia", "cnpj": "12.345.678/0001-90"},
            "contato": {"nome": "Dr. Fernando", "email": "fernando@santaluzia.com.br", "telefone": "11999887766"},
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigM3.CRM_WEBHOOK_API_TOKEN},
            json=payload
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("created"))
        self.assertIsNotNone(data.get("deal_id"))

        deal = CrmNegociacao.query.get(data["deal_id"])
        self.assertIsNotNone(deal)
        self.assertEqual(deal.nome, "Lead Inbound X-API-Token")
        self.assertEqual(float(deal.valor_total), 3500.0)
        self.assertEqual(deal.origem, "RD Station Inbound")
        self.assertIn(deal.user_id, [self.consultant_1.id, self.consultant_2.id])

    def test_inbound_valid_bearer_token_creates_deal_201(self):
        """Autenticação via Authorization: Bearer <token> cria oportunidade com status 201."""
        payload = {
            "nome_negociacao": "Lead Inbound Bearer Token",
            "valor": 4200.0,
            "empresa": {"nome": "Logistica Rapida", "cnpj": "98765432000111"},
            "contato": {"nome": "Juliana Gestora", "email": "juliana@lograpida.com.br"},
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"Authorization": f"Bearer {TestConfigM3.CRM_WEBHOOK_API_TOKEN}"},
            json=payload
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data.get("success"))

    def test_inbound_malformed_json_returns_400(self):
        """Payload não-JSON ou vazio é rejeitado com status 400."""
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigM3.CRM_WEBHOOK_API_TOKEN, "Content-Type": "text/plain"},
            data="not-a-valid-json-string"
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("success"))

    def test_inbound_smart_deduplication_empresa_cnpj_formatting(self):
        """CNPJs com pontuações diferentes vinculam à mesma CrmEmpresa existente."""
        empresa_existente = CrmEmpresa(
            id="emp_m3_dedup",
            nome="Empresa Matriz Ltda",
            cnpj="55.666.777/0001-88"
        )
        db.session.add(empresa_existente)
        db.session.commit()

        # Inbound envia o mesmo CNPJ sem pontos ou traços
        payload = {
            "nome_negociacao": "Expansão Filial 2",
            "empresa": {"nome": "Empresa Matriz - Filial 2", "cnpj": "55666777000188"},
            "contato": {"nome": "Carlos Roberto", "email": "carlos@empresa.com"},
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigM3.CRM_WEBHOOK_API_TOKEN},
            json=payload
        )
        self.assertEqual(res.status_code, 201)
        deal_id = res.get_json()["deal_id"]
        deal = CrmNegociacao.query.get(deal_id)

        # Não deve criar uma nova empresa; deve reutilizar a existente
        self.assertEqual(deal.empresa_id, empresa_existente.id)
        self.assertEqual(CrmEmpresa.query.count(), 1)

    def test_inbound_smart_deduplication_contato_email_case_and_whitespace(self):
        """Contatos com e-mails normalizados (letras maiúsculas e espaços) reutilizam registro existente."""
        contato_existente = CrmContato(
            id="cont_m3_dedup",
            nome="Luciana Silveira",
            email="luciana.silveira@hospital.org"
        )
        db.session.add(contato_existente)
        db.session.commit()

        payload = {
            "nome_negociacao": "Renovação Anual",
            "contato": {"nome": "Luciana S.", "email": "  LUCIANA.SILVEIRA@HOSPITAL.ORG  "},
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigM3.CRM_WEBHOOK_API_TOKEN},
            json=payload
        )
        self.assertEqual(res.status_code, 201)
        deal_id = res.get_json()["deal_id"]
        deal = CrmNegociacao.query.get(deal_id)

        self.assertEqual(deal.contato_id, contato_existente.id)
        self.assertEqual(CrmContato.query.count(), 1)

    def test_inbound_creates_audit_log(self):
        """Requisição inbound bem-sucedida registra log de auditoria CrmWebhookLog com status 201."""
        payload = {
            "nome_negociacao": "Lead para Auditoria Inbound",
            "origem": "Landing Page X",
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigM3.CRM_WEBHOOK_API_TOKEN},
            json=payload
        )
        self.assertEqual(res.status_code, 201)

        log = CrmWebhookLog.query.order_by(CrmWebhookLog.id.desc()).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status_code, 201)
        self.assertTrue(log.sucesso)
        self.assertEqual(log.tipo, "inbound")
        self.assertIn("Lead para Auditoria Inbound", log.request_payload)

    def test_inbound_executes_stage_automation_and_creates_task(self):
        """Quando a etapa inicial possui regra de automação, tarefa de follow-up é gerada automaticamente."""
        regra = CrmRegraAutomacao(
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            evento="deal_criado",
            acao_tipo="criar_tarefa",
            tarefa_titulo="Ligar imediatamente para novo lead inbound",
            tarefa_tipo="ligacao",
            prazo_horas=2,
            ativo=True
        )
        db.session.add(regra)
        db.session.commit()

        payload = {
            "nome_negociacao": "Lead Automação Imediata",
            "funil_id": self.funil.id,
            "etapa_id": self.etapa_entrada.id,
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            headers={"X-API-Token": TestConfigM3.CRM_WEBHOOK_API_TOKEN},
            json=payload
        )
        self.assertEqual(res.status_code, 201)
        deal_id = res.get_json()["deal_id"]

        tarefas = CrmTarefa.query.filter_by(negociacao_id=deal_id).all()
        self.assertTrue(any("Ligar imediatamente" in t.titulo for t in tarefas))


class TestCrmM3OutboundWebhookDispatcher(BaseCrmM3TestCase):
    """Testes completos do despachante Outbound Webhook e HMAC-SHA256."""

    def test_compute_webhook_signature(self):
        """Verifica que compute_webhook_signature produz hash HMAC-SHA256 com prefixo sha256=."""
        secret = "chave_secreta_teste_xyz"
        payload = b'{"event":"deal.won","deal_id":"123"}'
        raw_hash = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        computed_sig = compute_webhook_signature(payload, secret)
        self.assertEqual(computed_sig, f"sha256={raw_hash}")

    def test_get_active_outbound_webhooks_filtering(self):
        """get_active_outbound_webhooks seleciona webhooks ativos por evento exato ou coringa '*'."""
        wh1 = CrmWebhook(
            nome="Webhook Fechamento",
            tipo="outbound",
            url="https://api.empresa.com/won",
            eventos="deal.won",
            ativo=True
        )
        wh2 = CrmWebhook(
            nome="Webhook Universal",
            tipo="outbound",
            url="https://api.empresa.com/all",
            eventos="*",
            ativo=True
        )
        wh3 = CrmWebhook(
            nome="Webhook Desativado",
            tipo="outbound",
            url="https://api.empresa.com/inativo",
            eventos="deal.won",
            ativo=False
        )
        wh4 = CrmWebhook(
            nome="Webhook Perda",
            tipo="outbound",
            url="https://api.empresa.com/lost",
            eventos="deal.lost",
            ativo=True
        )
        db.session.add_all([wh1, wh2, wh3, wh4])
        db.session.commit()

        won_webhooks = get_active_outbound_webhooks("deal.won")
        won_ids = [w.id for w in won_webhooks]
        self.assertIn(wh1.id, won_ids)
        self.assertIn(wh2.id, won_ids)
        self.assertNotIn(wh3.id, won_ids, "Webhooks inativos não devem ser retornados")
        self.assertNotIn(wh4.id, won_ids, "Eventos divergentes não devem ser retornados")

    @patch("requests.post")
    def test_dispatch_crm_webhook_event_success_and_signature_header(self, mock_post):
        """Disparo com sucesso envia headers X-Sollus-Signature, X-Sollus-Event e registra CrmWebhookLog."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status":"received"}'
        mock_post.return_value = mock_resp

        wh = CrmWebhook(
            nome="Webhook Seguro",
            tipo="outbound",
            url="https://api.destino.com/webhook",
            eventos="deal.created",
            secret="minha_assinatura_secreta",
            ativo=True
        )
        db.session.add(wh)
        db.session.commit()

        res = dispatch_crm_webhook_event(
            "deal.created",
            deal_id="deal_100",
            payload={"id": "deal_100", "status": "aberto"}
        )
        self.assertEqual(len(res), 1)

        # Verifica chamada HTTP
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.destino.com/webhook")
        headers = kwargs["headers"]
        self.assertEqual(headers["X-Sollus-Event"], "deal.created")
        self.assertIn("X-Sollus-Signature", headers)
        self.assertIn("X-Sollus-Delivery", headers)

        # Verifica log gravado
        log = CrmWebhookLog.query.filter_by(webhook_id=wh.id).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status_code, 200)
        self.assertTrue(log.sucesso)
        self.assertEqual(log.tipo, "outbound")

    @patch("requests.post")
    def test_dispatch_crm_webhook_resilience_on_network_error(self, mock_post):
        """Falha de rede ou timeout nunca deve propagar exceção para o chamador."""
        import requests
        mock_post.side_effect = requests.exceptions.ConnectTimeout("Connection to destination timed out")

        wh = CrmWebhook(
            nome="Webhook com Timeout",
            tipo="outbound",
            url="https://blackhole.servidor.com",
            eventos="deal.stage_changed",
            ativo=True
        )
        db.session.add(wh)
        db.session.commit()

        # O despacho não deve lançar exceção
        res = dispatch_crm_webhook_event(
            "deal.stage_changed",
            deal_id="deal_200",
            payload={"etapa": "qualificacao"}
        )
        self.assertEqual(len(res), 1)

        # Deve persistir log com sucesso=False
        log = CrmWebhookLog.query.filter_by(webhook_id=wh.id).first()
        self.assertIsNotNone(log)
        self.assertFalse(log.sucesso)
        self.assertEqual(log.status_code, 0)
        self.assertIn("Connection to destination timed out", log.response_body)

    @patch("requests.post")
    def test_lifecycle_hooks_trigger_webhooks(self, mock_post):
        """Testa o acionamento de webhooks nos métodos de ciclo de vida do CRM."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"
        mock_post.return_value = mock_resp

        wh = CrmWebhook(
            nome="Webhook Ciclo de Vida",
            tipo="outbound",
            url="https://api.empresa.com/lifecycle",
            eventos="*",
            ativo=True
        )
        db.session.add(wh)
        db.session.commit()

        # 1. create_deal dispara deal.created
        deal = create_deal(
            nome="Negociação Ciclo Completo",
            valor=15000.0,
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            user_id=self.consultant_1.id
        )
        self.assertTrue(mock_post.called)
        last_event = mock_post.call_args[1]["headers"]["X-Sollus-Event"]
        self.assertEqual(last_event, "deal.created")

        # 2. move_deal_stage dispara deal.stage_changed
        move_deal_stage(deal.id, self.etapa_qualif.id)
        last_event = mock_post.call_args[1]["headers"]["X-Sollus-Event"]
        self.assertEqual(last_event, "deal.stage_changed")

        # 3. mark_deal_won dispara deal.won
        mark_deal_won(deal.id, user=self.admin_user)
        last_event = mock_post.call_args[1]["headers"]["X-Sollus-Event"]
        self.assertEqual(last_event, "deal.won")

        # 4. mark_deal_lost dispara deal.lost
        deal2 = create_deal(
            nome="Negociação Perdida Teste",
            valor=8000.0,
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            user_id=self.consultant_2.id
        )
        mark_deal_lost(deal2.id, motivo="Preço alto", user=self.admin_user, categoria="preco")
        last_event = mock_post.call_args[1]["headers"]["X-Sollus-Event"]
        self.assertEqual(last_event, "deal.lost")


class TestCrmM3WebhooksHubUIAndAPI(BaseCrmM3TestCase):
    """Testes completos da interface gráfica e endpoints REST da Central de Webhooks."""

    def test_webhooks_ui_page_renders_200(self):
        """A rota GET /crm/webhooks deve renderizar 200 OK com layout e componentes."""
        self._login(self.admin_user)
        res = self.client.get("/crm/webhooks")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")
        self.assertIn("Webhooks", html)
        self.assertIn("/crm/api/webhooks/inbound", html)
        self.assertIn("Novo Webhook", html)

    def test_webhooks_access_restricted_for_non_admin(self):
        """Usuários que não sejam admin são bloqueados de acessar a UI e APIs de webhooks."""
        self._login(self.consultant_1)
        res_ui = self.client.get("/crm/webhooks")
        self.assertEqual(res_ui.status_code, 302)

        res_api = self.client.get("/crm/api/webhooks")
        self.assertEqual(res_api.status_code, 403)

        res_post = self.client.post("/crm/api/webhooks", json={"nome": "Teste Bloqueado"})
        self.assertEqual(res_post.status_code, 403)

    def test_api_webhooks_crud_lifecycle(self):
        """Testa criação, listagem, toggle, teste manual e exclusão de webhooks via API."""
        self._login(self.admin_user)

        # 1. Listagem inicial vazia
        res = self.client.get("/crm/api/webhooks")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.get_json()["data"]), 0)

        # 2. Criação de Webhook
        create_payload = {
            "nome": "Integração Slack Financeiro",
            "url": "https://hooks.slack.com/services/T00/B00/X00",
            "evento": "deal.won",
            "ativo": True,
            "secret": "slack_secret_123"
        }
        res_create = self.client.post("/crm/api/webhooks", json=create_payload)
        self.assertEqual(res_create.status_code, 201)
        created_wh = res_create.get_json()["data"]
        wh_id = created_wh["id"]
        self.assertEqual(created_wh["nome"], "Integração Slack Financeiro")
        self.assertTrue(created_wh["ativo"])

        # 3. Listagem contém webhook criado
        res_list = self.client.get("/crm/api/webhooks")
        self.assertEqual(len(res_list.get_json()["data"]), 1)

        # 4. Toggle Ativo/Inativo
        res_toggle = self.client.post(f"/crm/api/webhooks/{wh_id}/toggle")
        self.assertEqual(res_toggle.status_code, 200)
        self.assertFalse(res_toggle.get_json()["data"]["ativo"])

        # Toggle de volta para ativo
        res_toggle2 = self.client.post(f"/crm/api/webhooks/{wh_id}/toggle")
        self.assertEqual(res_toggle2.status_code, 200)
        self.assertTrue(res_toggle2.get_json()["data"]["ativo"])

        # 5. Test Ping manual com mock
        with patch("requests.post") as mock_ping:
            mock_ping.return_value.status_code = 200
            mock_ping.return_value.text = '{"ok":true}'
            res_ping = self.client.post(f"/crm/api/webhooks/{wh_id}/test")
            self.assertEqual(res_ping.status_code, 200)
            self.assertTrue(res_ping.get_json()["success"])

        # 6. Remoção do Webhook
        res_del = self.client.delete(f"/crm/api/webhooks/{wh_id}")
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.get_json()["success"])

        # Confirma que foi excluído
        wh_check = CrmWebhook.query.get(wh_id)
        self.assertIsNone(wh_check)

    def test_api_create_webhook_validation_errors(self):
        """Validação de payload incorreto na criação de webhook (URL inválida ou nome vazio)."""
        self._login(self.admin_user)

        # Sem URL
        res = self.client.post("/crm/api/webhooks", json={"nome": "Sem URL"})
        self.assertEqual(res.status_code, 400)

        # Sem Nome
        res2 = self.client.post("/crm/api/webhooks", json={"url": "https://api.valida.com"})
        self.assertEqual(res2.status_code, 400)

        # URL sem protocolo http/https
        res3 = self.client.post("/crm/api/webhooks", json={"nome": "URL Invalida", "url": "ftp://invalido.com"})
        self.assertEqual(res3.status_code, 400)

    def test_api_get_webhook_logs(self):
        """GET /crm/api/webhooks/logs retorna histórico estruturado de entregas."""
        self._login(self.admin_user)

        log1 = CrmWebhookLog(
            evento="deal.won",
            status_code=200,
            sucesso=True,
            tempo_ms=120
        )
        log2 = CrmWebhookLog(
            evento="deal.lost",
            status_code=502,
            sucesso=False,
            tempo_ms=3500
        )
        db.session.add_all([log1, log2])
        db.session.commit()

        res = self.client.get("/crm/api/webhooks/logs?limit=10")
        self.assertEqual(res.status_code, 200)
        logs = res.get_json()["data"]
        self.assertGreaterEqual(len(logs), 2)
        eventos = [l["evento"] for l in logs]
        self.assertIn("deal.won", eventos)
        self.assertIn("deal.lost", eventos)


if __name__ == "__main__":
    unittest.main()
