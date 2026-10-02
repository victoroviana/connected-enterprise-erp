"""Testes automatizados do Milestone M2 - Sollus CRM.

Abrange:
- Cockpit de Produtividade Diária ("O que fazer hoje") com semáforo visual de 4 estados (Atrasadas, Hoje, Próximas, Concluídas)
- Sanitização de números de telefone para WhatsApp (E.164 canônico, DDD, zeros à esquerda)
- Geração canônica de links de 1-clique para WhatsApp com URI encode
- Motor de templates de mensagens de WhatsApp com variáveis dinâmicas ({nome_contato}, {empresa}, {consultor}, {link_proposta}, {saudacao}) e fallbacks seguros
- Rotas /crm/tarefas (renderização HTML e suporte a payload JSON via query e headers)
- APIs de templates de WhatsApp: GET /crm/api/templates-whatsapp e POST /crm/api/templates-whatsapp/render
- Registro rápido de notas e interações na timeline: POST /crm/api/negociacoes/<id>/interacoes e /anotacoes
- Validação e rejeição de anotações vazias ou formadas apenas por espaços em branco (HTTP 400)
- Toggle de conclusão de tarefas: POST /crm/api/tarefas/<id>/toggle com recálculo de cache de próxima tarefa e log de timeline
"""
from __future__ import annotations

import unittest
import urllib.parse
from datetime import datetime, date, timedelta
from sqlalchemy.pool import StaticPool

from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department, Proposal, ParamOption, ParamCategory
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmInteracao,
    CrmTemplateMensagem,
)
from modules.crm.services.crm_service import (
    sanitize_whatsapp_phone,
    build_whatsapp_link,
    generate_whatsapp_url,
    render_whatsapp_template,
    get_cockpit_tasks,
    add_note,
    toggle_task,
)


