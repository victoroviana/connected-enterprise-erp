import unittest
from datetime import datetime, date
from sqlalchemy.pool import StaticPool
from extensions import db
from platform_app import create_app
from modules.propostas.models import User
from modules.suporte.models import AssistenciaTarefa, AtendimentoSuporte


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


class TestDelayMonitoringFixes(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create admin user
        self.admin_user = User(
            usuario="admin_u",
            nome_completo="Admin User",
            email="admin@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="admin",
            role="admin",
            is_active=True,
            permissions={"chamados": True}
        )
        db.session.add(self.admin_user)
        db.session.commit()

        # Create AssistenciaTarefa (OS Task) with an empty status
        self.os_empty_status = AssistenciaTarefa(
            OS="OS 87506100 SRJ",
            nome="COLEGIO DE APLICACAO FERREIRA DE ALMEIDA LTDA",
            status="",
            data_fim=date(2025, 8, 20),
            data_criacao=date(2025, 8, 10),
            unidade="Rio de Janeiro",
            departamento_responsavel="ASSISTENCIA TECNICA"
        )
        # Create AssistenciaTarefa with normal open status
        self.os_open_status = AssistenciaTarefa(
            OS="OS 11111111 AAA",
            nome="Normal Open Task",
            status="Entrada",
            data_fim=date(2025, 8, 20),
            data_criacao=date(2025, 8, 10),
            unidade="Rio de Janeiro",
            departamento_responsavel="ASSISTENCIA TECNICA"
        )
        db.session.add_all([self.os_empty_status, self.os_open_status])
        db.session.commit()

        # Create AtendimentoSuporte (Support Ticket)
        self.support_call = AtendimentoSuporte(
            cliente="RIO+ SANEAMENTO BL3 S.A",
            status="Em progresso",
            tipo_atendimento="ATENDIMENTO",
            descricao="Support description",
            os_entrada="87506148",
            data_entrada=datetime(2025, 8, 26)
        )
        db.session.add(self.support_call)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login_as(self, user):
        with self.client.session_transaction() as sess:
            sess["usuario_id"] = user.id
            sess["user_id"] = user.id
            sess["_user_id"] = str(user.id)
            sess["tipo"] = user.tipo
            sess["logged_in_user"] = user.nome_completo

    def test_os_empty_status_filtering_bypass(self):
        """Test that searching by os_codigo bypasses status_group = open filter."""
        self.login_as(self.admin_user)

        # 1. Query dashboard without os_codigo, should return only open status task
        response = self.client.get("/assistencia/api/dashboard?status_group=open")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        items = data["items"]
        
        # Verify empty status task is NOT returned, but open status task is
        self.assertTrue(any(x["os"] == "OS 11111111 AAA" for x in items))
        self.assertFalse(any(x["os"] == "OS 87506100 SRJ" for x in items))

        # 2. Query dashboard with os_codigo filter, should return the target task even if status is empty
        response = self.client.get("/assistencia/api/dashboard?status_group=open&os_codigo=OS+87506100+SRJ")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        items = data["items"]
        
        self.assertTrue(any(x["os"] == "OS 87506100 SRJ" for x in items))

    def test_atendimento_id_query_parameter_filtering(self):
        """Test that passing atendimentos?atendimento_id returns only that specific ticket, bypassing default status."""
        self.login_as(self.admin_user)

        # Query atendimentos dashboard API without specific ID (default filter status = 'entrada')
        # Since support_call is 'Em progresso' (which maps to status_key 'atencao' or similar, not 'entrada'),
        # it won't be in the 'entrada' list if we filter by status = 'entrada'.
        response = self.client.get("/admin/suporte/api/atendimentos?status=entrada")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        items = data["items"]
        self.assertFalse(any(x["id"] == self.support_call.id for x in items))

        # Query atendimentos dashboard API passing atendimento_id, should return only that item
        response = self.client.get(f"/admin/suporte/api/atendimentos?status=entrada&atendimento_id={self.support_call.id}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        items = data["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], self.support_call.id)
        self.assertEqual(items[0]["cliente"], "RIO+ SANEAMENTO BL3 S.A")


if __name__ == "__main__":
    unittest.main()
