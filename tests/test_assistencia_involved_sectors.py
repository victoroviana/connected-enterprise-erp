"""
Integration tests: Estoque and Oficina sectors access to Controle de Equipamentos.

Verifies:
  - _enforce_department_for_status logic (unit test, no HTTP needed)
  - Editing a task without changing status works for ESTOQUE users
  - Changing status to an owned state works for ESTOQUE users
  - Changing status to an unowned state is blocked for ESTOQUE users
"""
import unittest
from datetime import date
from unittest.mock import patch, MagicMock
from sqlalchemy.pool import StaticPool
from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department
from modules.suporte.models import AssistenciaTarefa


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


# ---------------------------------------------------------------------------
# Unit tests for _enforce_department_for_status — no HTTP needed
# ---------------------------------------------------------------------------
class TestEnforceDeptForStatus(unittest.TestCase):
    """Unit-test the status enforcement helper without spinning up the full app."""

    def _call(self, dept_names_set, status):
        from modules.suporte.blueprints.assistencia import (
            STATUS_DEPT_OWNERS,
            _enforce_department_for_status,
        )
        with patch(
            "modules.suporte.blueprints.assistencia._role_key",
            return_value="user",
        ), patch(
            "modules.suporte.blueprints.assistencia._has_assist_admin_permission",
            return_value=False,
        ), patch(
            "modules.suporte.blueprints.assistencia._dept_names",
            return_value=dept_names_set,
        ):
            return _enforce_department_for_status(status)

    def test_estoque_allowed_for_entrada(self):
        self.assertTrue(self._call({"ESTOQUE"}, "Entrada"))

    def test_estoque_allowed_for_fabrica(self):
        self.assertTrue(self._call({"ESTOQUE"}, "fabrica"))

    def test_estoque_allowed_for_retorno(self):
        self.assertTrue(self._call({"ESTOQUE"}, "retorno"))

    def test_estoque_blocked_for_aguardando(self):
        self.assertFalse(self._call({"ESTOQUE"}, "aguardando"))

    def test_estoque_blocked_for_descarte(self):
        self.assertFalse(self._call({"ESTOQUE"}, "descarte"))

    def test_oficina_allowed_for_em_progresso(self):
        self.assertTrue(self._call({"OFICINA"}, "em progresso"))

    def test_oficina_blocked_for_aguardando(self):
        self.assertFalse(self._call({"OFICINA"}, "aguardando"))

    def test_no_dept_allows_any_status(self):
        # empty dept set → do not block
        self.assertTrue(self._call(set(), "aguardando"))

    def test_assist_tecnica_allowed_for_all(self):
        for status in ["Entrada", "em progresso", "fabrica", "aguardando",
                       "concluído", "devolucao_sem_reparo", "descarte", "retorno"]:
            self.assertTrue(self._call({"ASSISTENCIA TECNICA"}, status),
                            f"Should allow ASSISTENCIA TECNICA → {status}")