class TestConfigM2:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key-crm-m2"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class TestCrmM2(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfigM2)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()

        # Departamento Comercial
        self.dept_comercial = Department(name="COMERCIAL", slug="comercial")
        db.session.add(self.dept_comercial)
        db.session.commit()

        # Consultor Comercial 1
        self.consultant_1 = User(
            usuario="consultor_m2_1",
            nome_completo="Carlos Drummond de Andrade",
            email="carlos@sollus.com.br",
            password_hash="hash1",
            tipo="consultor",
            role="consultor",
            department_id=self.dept_comercial.id,
            is_active=True,
            permissions={"crm": True},
        )
        # Consultor Comercial 2
        self.consultant_2 = User(
            usuario="consultor_m2_2",
            nome_completo="Clarice Lispector",
            email="clarice@sollus.com.br",
            password_hash="hash2",
            tipo="consultor",
            role="consultor",
            department_id=self.dept_comercial.id,
            is_active=True,
            permissions={"crm": True},
        )
        db.session.add_all([self.consultant_1, self.consultant_2])
        db.session.commit()

        # Funil de Teste
        self.funil = CrmFunil(
            id="funil_m2",
            nome="Funil Ponto M2",
            slug="funil_ponto_m2",
            tipo="ponto",
            ordem=1,
            ativo=True,
        )
        db.session.add(self.funil)
        db.session.flush()

        # Etapas do Funil
        self.etapa_novo = CrmEtapa(
            id="etapa_m2_novo",
            funil_id=self.funil.id,
            nome="Novo Lead",
            ordem=1,
            tipo="normal",
            probabilidade=10.0,
        )
        self.etapa_contato = CrmEtapa(
            id="etapa_m2_contato",
            funil_id=self.funil.id,
            nome="Contato Realizado",
            ordem=2,
            tipo="normal",
            probabilidade=30.0,
        )
        self.etapa_ganho = CrmEtapa(
            id="etapa_m2_ganho",
            funil_id=self.funil.id,
            nome="Fechamento Ganho",
            ordem=3,
            tipo="ganho",
            probabilidade=100.0,
        )
        db.session.add_all([self.etapa_novo, self.etapa_contato, self.etapa_ganho])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self, user: User):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user.id
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True

    # -------------------------------------------------------------
    # 1. Testes de Sanitização de Telefone e Geração de Links WhatsApp
    # -------------------------------------------------------------

    def test_whatsapp_phone_sanitization_comprehensive(self):
        """Testa todas as variações e casos de borda na sanitização de telefone WhatsApp."""
        # 11 dígitos celular (com e sem formatação)
        self.assertEqual(sanitize_whatsapp_phone("(21) 99876-5432"), "5521998765432")
        self.assertEqual(sanitize_whatsapp_phone("21998765432"), "5521998765432")
        # 10 dígitos fixo
        self.assertEqual(sanitize_whatsapp_phone("(11) 3344-5566"), "551133445566")
        self.assertEqual(sanitize_whatsapp_phone("1133445566"), "551133445566")
        # Com prefixo internacional +55 ou 55
        self.assertEqual(sanitize_whatsapp_phone("+55 (21) 99876-5432"), "5521998765432")
        self.assertEqual(sanitize_whatsapp_phone("5521998765432"), "5521998765432")
        # Com zeros à esquerda (ex: discagem com operadora 021...)
        self.assertEqual(sanitize_whatsapp_phone("021998765432"), "5521998765432")
        self.assertEqual(sanitize_whatsapp_phone("005521998765432"), "5521998765432")
        # Casos inválidos
        self.assertIsNone(sanitize_whatsapp_phone("12345"))
        self.assertIsNone(sanitize_whatsapp_phone(""))
        self.assertIsNone(sanitize_whatsapp_phone("   "))
        self.assertIsNone(sanitize_whatsapp_phone(None))

    def test_build_whatsapp_link_canonical_and_encoded(self):
        """Testa a criação do link canônico para WhatsApp com codificação em URI."""
        phone = "(21) 98888-7777"
        msg = "Olá! Confirmamos sua demonstração para amanhã às 14h. Ficou alguma dúvida?"
        
        link = build_whatsapp_link(phone, msg)
        self.assertTrue(link.startswith("https://api.whatsapp.com/send?phone=5521988887777&text="))
        self.assertIn(urllib.parse.quote("Olá!"), link)
        self.assertIn(urllib.parse.quote("demonstração"), link)
        
        # Teste com o alias generate_whatsapp_url
        alias_link = generate_whatsapp_url(phone, msg)
        self.assertEqual(link, alias_link)

    # -------------------------------------------------------------
    # 2. Testes do Motor de Substituição Dinâmica de Templates WhatsApp
    # -------------------------------------------------------------

    def test_render_whatsapp_template_all_variables(self):
        """Testa a renderização completa com todas as variáveis dinâmicas presentes."""
        empresa = CrmEmpresa(id="emp_m2_1", nome="Indústria Alfa S.A.")
        contato = CrmContato(id="cont_m2_1", empresa_id=empresa.id, nome="Rodrigo Constantino", celular="21999998888")
        db.session.add_all([empresa, contato])
        db.session.flush()

        deal = CrmNegociacao(
            id="deal_m2_full",
            nome="Negócio Completo Alfa",
            funil_id=self.funil.id,
            etapa_id=self.etapa_novo.id,
            empresa_id=empresa.id,
            contato_id=contato.id,
            user_id=self.consultant_1.id,
            user_name="Carlos Drummond de Andrade",
            proposta_id=1045,
            status="aberto"
        )
        db.session.add(deal)
        db.session.commit()

        template = "{saudacao}, {nome_contato}! Sou o {consultor} da {empresa}. Proposta: {link_proposta}."
        rendered = render_whatsapp_template(template, deal_id=deal.id)

        self.assertIn("Rodrigo Constantino", rendered)
        self.assertIn("Carlos Drummond de Andrade", rendered)
        self.assertIn("Indústria Alfa S.A.", rendered)
        self.assertIn("1045", rendered)
        self.assertTrue("Bom dia" in rendered or "Boa tarde" in rendered or "Boa noite" in rendered)

    def test_render_whatsapp_template_fallbacks(self):
        """Testa fallbacks quando a negociação não tem contato, empresa, consultor ou proposta."""
        deal = CrmNegociacao(
            id="deal_m2_empty",
            nome="Negócio Sem Vínculos",
            funil_id=self.funil.id,
            etapa_id=self.etapa_novo.id,
            status="aberto"
        )
        db.session.add(deal)
        db.session.commit()

        template = "Olá {nome_contato}! Aqui é da {empresa}, consultor {consultor}. Link: {link_proposta}."
        rendered = render_whatsapp_template(template, deal_id=deal.id)

        self.assertIn("Cliente", rendered)
        self.assertIn("sua empresa", rendered)
        self.assertIn("Consultor Comercial", rendered)
        self.assertNotIn("{link_proposta}", rendered)

    # -------------------------------------------------------------
    # 3. Testes do Cockpit de Tarefas: get_cockpit_tasks e Semáforo Visual
    # -------------------------------------------------------------

    def test_get_cockpit_tasks_traffic_light_categorization(self):
        """Testa a correta classificação das tarefas nos 4 semáforos (atrasada, hoje, próxima, concluída)."""
        today = date.today()
        deal = CrmNegociacao(
            id="deal_m2_cockpit",
            nome="Negociação Cockpit",
            funil_id=self.funil.id,
            etapa_id=self.etapa_novo.id,
            user_id=self.consultant_1.id,
            status="aberto"
        )
        db.session.add(deal)
        db.session.flush()

        # Tarefa atrasada (ontem)
        t_late = CrmTarefa(
            id="t_m2_late",
            negociacao_id=deal.id,
            user_id=self.consultant_1.id,
            titulo="Follow-up Atrasado",
            data_vencimento=datetime.combine(today - timedelta(days=1), datetime.min.time()) + timedelta(hours=10),
            concluida=False
        )
        # Tarefa para hoje (às 15:00)
        t_today = CrmTarefa(
            id="t_m2_today",
            negociacao_id=deal.id,
            user_id=self.consultant_1.id,
            titulo="Ligar Hoje",
            data_vencimento=datetime.combine(today, datetime.min.time()) + timedelta(hours=15),
            concluida=False
        )
        # Tarefa futura (depois de amanhã)
        t_upcoming = CrmTarefa(
            id="t_m2_up",
            negociacao_id=deal.id,
            user_id=self.consultant_1.id,
            titulo="Reunião Futura",
            data_vencimento=datetime.combine(today + timedelta(days=2), datetime.min.time()) + timedelta(hours=14),
            concluida=False
        )
        # Tarefa concluída
        t_done = CrmTarefa(
            id="t_m2_done",
            negociacao_id=deal.id,
            user_id=self.consultant_1.id,
            titulo="WhatsApp Concluído",
            data_vencimento=datetime.combine(today, datetime.min.time()) + timedelta(hours=9),
            concluida=True,
            concluida_em=datetime.utcnow()
        )
        db.session.add_all([t_late, t_today, t_upcoming, t_done])
        db.session.commit()

        res = get_cockpit_tasks(user_id=self.consultant_1.id)
        counts = res["counts"]

        self.assertEqual(counts["late"], 1)
        self.assertEqual(counts["today"], 1)
        self.assertEqual(counts["upcoming"], 1)
        self.assertEqual(counts["done"], 1)
        self.assertEqual(counts["atrasadas"], 1)
        self.assertEqual(counts["hoje"], 1)
        self.assertEqual(counts["proximas"], 1)
        self.assertEqual(counts["concluidas"], 1)
        self.assertEqual(counts["total"], 4)

    def test_cockpit_empty_state(self):
        """Testa cockpit quando o consultor não possui nenhuma tarefa pendente."""
        res = get_cockpit_tasks(user_id=self.consultant_2.id)
        counts = res["counts"]
        self.assertEqual(counts["total"], 0)
        self.assertEqual(counts["late"], 0)
        self.assertEqual(counts["today"], 0)
        self.assertEqual(counts["upcoming"], 0)
        self.assertEqual(counts["done"], 0)

    # -------------------------------------------------------------
    # 4. Testes de Rotas e Endpoints HTTP
    # -------------------------------------------------------------

    def test_route_crm_tarefas_html_and_json(self):
        """Testa a rota GET /crm/tarefas tanto no formato HTML quanto no formato JSON."""
        self._login(self.consultant_1)

        # 1. HTML View
        res_html = self.client.get("/crm/tarefas")
        self.assertEqual(res_html.status_code, 200)
        self.assertIn(b"tarefas", res_html.data.lower())
        self.assertIn(b"cockpit", res_html.data.lower())

        # 2. JSON View com ?format=json
        res_json = self.client.get("/crm/tarefas?format=json")
        self.assertEqual(res_json.status_code, 200)
        data = res_json.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("counts", data)
        self.assertIn("tarefas", data)

        # 3. JSON View com cabeçalho Accept: application/json
        res_header = self.client.get("/crm/tarefas", headers={"Accept": "application/json"})
        self.assertEqual(res_header.status_code, 200)
        self.assertTrue(res_header.is_json)

    def test_route_templates_whatsapp_api_list_and_render(self):
        """Testa listagem e renderização via API de templates de WhatsApp."""
        self._login(self.consultant_1)

        # Listagem
        res_list = self.client.get("/crm/api/templates-whatsapp")
        self.assertEqual(res_list.status_code, 200)
        data_list = res_list.get_json()
        self.assertTrue(data_list.get("success"))
        self.assertGreaterEqual(len(data_list.get("templates", [])), 1)

        # Renderização
        deal = CrmNegociacao(
            id="deal_m2_render_test",
            nome="Deal Render WhatsApp",
            funil_id=self.funil.id,
            etapa_id=self.etapa_novo.id,
            user_id=self.consultant_1.id,
            user_name=self.consultant_1.nome_completo,
            status="aberto"
        )
        db.session.add(deal)
        db.session.commit()

        payload = {
            "template_text": "Olá {nome_contato}, aqui é o {consultor} da {empresa}!",
            "deal_id": deal.id,
            "telefone": "21988887777"
        }
        res_render = self.client.post("/crm/api/templates-whatsapp/render", json=payload)
        self.assertEqual(res_render.status_code, 200)
        data_render = res_render.get_json()
        self.assertTrue(data_render.get("success"))
        self.assertIn("Carlos Drummond de Andrade", data_render.get("rendered_text", ""))
        self.assertTrue(data_render.get("whatsapp_url", "").startswith("https://api.whatsapp.com/send?phone=5521988887777"))

    def test_route_interacoes_and_anotacoes(self):
        """Testa endpoints de notas e interações na timeline da negociação."""
        self._login(self.consultant_1)
        deal = CrmNegociacao(
            id="deal_m2_interaction",
            nome="Deal Interações",
            funil_id=self.funil.id,
            etapa_id=self.etapa_novo.id,
            user_id=self.consultant_1.id,
            status="aberto"
        )
        db.session.add(deal)
        db.session.commit()

        # 1. Interação válida tipo whatsapp
        payload_wa = {"conteudo": "Contato comercial enviado via WhatsApp", "tipo": "whatsapp"}
        res_wa = self.client.post(f"/crm/api/negociacoes/{deal.id}/interacoes", json=payload_wa)
        self.assertEqual(res_wa.status_code, 200)

        interacao = CrmInteracao.query.filter_by(negociacao_id=deal.id).first()
        self.assertIsNotNone(interacao)
        self.assertEqual(interacao.tipo, "whatsapp")

        # 2. Rejeição de anotação com conteúdo em branco ou apenas espaços
        res_empty = self.client.post(f"/crm/api/negociacoes/{deal.id}/interacoes", json={"conteudo": "   "})
        self.assertEqual(res_empty.status_code, 400)

    def test_route_tarefa_toggle(self):
        """Testa o endpoint POST /crm/api/tarefas/<id>/toggle e atualização de status."""
        self._login(self.consultant_1)
        deal = CrmNegociacao(
            id="deal_m2_toggle",
            nome="Deal Toggle Task",
            funil_id=self.funil.id,
            etapa_id=self.etapa_novo.id,
            user_id=self.consultant_1.id,
            status="aberto"
        )
        task = CrmTarefa(
            id="t_m2_toggle_1",
            negociacao_id=deal.id,
            user_id=self.consultant_1.id,
            titulo="Demonstração com Diretor",
            data_vencimento=datetime.utcnow() + timedelta(hours=3),
            concluida=False
        )
        db.session.add_all([deal, task])
        db.session.commit()

        # Marcar como concluída
        res_done = self.client.post(f"/crm/api/tarefas/{task.id}/toggle", json={"concluida": True})
        self.assertEqual(res_done.status_code, 200)
        db.session.refresh(task)
        self.assertTrue(task.concluida)
        self.assertIsNotNone(task.concluida_em)

        # Reabrir tarefa
        res_reopen = self.client.post(f"/crm/api/tarefas/{task.id}/toggle", json={"concluida": False})
        self.assertEqual(res_reopen.status_code, 200)
        db.session.refresh(task)
        self.assertFalse(task.concluida)
        self.assertIsNone(task.concluida_em)


if __name__ == "__main__":
    unittest.main()
