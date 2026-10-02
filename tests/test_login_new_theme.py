"""Testes de validação da nova tela de login cibernética e do endpoint AJAX."""
import unittest
from platform_app import create_app
from extensions import db
from modules.propostas.models import User
from werkzeug.security import generate_password_hash


class TestNewLoginTheme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Config:
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite://"
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SECRET_KEY = "test-login-key-12345"
            WTF_CSRF_ENABLED = False

        cls.app = create_app(Config)
        with cls.app.app_context():
            db.create_all()
            test_user = User(
                usuario="user_teste",
                nome_completo="Usuário Teste",
                email="teste@sollus.com",
                password_hash=generate_password_hash("senha_correta_123"),
                tipo="admin",
                role="admin",
                is_active=True,
            )
            db.session.add(test_user)
            db.session.commit()

    def setUp(self):
        self.client = self.app.test_client()

    def test_get_login_page_renders_new_cyber_theme(self):
        """Verifica se a rota GET /auth/login renderiza os elementos do novo tema visual."""
        res = self.client.get("/auth/login")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")

        # Verifica componentes do design system oficial
        self.assertIn("Sollus Connected - Login", html)
        self.assertIn("SOLLUS", html)
        self.assertIn("CONNECTED", html)
        self.assertIn("card-laser-scanner", html)
        self.assertIn("login-card-panel", html)
        self.assertIn("exact-btn-submit", html)
        self.assertIn("loginSuccessContainer", html)
        self.assertIn("btnThemeToggle", html)
        self.assertIn("cookieConsentBanner", html)
        self.assertIn("loginLgpdModal", html)
        self.assertIn("sollus:theme", html)

    def test_post_login_ajax_failure(self):
        """Verifica se falha de login via AJAX retorna JSON 401 com mensagem amigável."""
        res = self.client.post(
            "/auth/login_ajax",
            json={"usuario": "user_teste", "senha": "senha_errada_456"},
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("inválidos", data["msg"].lower())

    def test_post_login_ajax_success(self):
        """Verifica se login com sucesso via AJAX retorna JSON com redirect."""
        res = self.client.post(
            "/auth/login_ajax",
            json={"usuario": "user_teste", "senha": "senha_correta_123"},
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("redirect", data)
        self.assertEqual(data["msg"], "Login realizado com sucesso!")

    def test_post_login_traditional_form_success(self):
        """Verifica compatibilidade com envio de formulário POST tradicional (redirect 302)."""
        res = self.client.post(
            "/auth/login",
            data={"usuario": "user_teste", "senha": "senha_correta_123"}
        )
        self.assertEqual(res.status_code, 302)

    def test_get_login_cache_control_headers(self):
        """Verifica se os headers no-cache estão presentes para evitar bfcache com tokens antigos."""
        res = self.client.get("/auth/login")
        self.assertEqual(res.status_code, 200)
        self.assertIn("no-cache", res.headers.get("Cache-Control", ""))
        self.assertIn("no-store", res.headers.get("Cache-Control", ""))
        self.assertEqual(res.headers.get("Pragma"), "no-cache")


class TestLoginCSRFExemption(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class CSRFConfig:
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite://"
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SECRET_KEY = "test-csrf-login-key-9999"
            WTF_CSRF_ENABLED = True

        cls.app = create_app(CSRFConfig)
        with cls.app.app_context():
            db.create_all()
            test_user = User(
                usuario="user_csrf_test",
                nome_completo="Usuário CSRF Test",
                email="csrf_test@sollus.com",
                password_hash=generate_password_hash("senha_correta_123"),
                tipo="admin",
                role="admin",
                is_active=True,
            )
            db.session.add(test_user)
            db.session.commit()

    def setUp(self):
        self.client = self.app.test_client()

    def test_login_ajax_without_csrf_token_succeeds(self):
        """Garante que o endpoint de login_ajax é isento de CSRF e não rejeita requisições legítimas."""
        res = self.client.post(
            "/auth/login_ajax",
            json={"usuario": "user_csrf_test", "senha": "senha_correta_123"},
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])


if __name__ == "__main__":
    unittest.main()
