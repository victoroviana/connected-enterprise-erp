import unittest
from datetime import date
from sqlalchemy.pool import StaticPool
from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Part
from modules.suporte.models import OrcamentoTemplate, AssistenciaOrcamento, OrcamentoStatus, AssistenciaTarefa
from modules.suporte.blueprints.assistencia import ORCAMENTO_UNIDADES

class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False}
    }

class TestAssistenciaOrcamentoManual(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.app.config["_audit_logs_table_available"] = True
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        print("ENGINE URL:", db.engine.url)
        print("TABLES IN DB AFTER CREATE_ALL:", inspector.get_table_names())

        # Seed template
        self.template = OrcamentoTemplate(
            chave="teste_tipo",
            label="Orcamento de Teste",
            table_title="Itens de Teste",
            ativo=True,
            items=[{"name": "Item A", "price": 100.0, "quantity": 1}],
            condicoes=[["Condição 1", "Valor 1"]],
            observacao="Obs teste",
            aceite=["Aceite 1"]
        )
        db.session.add(self.template)

        # Seed user
        self.user = User(
            usuario="test_user",
            nome_completo="Test User",
            email="test@example.com",
            password_hash="hash",
            tipo="admin",
            role="admin",
        )
        db.session.add(self.user)
        db.session.flush()
        self.user_id = self.user.id

        # Seed part in stock
        self.eq = Part(
            id=1,
            name="Produto Teste",
            description="Descricao do produto",
            unit_price=150.0,
            quantity=10
        )
        db.session.add(self.eq)

        db.session.commit()

        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["usuario_id"] = self.user_id
            sess["_user_id"] = str(self.user_id)
            sess["tipo"] = "admin"
        print("USERS IN DB AT END OF SETUP:", User.query.all())

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_gerar_orcamento_manual_sem_os(self):
        print("USERS IN DB AT START OF MANUAL TEST:", User.query.all())
        # Prepare form data simulating creation without OS
        form_data = {
            "tarefa_id": "", # empty/None tarefa_id
            "tipo": "teste_tipo",
            "equip_teste_tipo_0": "1", # equipment id
            "desc_teste_tipo_0": "Produto Teste Desc",
            "qty_teste_tipo_0": "2",
            "unit_teste_tipo_0": "R$ 150,00",
            "disc_teste_tipo_0": "0,00",
            "manual_empresa": "Cliente Teste S/A",
            "manual_cnpj": "12.345.678/0001-99",
            "manual_email": "cliente@example.com",
            "manual_os": "9999 MAN",
            "manual_unidade": "SOLLUS SP",
            "manual_tecnico": "João Técnico",
            "manual_departamento": "OFICINA",
            "manual_descricao": "Aparelho de teste manual",
        }

        response = self.client.post(
            "/assistencia/orcamentos/gerar",
            data=form_data,
            headers={"X-Requested-With": "XMLHttpRequest"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])

        # Verify database record
        orcamentos = AssistenciaOrcamento.query.all()
        self.assertEqual(len(orcamentos), 1)
        orc = orcamentos[0]
        self.assertIsNone(orc.tarefa_id)
        self.assertEqual(orc.total, 300.0) # 2 * 150.0

        # Verify snapshot
        snap = orc.snapshot
        self.assertEqual(snap["empresa"], "Cliente Teste S/A")
        self.assertEqual(snap["cnpj"], "12.345.678/0001-99")
        self.assertEqual(snap["email"], "cliente@example.com")
        self.assertEqual(snap["os"], "9999 MAN")
        self.assertEqual(snap["unidade"], "SOLLUS SP")
        self.assertEqual(snap["tecnico"], "João Técnico")
        self.assertEqual(snap["departamento"], "OFICINA")
        self.assertEqual(snap["descricao"], "Aparelho de teste manual")

        # Verify context built for PDF
        from modules.suporte.services.orcamentos import build_orcamento_context
        context = build_orcamento_context(orc)
        self.assertEqual(context["email"], "cliente@example.com")
        self.assertEqual(context["tecnico"], "João Técnico")
        self.assertEqual(context["departamento"], "OFICINA")

        # Verify OrcamentoStatus
        statuses = OrcamentoStatus.query.all()
        self.assertEqual(len(statuses), 1)
        status = statuses[0]
        self.assertEqual(status.cliente, "Cliente Teste S/A")
        self.assertEqual(status.numero_proposta, "9999 MAN")
        self.assertEqual(status.unidade, "SOLLUS SP")
        self.assertEqual(float(status.valor), 300.0)
        self.assertEqual(status.ordem_servico, "9999 MAN")

    def test_gerar_orcamento_manual_sem_tecnico_default_departamento(self):
        # Prepare form data simulating creation without OS, leaving technician blank and departamento as ASSISTENCIA TECNICA
        form_data = {
            "tarefa_id": "",
            "tipo": "teste_tipo",
            "equip_teste_tipo_0": "1",
            "qty_teste_tipo_0": "1",
            "unit_teste_tipo_0": "R$ 150,00",
            "disc_teste_tipo_0": "0,00",
            "manual_empresa": "Cliente Teste S/A",
            "manual_cnpj": "12.345.678/0001-99",
            "manual_email": "",
            "manual_os": "9999 MAN",
            "manual_unidade": "SOLLUS SP",
            "manual_tecnico": "", # "Sem técnico" or empty
            "manual_departamento": "ASSISTENCIA TECNICA",
            "manual_descricao": "Aparelho de teste manual",
        }

        response = self.client.post(
            "/assistencia/orcamentos/gerar",
            data=form_data,
            headers={"X-Requested-With": "XMLHttpRequest"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])

        # Verify database record
        orc = AssistenciaOrcamento.query.all()[0]
        self.assertEqual(orc.snapshot["tecnico"], "")
        self.assertEqual(orc.snapshot["departamento"], "ASSISTENCIA TECNICA")
        self.assertEqual(orc.snapshot["email"], "")

        # Verify context built for PDF mapping empty tecnico to "Sem técnico"
        from modules.suporte.services.orcamentos import build_orcamento_context
        context = build_orcamento_context(orc)
        self.assertEqual(context["email"], "-")
        self.assertEqual(context["tecnico"], "Sem técnico")
        self.assertEqual(context["departamento"], "ASSISTENCIA TECNICA")

    def test_gerar_orcamento_com_os_legado(self):
        tarefa = AssistenciaTarefa(
            id=123,
            OS="5555 RJ",
            nome="Cliente OS S/A",
            cnpj="99.888.777/0001-66",
            unidade="SOLLUS RJ",
            departamento_responsavel="TI",
            usuario_designado="Maria Tecnica",
            descricao="Defeito OS"
        )
        print("USERS IN DB BEFORE COMMIT:", User.query.all())
        db.session.add(tarefa)
        db.session.commit()
        print("USERS IN DB AFTER COMMIT:", User.query.all())

        form_data = {
            "tarefa_id": "123",
            "tipo": "teste_tipo",
            "equip_teste_tipo_0": "1",
            "desc_teste_tipo_0": "Produto Teste Desc",
            "qty_teste_tipo_0": "1",
            "unit_teste_tipo_0": "R$ 150,00",
            "disc_teste_tipo_0": "0,00",
            # even if manual fields are sent, they should be ignored/overridden by OS details
            "manual_empresa": "Cliente Teste Ignorado",
        }

        response = self.client.post(
            "/assistencia/orcamentos/gerar",
            data=form_data,
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        print("DEBUG RESPONSE IN LEGACY TEST:")
        print("Status Code:", response.status_code)
        print("Headers:", response.headers)
        if response.status_code == 302:
            print("Location:", response.headers.get("Location"))
        else:
            print("JSON:", response.get_json())

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])

        # Verify database record
        orc = AssistenciaOrcamento.query.all()[0]
        self.assertEqual(orc.tarefa_id, 123)

        # Verify snapshot matches OS
        snap = orc.snapshot
        self.assertEqual(snap["empresa"], "Cliente OS S/A")
        self.assertEqual(snap["cnpj"], "99.888.777/0001-66")
        self.assertEqual(snap["os"], "5555 RJ")

        # Verify OrcamentoStatus matches OS
        status = OrcamentoStatus.query.all()[0]
        self.assertEqual(status.cliente, "Cliente OS S/A")
        self.assertEqual(status.numero_proposta, "5555 RJ")

    def test_criar_orcamento_status_manual(self):
        form_data = {
            "dataEnvio": "2026-05-21",
            "tipoVisita": "OFICINA",
            "unidade": "SOLLUS SP",
            "cliente": "Manual Budget Corp",
            "numeroProposta": "PROP-9999",
            "equipamento": "Gerador de Testes",
            "valor": "R$ 1.500,00",
        }
        response = self.client.post(
            "/assistencia/orcamentos/criar",
            data=form_data,
            follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)

        # Verify db insertion
        status = OrcamentoStatus.query.filter_by(numero_proposta="PROP-9999").first()
        self.assertIsNotNone(status)
        self.assertEqual(status.cliente, "Manual Budget Corp")
        self.assertEqual(status.unidade, "SOLLUS SP")
        self.assertEqual(status.tipo_visita, "OFICINA")
        self.assertEqual(status.equipamento, "Gerador de Testes")
        self.assertEqual(float(status.valor), 1500.0)
        self.assertEqual(status.status, "AGUARDANDO")

    def test_salvar_e_excluir_orcamento_template(self):
        # 1. Save new template
        template_data = {
            "chave": "novo_template_teste",
            "label": "Novo Template Teste",
            "table_title": "ITENS DO TESTE",
            "ativo": True,
            "items": [{"name": "Item B", "price": 200.0, "quantity": 1}],
            "condicoes": [["Prazo", "30 dias"]],
            "observacao": "Obs do novo template",
            "aceite": ["Aceito novo"]
        }
        
        response = self.client.post(
            "/assistencia/orcamento-templates/salvar",
            json=template_data
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        
        # Verify it is in database
        template = OrcamentoTemplate.query.filter_by(chave="novo_template_teste").first()
        self.assertIsNotNone(template)
        self.assertEqual(template.label, "Novo Template Teste")
        self.assertEqual(template.table_title, "ITENS DO TESTE")
        self.assertEqual(template.condicoes, [["Prazo", "30 dias"]])
        
        # 2. Exclude template by key
        response_delete = self.client.post(
            "/assistencia/orcamento-templates/excluir-por-chave/novo_template_teste"
        )
        self.assertEqual(response_delete.status_code, 200)
        data_delete = response_delete.get_json()
        self.assertTrue(data_delete["ok"])
        
        # Verify it was deleted
        template_deleted = OrcamentoTemplate.query.filter_by(chave="novo_template_teste").first()
        self.assertIsNone(template_deleted)

if __name__ == "__main__":
    unittest.main()

