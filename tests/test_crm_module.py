"""Testes automatizados do Módulo Sollus CRM."""
import unittest
from datetime import datetime, timedelta
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
    CrmInteracao,
    CrmLeadMarketing
)


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key-crm"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class TestCrmModule(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()

        # Criar departamento Comercial
        self.dept_comercial = Department.query.filter_by(slug="comercial").first()
        if not self.dept_comercial:
            self.dept_comercial = Department(name="COMERCIAL", slug="comercial")
            db.session.add(self.dept_comercial)
            db.session.commit()

        # Criar Consultor
        self.user = User(
            usuario="consultor_crm",
            nome_completo="Vendedor Teste",
            email="vendedor@sollus.com",
            password_hash="hash_teste",
            tipo="consultor",
            role="usuario",
            department_id=self.dept_comercial.id,
            permissions={"crm": True, "propostas": True},
        )
        db.session.add(self.user)
        db.session.commit()

        # Criar Funil e Etapas de Teste
        self.funil = CrmFunil(
            id="funil_teste",
            nome="Funil de Teste",
            slug="funil_ponto",
            tipo="ponto",
            ordem=1,
            ativo=True
        )
        db.session.add(self.funil)
        db.session.flush()

        self.etapa1 = CrmEtapa(
            id="etapa_novo",
            funil_id=self.funil.id,
            nome="Novo",
            ordem=1,
            tipo="normal"
        )
        self.etapa2 = CrmEtapa(
            id="etapa_qualif",
            funil_id=self.funil.id,
            nome="Qualificação",
            ordem=2,
            tipo="normal"
        )
        self.etapa_venda = CrmEtapa(
            id="etapa_ganho",
            funil_id=self.funil.id,
            nome="Vendido",
            ordem=3,
            tipo="venda"
        )
        db.session.add_all([self.etapa1, self.etapa2, self.etapa_venda])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(self.user.id)
            sess["user_id"] = self.user.id
            sess["tipo"] = "consultor"

    def test_crm_index_redirects_to_active_funil(self):
        self._login()
        res = self.client.get("/crm/")
        self.assertEqual(res.status_code, 302)
        self.assertTrue("/crm/funil/funil_teste" in res.location)

    def test_crm_kanban_renders(self):
        self._login()
        res = self.client.get(f"/crm/funil/{self.funil.id}")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Funil de Teste".encode(), res.data)
        self.assertIn("crm-kanban-wrapper".encode(), res.data)

    def test_crm_lead_capture_webhook(self):
        # Universal Webhook / Elementor / WordPress Form Ingestion (Opção A)
        payload = {
            "nome": "Cliente Ingestao Teste",
            "email": "ingestao@empresa.com",
            "telefone": "(21) 98888-7777",
            "empresa": "Empresa Ingestao SA",
            "origem": "Formulário Site",
            "filial": "RJ",
            "mensagem": "Gostaria de cotar 2 relógios de ponto biométricos"
        }
        res = self.client.post("/crm/api/leads/captura", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")

        # Verificar se inseriu no banco
        deal = CrmNegociacao.query.filter(CrmNegociacao.nome.like("%Empresa Ingestao SA%")).first()
        self.assertIsNotNone(deal)
        self.assertEqual(deal.origem, "Formulário Site")
        self.assertEqual(deal.filial, "RJ")

        empresa = CrmEmpresa.query.filter_by(nome="Empresa Ingestao SA").first()
        self.assertIsNotNone(empresa)

        contato = CrmContato.query.filter_by(email="ingestao@empresa.com").first()
        self.assertIsNotNone(contato)

    def test_crm_move_stage(self):
        self._login()
        # Criar uma negociação
        deal = CrmNegociacao(
            id="deal_123",
            nome="Negociacao 1",
            funil_id=self.funil.id,
            etapa_id=self.etapa1.id,
            valor_total=1500.0,
            status="aberto"
        )
        db.session.add(deal)
        db.session.commit()

        # Mover para etapa 2
        res = self.client.post(
            f"/crm/api/negociacoes/{deal.id}/mover",
            json={"new_etapa_id": self.etapa2.id}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))

        # Checar no banco
        updated_deal = CrmNegociacao.query.get(deal.id)
        self.assertEqual(updated_deal.etapa_id, self.etapa2.id)

    def test_crm_deal_details_and_notes(self):
        self._login()
        deal = CrmNegociacao(
            id="deal_456",
            nome="Negociacao 360",
            funil_id=self.funil.id,
            etapa_id=self.etapa1.id,
            valor_total=3200.0,
            status="aberto"
        )
        db.session.add(deal)
        db.session.commit()

        # Adicionar nota
        res_note = self.client.post(
            f"/crm/api/negociacoes/{deal.id}/anotacoes",
            json={"conteudo": "Cliente solicitou desconto à vista"}
        )
        self.assertEqual(res_note.status_code, 200)
        self.assertTrue(res_note.get_json().get("success"))

        # Obter detalhes 360
        res_det = self.client.get(f"/crm/api/negociacoes/{deal.id}/detalhes")
        self.assertEqual(res_det.status_code, 200)
        det_data = res_det.get_json()["data"]
        self.assertEqual(det_data["deal"]["nome"], "Negociacao 360")
        self.assertEqual(len(det_data["interacoes"]), 1)
        self.assertIn("desconto à vista", det_data["interacoes"][0]["conteudo"])

    def test_crm_tasks_scheduling_and_toggle(self):
        self._login()
        deal = CrmNegociacao(
            id="deal_789",
            nome="Negociacao Tarefa",
            funil_id=self.funil.id,
            etapa_id=self.etapa1.id,
            status="aberto"
        )
        db.session.add(deal)
        db.session.commit()

        # Criar tarefa
        dt_venc = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%dT15:00")
        res_task = self.client.post(
            f"/crm/api/negociacoes/{deal.id}/tarefas",
            json={
                "titulo": "Ligar para o diretor",
                "tipo": "ligacao",
                "data_vencimento": dt_venc
            }
        )
        self.assertEqual(res_task.status_code, 200)
        task_data = res_task.get_json()["tarefa"]
        task_id = task_data["id"]

        # Concluir tarefa
        res_toggle = self.client.post(
            f"/crm/api/tarefas/{task_id}/toggle",
            json={"concluida": True}
        )
        self.assertEqual(res_toggle.status_code, 200)
        self.assertTrue(res_toggle.get_json()["tarefa"]["concluida"])

    def test_crm_mark_won_and_lost(self):
        self._login()
        deal = CrmNegociacao(
            id="deal_win_lose",
            nome="Negociacao Ganha e Perdida",
            funil_id=self.funil.id,
            etapa_id=self.etapa1.id,
            valor_total=5000.0,
            status="aberto"
        )
        db.session.add(deal)
        db.session.commit()

        # Ganhar venda
        res_won = self.client.post(f"/crm/api/negociacoes/{deal.id}/ganhar")
        self.assertEqual(res_won.status_code, 200)
        self.assertTrue(res_won.get_json().get("success"))

        deal_db = CrmNegociacao.query.get(deal.id)
        self.assertEqual(deal_db.status, "ganho")
        self.assertIsNotNone(deal_db.closed_at)

        # Perder venda
        res_lost = self.client.post(f"/crm/api/negociacoes/{deal.id}/perder", json={"categoria": "preco", "motivo": "Preço alto"})
        self.assertEqual(res_lost.status_code, 200)
        self.assertTrue(res_lost.get_json().get("success"))

        deal_db = CrmNegociacao.query.get(deal.id)
        self.assertEqual(deal_db.status, "perdido")
        self.assertEqual(deal_db.motivo_perda, "Preço alto")

    def test_crm_views_empresas_contatos_leads_metricas(self):
        self._login()
        # Empresas
        res_emp = self.client.get("/crm/empresas")
        self.assertEqual(res_emp.status_code, 200)

        # Contatos
        res_ct = self.client.get("/crm/contatos")
        self.assertEqual(res_ct.status_code, 200)

        # Leads
        res_ld = self.client.get("/crm/leads")
        self.assertEqual(res_ld.status_code, 200)

        # Métricas
        res_met = self.client.get("/crm/metricas")
        self.assertEqual(res_met.status_code, 200)


if __name__ == "__main__":
    unittest.main()
