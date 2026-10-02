import os
import unittest
import json
from io import BytesIO
from sqlalchemy.pool import StaticPool
from platform_app import create_app
from extensions import db
from modules.propostas.models import User, Department

class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-reporte"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }

class TestReportarProblema(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        dept = Department(name="COMERCIAL", slug="comercial")
        db.session.add(dept)
        db.session.commit()

        self.user = User(
            usuario="joao_teste",
            nome_completo="João da Silva",
            email="joao@sollus.com",
            password_hash="hash",
            tipo="consultor",
            role="usuario",
            department_id=dept.id,
            is_active=True,
        )
        db.session.add(self.user)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_reportar_problema_sem_dados(self):
        res = self.client.post("/api/reportar_problema", data={})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["ok"])

    def test_reportar_problema_email_com_print(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["nome"] = self.user.nome_completo
            sess["email"] = self.user.email

        payload = {
            "pagina": "/propostas/nova",
            "acao": "Tentando salvar uma proposta com 3 itens",
            "descricao": "Ao clicar no botão de gerar PDF, apareceu mensagem de erro 500.",
            "canal": "email",
            "print": (BytesIO(b"fake-image-bytes-png"), "screenshot_teste.png")
        }
        res = self.client.post("/api/reportar_problema", data=payload, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("print_", data["image_filename"])
        self.assertTrue(data["image_url"].endswith(".png"))

    def test_reportar_problema_whatsapp_base64(self):
        payload = {
            "pagina": "/estoque",
            "acao": "Consultando equipamentos",
            "descricao": "Botão de exportar relatório não responde.",
            "canal": "whatsapp",
            "print_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        }
        res = self.client.post("/api/reportar_problema", data=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertIsNotNone(data["image_url"])
