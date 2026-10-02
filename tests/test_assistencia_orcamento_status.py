import unittest
from datetime import date
from sqlalchemy.pool import StaticPool
from extensions import db
from platform_app import create_app
from modules.propostas.models import User
from modules.suporte.models import OrcamentoStatus
from modules.suporte.blueprints.assistencia import _cobranca_blink_class

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

class TestOrcamentoStatusAprovado(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.app.config["_audit_logs_table_available"] = True

        self.user = User(
            usuario="admin_tester",
            nome_completo="Admin Tester",
            email="admin@example.com",
            password_hash="hash",
            tipo="admin",
            role="admin",
        )
        db.session.add(self.user)
        db.session.flush()
        self.user_id = self.user.id

        self.orcamento = OrcamentoStatus(
            unidade="SOLLUS SP",
            responsavel="Admin Tester",
            cliente="Empresa ABC",
            numero_proposta="SP9999",
            tipo_visita="OFICINA",
            equipamento="Equip Teste",
            valor=1250.50,
            status="AGUARDANDO",
            data_envio=date(2026, 8, 20),
            ultima_cobranca=date(2026, 8, 25),
        )
        db.session.add(self.orcamento)
        db.session.commit()
        self.orcamento_id = self.orcamento.id

        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["usuario_id"] = self.user_id
            sess["_user_id"] = str(self.user_id)
            sess["tipo"] = "admin"

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_aprovar_orcamento_sem_data(self):
        orc = OrcamentoStatus.query.get(self.orcamento_id)
        self.assertEqual(orc.status, "AGUARDANDO")
        self.assertEqual(_cobranca_blink_class(orc.status, orc.ultima_cobranca), "blink-red")

        response = self.client.post(
            f"/assistencia/orcamentos/{self.orcamento_id}/status",
            data={"status": "APROVADO", "dataAprovacao": ""},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        db.session.refresh(orc)
        self.assertEqual(orc.status, "APROVADO")
        self.assertIsNone(orc.data_aprovacao)
        self.assertEqual(_cobranca_blink_class(orc.status, orc.ultima_cobranca), "")

    def test_aprovar_orcamento_com_data(self):
        response = self.client.post(
            f"/assistencia/orcamentos/{self.orcamento_id}/status",
            data={"status": "APROVADO", "dataAprovacao": "2026-09-04"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        orc = OrcamentoStatus.query.get(self.orcamento_id)
        self.assertEqual(orc.status, "APROVADO")
        self.assertEqual(orc.data_aprovacao, date(2026, 9, 4))
        self.assertEqual(_cobranca_blink_class(orc.status, orc.ultima_cobranca), "")

if __name__ == "__main__":
    unittest.main()