# ---------------------------------------------------------------------------
# Integration tests against the real HTTP layer
# ---------------------------------------------------------------------------
class TestAssistenciaInvolvedSectors(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.app.config["_audit_logs_table_available"] = True

        # Pre-reflect models to avoid SQLite PRAGMA rollback issue in tests
        from modules.suporte.models import AssistenciaTarefa as AT
        db.session.query(AT).first()

        # Create departments
        self.dept_estoque = Department(name="ESTOQUE", slug="estoque")
        self.dept_oficina = Department(name="OFICINA", slug="oficina")
        self.dept_assist = Department(name="ASSISTENCIA TECNICA", slug="assistencia-tecnica")
        db.session.add_all([self.dept_estoque, self.dept_oficina, self.dept_assist])
        db.session.commit()

        # Create test users — set both FK and M2M for robustness
        self.user_estoque = User(
            usuario="estoque_u",
            nome_completo="Estoque User",
            email="estoque@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="user",
            is_active=True,
            department_id=self.dept_estoque.id,
        )
        self.user_estoque.departments = [self.dept_estoque]

        self.user_oficina = User(
            usuario="oficina_u",
            nome_completo="Oficina User",
            email="oficina@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="user",
            is_active=True,
            department_id=self.dept_oficina.id,
        )
        self.user_oficina.departments = [self.dept_oficina]

        db.session.add_all([self.user_estoque, self.user_oficina])
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

    def _make_task(self, status="aguardando", os_code="1000 RJ"):
        """Create a minimal AssistenciaTarefa for testing."""
        task = AssistenciaTarefa(
            OS=os_code,
            nome="Cliente de Teste",
            unidade="Rio de Janeiro",
            departamento_responsavel="ESTOQUE",
            tipo_entrada="RETIRADO",  # must be a valid choice from ASSIST_TIPO_ENTRADA_CHOICES
            CONTRATO="nao",
            status=status,
            descricao="Descricao de teste",
            data_criacao=date.today(),
            data_fim=date.today(),
        )
        db.session.add(task)
        db.session.commit()
        return task

    def _edit_form_data(self, task, new_status=None, new_descricao=None):
        """Build minimal valid form data for assistencia_editar."""
        return {
            "tarefa_id": str(task.id),
            "nome": task.nome or "Cliente",
            "unidade": task.unidade or "Rio de Janeiro",
            "departamento_responsavel": task.departamento_responsavel or "ESTOQUE",
            # tipo_entrada must match a value from ASSIST_TIPO_ENTRADA_CHOICES
            "tipo_entrada": task.tipo_entrada or "RETIRADO",
            "contrato": (task.CONTRATO or "nao"),
            "os_codigo": task.OS or "TEST",
            "data_criacao": date.today().strftime("%Y-%m-%d"),
            "data_fim": date.today().strftime("%Y-%m-%d"),
            "status": new_status or task.status,
            "descricao": new_descricao or task.descricao or "",
            "notificacao": "nao",
        }

    # -- Access control (before_request hook) --------------------------------

    def test_estoque_can_access_controle_equipamentos(self):
        self.login_as(self.user_estoque)
        response = self.client.get("/assistencia/controle-equipamentos", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertNotIn("Você não tem permissão", html)

    def test_oficina_can_access_controle_equipamentos(self):
        self.login_as(self.user_oficina)
        response = self.client.get("/assistencia/controle-equipamentos", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertNotIn("Você não tem permissão", html)

    # -- Edit without status change -------------------------------------------

    def test_estoque_edit_task_fields_without_status_change(self):
        """ESTOQUE user edits description of a task in 'Entrada' (owned by ESTOQUE).
        This should succeed because no business rules block Entrada status."""
        task = self._make_task(status="Entrada")

        self.login_as(self.user_estoque)
        form_data = self._edit_form_data(task, new_descricao="Nova descricao editada pelo estoque")
        response = self.client.post(
            f"/assistencia/{task.id}/editar",
            data=form_data,
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        db.session.refresh(task)
        self.assertEqual(task.descricao, "Nova descricao editada pelo estoque")
        self.assertEqual(task.status, "Entrada")

    # -- Status change to unowned state ---------------------------------------

    def test_estoque_blocked_from_moving_to_aguardando(self):
        """ESTOQUE user attempts to change status from 'Entrada' to 'aguardando'.
        This should be blocked since ESTOQUE doesn't own 'aguardando'."""
        task = self._make_task(status="Entrada", os_code="1001 RJ")

        self.login_as(self.user_estoque)
        form_data = self._edit_form_data(task, new_status="aguardando")
        response = self.client.post(
            f"/assistencia/{task.id}/editar",
            data=form_data,
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("Seu setor não pode mover para esta etapa", html)

        db.session.refresh(task)
        self.assertEqual(task.status, "Entrada")  # unchanged

    # -- Status change to owned state -----------------------------------------

    def test_estoque_can_move_to_retorno(self):
        """ESTOQUE user moves status from 'Entrada' to 'retorno'.
        This should succeed since ESTOQUE owns 'retorno', and
        Entrada→retorno doesn't trigger budget rules."""
        task = self._make_task(status="Entrada", os_code="1002 RJ")

        self.login_as(self.user_estoque)
        form_data = self._edit_form_data(task, new_status="retorno")
        response = self.client.post(
            f"/assistencia/{task.id}/editar",
            data=form_data,
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        db.session.refresh(task)
        self.assertEqual(task.status, "retorno")


    # -- Department-based visibility and access restrictions -------------------

    def test_estoque_user_cannot_view_or_access_oficina_task(self):
        """Test that an ESTOQUE user cannot view or edit a task assigned to OFICINA."""
        task_oficina = AssistenciaTarefa(
            OS="2001 RJ",
            nome="Cliente Oficina Only",
            unidade="Rio de Janeiro",
            departamento_responsavel="OFICINA",
            tipo_entrada="RETIRADO",
            CONTRATO="nao",
            status="em progresso",
            descricao="Descricao oficina",
            data_criacao=date.today(),
            data_fim=date.today(),
        )
        db.session.add(task_oficina)
        db.session.commit()

        self.login_as(self.user_estoque)

        # 1. API Dashboard: task should not be visible
        response = self.client.get("/assistencia/api/dashboard")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        task_ids = [item["id"] for item in data["items"]]
        self.assertNotIn(task_oficina.id, task_ids)

        # 2. Try to edit this task: should be blocked by check_permissions
        form_data = self._edit_form_data(task_oficina, new_descricao="Trying to hack from estoque")
        response = self.client.post(
            f"/assistencia/{task_oficina.id}/editar",
            data=form_data,
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("Você não tem permissão para acessar esta área", html)

    def test_estoque_user_can_view_and_access_estoque_task(self):
        """Test that an ESTOQUE user can view and edit a task assigned to ESTOQUE."""
        task_estoque = self._make_task(status="Entrada", os_code="2002 RJ")

        self.login_as(self.user_estoque)

        # 1. API Dashboard: task should be visible
        response = self.client.get("/assistencia/api/dashboard")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        task_ids = [item["id"] for item in data["items"]]
        self.assertIn(task_estoque.id, task_ids)

        # 2. Edit should work
        form_data = self._edit_form_data(task_estoque, new_descricao="Authorized edit")
        response = self.client.post(
            f"/assistencia/{task_estoque.id}/editar",
            data=form_data,
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertNotIn("Você não tem permissão", html)

        db.session.refresh(task_estoque)
        self.assertEqual(task_estoque.descricao, "Authorized edit")


if __name__ == "__main__":
    unittest.main()
