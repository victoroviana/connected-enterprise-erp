"""Testes automatizados da Rede de Empresas Parceiras e Histórico de Serviços."""
import unittest
from datetime import date
from decimal import Decimal
from sqlalchemy.pool import StaticPool

from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department, EmpresaParceira, ParceiroServicoHistorico


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class TestEmpresasParceiras(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.dept_comercial = Department.query.filter_by(slug="comercial").first()
        if not self.dept_comercial:
            self.dept_comercial = Department(name="COMERCIAL", slug="comercial")
            db.session.add(self.dept_comercial)
            db.session.commit()

        self.user = User(
            usuario="gestor_vendas",
            nome_completo="Gestor Comercial",
            email="gestor@sollus.com",
            password_hash="hash",
            tipo="gestor",
            role="gestor",
            department_id=self.dept_comercial.id,
            permissions={"comercial_parceiros": True, "propostas": True},
        )
        db.session.add(self.user)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self, user):
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["usuario_id"] = user.id
            sess["user_id"] = user.id
            sess["_fresh"] = True

    def test_cadastrar_parceiro_e_filtrar_por_uf(self):
        self._login(self.user)

        # Cadastro de Parceiro na Bahia
        payload = {
            "razao_social": "Bahia Segurança e Catracas Eireli",
            "nome_fantasia": "Bahia Acesso Chapada",
            "cnpj": "12.345.678/0001-90",
            "responsavel": "Jorge Amado",
            "telefone": "(75) 3331-1234",
            "whatsapp": "(75) 98888-7777",
            "email": "contato@bahiaacesso.com.br",
            "estado": "BA",
            "cidade": "Lençóis",
            "regiao_atendimento": "Atende Lençóis, Seabra e toda a Chapada Diamantina",
            "especialidades": "Catracas Henry Lumen, Relógio de Ponto iDClass, Secullum",
            "status": "ativo",
            "observacoes": "Deslocamento R$ 1,50 por km.",
        }
        res = self.client.post("/comercial/parceiros/novo", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        parceiro = EmpresaParceira.query.filter_by(cidade="Lençóis").first()
        self.assertIsNotNone(parceiro)
        self.assertEqual(parceiro.estado, "BA")
        self.assertEqual(parceiro.responsavel, "Jorge Amado")

        # Filtrar por UF = BA
        res_filtro_ba = self.client.get("/comercial/parceiros?uf=BA")
        self.assertEqual(res_filtro_ba.status_code, 200)
        self.assertIn("Bahia Acesso Chapada".encode("utf-8"), res_filtro_ba.data)

        # Filtrar por UF = SP -> Não deve encontrar
        res_filtro_sp = self.client.get("/comercial/parceiros?uf=SP")
        self.assertEqual(res_filtro_sp.status_code, 200)
        self.assertNotIn("Bahia Acesso Chapada".encode("utf-8"), res_filtro_sp.data)

    def test_historico_servicos_e_recalculo_estrelas(self):
        self._login(self.user)

        parceiro = EmpresaParceira(
            razao_social="Prestadora Teste",
            nome_fantasia="Parceiro Teste",
            estado="SC",
            cidade="Florianópolis",
            status="ativo",
        )
        db.session.add(parceiro)
        db.session.commit()

        # Registrar primeiro serviço com nota 5 estrelas
        payload1 = {
            "cliente_nome": "Hotel Beira Mar",
            "cliente_cidade": "Florianópolis",
            "cliente_uf": "SC",
            "data_servico": "2026-09-10",
            "tipo_servico": "Instalação de Catraca",
            "equipamento_modelo": "Catraca Henry Lumen",
            "os_codigo": "OS 998877",
            "tecnico_parceiro": "Técnico Lucas",
            "valor_servico": "450,00",
            "avaliacao_nota": "5",
            "avaliacao_parecer": "Instalação executada no prazo e cliente muito satisfeito.",
        }
        res1 = self.client.post(f"/comercial/parceiros/{parceiro.id}/servicos/novo", data=payload1, follow_redirects=True)
        self.assertEqual(res1.status_code, 200)

        db.session.refresh(parceiro)
        self.assertEqual(parceiro.total_atendimentos, 1)
        self.assertEqual(parceiro.avaliacao_media, 5.0)

        # Registrar segundo serviço com nota 3 estrelas
        payload2 = {
            "cliente_nome": "Condomínio Horizonte",
            "cliente_cidade": "São José",
            "cliente_uf": "SC",
            "data_servico": "2026-09-15",
            "tipo_servico": "Manutenção Corretiva",
            "equipamento_modelo": "REP iDClass",
            "avaliacao_nota": "3",
            "avaliacao_parecer": "Atrasou 2 horas na chegada, mas resolveu o defeito da placa.",
        }
        res2 = self.client.post(f"/comercial/parceiros/{parceiro.id}/servicos/novo", data=payload2, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)

        db.session.refresh(parceiro)
        self.assertEqual(parceiro.total_atendimentos, 2)
        self.assertEqual(parceiro.avaliacao_media, 4.0)  # (5 + 3) / 2 = 4.0

        # Ver detalhes da página HTML com histórico
        res_detalhe = self.client.get(f"/comercial/parceiros/{parceiro.id}")
        self.assertEqual(res_detalhe.status_code, 200)
        self.assertIn("Hotel Beira Mar".encode("utf-8"), res_detalhe.data)
        self.assertIn("Condomínio Horizonte".encode("utf-8"), res_detalhe.data)
        self.assertIn("4.0".encode("utf-8"), res_detalhe.data)

        # Excluir o serviço de nota 3 -> média volta para 5.0
        servico2 = ParceiroServicoHistorico.query.filter_by(cliente_nome="Condomínio Horizonte").first()
        res_del_servico = self.client.post(f"/comercial/parceiros/servicos/{servico2.id}/excluir", follow_redirects=True)
        self.assertEqual(res_del_servico.status_code, 200)

        db.session.refresh(parceiro)
        self.assertEqual(parceiro.total_atendimentos, 1)
        self.assertEqual(parceiro.avaliacao_media, 5.0)

    def test_api_busca_parceiros(self):
        self._login(self.user)

        p1 = EmpresaParceira(razao_social="Eletro Bahia", nome_fantasia="Eletro Bahia", estado="BA", cidade="Salvador", especialidades="Catraca, Henry")
        p2 = EmpresaParceira(razao_social="Paulista Catracas", nome_fantasia="Paulista Catracas", estado="SP", cidade="Campinas", especialidades="Control iD")
        db.session.add_all([p1, p2])
        db.session.commit()

        # Busca por UF
        res = self.client.get("/comercial/api/parceiros/busca?uf=BA")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["cidade"], "Salvador")

        # Busca por especialidade "Control iD"
        res2 = self.client.get("/comercial/api/parceiros/busca?q=control")
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertEqual(len(data2["items"]), 1)
        self.assertEqual(data2["items"][0]["cidade"], "Campinas")
