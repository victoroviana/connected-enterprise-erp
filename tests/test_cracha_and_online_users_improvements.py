import unittest
import time
import math
import re
from datetime import date
from flask import current_app
from sqlalchemy.pool import StaticPool
from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department

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

class TestCrachaAndOnlineUsersImprovements(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create legacy tables needed for cracha in SQLite in-memory DB with clean syntax
        from modules.cracha.blueprints.cracha import _legacy_cracha_table_statements
        for name, stmt in _legacy_cracha_table_statements():
            clean_stmt = stmt
            if "ENGINE=" in clean_stmt:
                clean_stmt = clean_stmt.split("ENGINE=")[0].strip()
            
            # Clean indices/keys
            start_idx = clean_stmt.find("(")
            end_idx = clean_stmt.rfind(")")
            if start_idx != -1 and end_idx != -1:
                prefix = clean_stmt[:start_idx + 1]
                body = clean_stmt[start_idx + 1:end_idx]
                suffix = clean_stmt[end_idx:]
                parts = [p for p in body.split(",") if not p.strip().upper().startswith("KEY ")]
                clean_stmt = prefix + ",".join(parts) + suffix
                
            clean_stmt = clean_stmt.replace("AUTO_INCREMENT", "")
            clean_stmt = re.sub(r"(?i)enum\([^)]+\)", "text", clean_stmt)
            
            db.session.execute(db.text(clean_stmt))
        db.session.commit()

        # Retrieve existing departments or create them if they do not exist
        self.dept_cracha = Department.query.filter_by(slug="cracha").first()
        if not self.dept_cracha:
            self.dept_cracha = Department(name="CRACHA", slug="cracha")
            db.session.add(self.dept_cracha)

        self.dept_admin = Department.query.filter_by(slug="administracao").first()
        if not self.dept_admin:
            self.dept_admin = Department(name="ADMINISTRACAO", slug="administracao")
            db.session.add(self.dept_admin)

        db.session.commit()

        # Create admin user
        self.admin_user = User(
            usuario="admin_u",
            nome_completo="Admin User",
            email="admin@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="admin",
            role="admin",
            is_active=True,
            department_id=self.dept_admin.id,
        )
        self.admin_user.departments = [self.dept_admin, self.dept_cracha]
        db.session.add(self.admin_user)
        db.session.commit()

        self.client = self.app.test_client()
        self.login_as(self.admin_user)

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

    def test_online_users_empty_state(self):
        """Test online users page when no users are online."""
        # Ensure cache is empty and cannot be written to by before_request
        class DictMock(dict):
            def __setitem__(self, key, value):
                pass
        self.app.online_users_cache = DictMock()
        
        response = self.client.get("/admin/usuarios-online")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Nenhum colaborador online no momento", html)

    def test_online_users_list_and_search(self):
        """Test online users page lists online users and filters via search."""
        # Create a few more active users
        users = []
        for i in range(1, 10):
            u = User(
                usuario=f"user_{i}",
                nome_completo=f"Colaborador Teste {i}",
                email=f"user{i}@sollus.com",
                password_hash="pbkdf2:sha256:dummy",
                tipo="user",
                role="user",
                is_active=True,
                department_id=self.dept_cracha.id
            )
            db.session.add(u)
            users.append(u)
        db.session.commit()

        # Mark them as online in the cache
        cache = {}
        now = time.time()
        for u in users:
            cache[u.id] = now
        # Also mark admin user as online
        cache[self.admin_user.id] = now
        
        self.app.online_users_cache = cache

        # Test listing with pagination (limit 6 per page)
        response = self.client.get("/admin/usuarios-online?page=1")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        # There should be exactly 6 users shown on page 1 + admin or total 6 (since pagination per_page is 6)
        # Let's count how many user-card-col are in the page
        self.assertEqual(html.count("user-card-col"), 6)
        
        # Page 2 should have the rest
        response_page2 = self.client.get("/admin/usuarios-online?page=2")
        html2 = response_page2.get_data(as_text=True)
        self.assertEqual(html2.count("user-card-col"), 4) # 10 total users online (9 created + 1 admin)

        # Test search filter for specific user
        response_search = self.client.get("/admin/usuarios-online?q=Colaborador Teste 5")
        self.assertEqual(response_search.status_code, 200)
        html_search = response_search.get_data(as_text=True)
        self.assertIn("Colaborador Teste 5", html_search)
        self.assertNotIn("Colaborador Teste 1", html_search)
        self.assertEqual(html_search.count("user-card-col"), 1)

    def test_cracha_clientes_view_contains_modal_dependencies(self):
        """Test that the clientes view has the required dropdown data for the modal (ufs, localidades, empresas)."""
        # Populate mock data for the dropdowns
        # Localidades
        db.session.execute(db.text("INSERT INTO ja_prm_localidades (id_pk, localidade) VALUES (1, 'Rio de Janeiro')"))
        # UFs
        db.session.execute(db.text("INSERT INTO ja_sys_ufs (id_pk, estado, sigla) VALUES (1, 'Rio de Janeiro', 'RJ')"))
        # Empresas
        db.session.execute(db.text("INSERT INTO ja_emp_empresas (id_pk, nome, ativo) VALUES (1, 'Empresa Sollus', 1)"))
        db.session.commit()

        # Request client page
        response = self.client.get("/cracha/clientes")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # Verify modal dropdown values are rendered in the HTML
        self.assertIn("Rio de Janeiro", html)
        self.assertIn("Empresa Sollus", html)
        self.assertIn("RJ", html)
        # Verify modal elements exist
        self.assertIn("id=\"modalNovoCliente\"", html)
        self.assertIn("name=\"txtNomeFantasia\"", html)

    def test_photo_cutter_filename_sanitization(self):
        """Test the custom filename sanitization function preserves spaces/accents and removes path/unsafe chars."""
        from modules.cracha.blueprints.cracha import _sanitize_photo_filename

        self.assertEqual(_sanitize_photo_filename("NOME EXEMPLO.JPG"), "NOME EXEMPLO.JPG")
        self.assertEqual(_sanitize_photo_filename("JOÃO DA SILVA.png"), "JOÃO DA SILVA.png")
        self.assertEqual(_sanitize_photo_filename("../../path/injection/file.jpg"), "file.jpg")
        self.assertEqual(_sanitize_photo_filename("file:name*with?invalid<chars>|.png"), "filenamewithinvalidchars.png")

