"""Testes automatizados da Agenda dos Consultores Comerciais."""
import unittest
from datetime import date, timedelta
from flask_login import login_user
from sqlalchemy.pool import StaticPool

from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department, CommercialAgendaEntry


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


class TestAgendaComercial(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Criar departamento Comercial
        self.dept_comercial = Department.query.filter_by(slug="comercial").first()
        if not self.dept_comercial:
            self.dept_comercial = Department(name="COMERCIAL", slug="comercial")
            db.session.add(self.dept_comercial)
            db.session.commit()

        # Criar Usuários
        self.consultor1 = User(
            usuario="consultor1",
            nome_completo="Consultor Gilson",
            email="gilson@sollus.com",
            password_hash="hash1",
            tipo="consultor",
            role="usuario",
            department_id=self.dept_comercial.id,
            permissions={"comercial_agenda": True, "propostas": True},
        )
        self.consultor2 = User(
            usuario="consultor2",
            nome_completo="Consultor Hizael",
            email="hizael@sollus.com",
            password_hash="hash2",
            tipo="consultor",
            role="usuario",
            department_id=self.dept_comercial.id,
            permissions={"comercial_agenda": True, "propostas": True},
        )
        self.gestor = User(
            usuario="gestor_leonardo",
            nome_completo="Leonardo Gestor",
            email="leonardo@sollus.com",
            password_hash="hash3",
            tipo="gestor",
            role="gestor",
            department_id=self.dept_comercial.id,
            permissions={"comercial_agenda": True, "propostas": True},
        )

        db.session.add_all([self.consultor1, self.consultor2, self.gestor])
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self, user):
        from flask import g
        g.pop("_login_user", None)
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["usuario_id"] = user.id
            sess["user_id"] = user.id
            sess["_fresh"] = True

    def test_acesso_agenda_comercial_html(self):
        self._login(self.consultor1)
        res = self.client.get("/comercial/agenda")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Agenda dos Consultores Comerciais".encode("utf-8"), res.data)
        self.assertIn("Consultor Gilson".encode("utf-8"), res.data)

    def test_criar_compromisso_consultor(self):
        self._login(self.consultor1)
        hoje = date.today()
        payload = {
            "tipo_compromisso": "visita",
            "cliente": "Condomínio Amadeus",
            "local": "Centro - Rio de Janeiro",
            "data_inicio": hoje.isoformat(),
            "periodo": "Tarde",
            "observacoes": "Demonstração de Catraca Henry Lumen",
        }
        res = self.client.post("/comercial/agenda/novo", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        entry = CommercialAgendaEntry.query.filter_by(cliente="Condomínio Amadeus").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.usuario_id, self.consultor1.id)
        self.assertEqual(entry.tipo_compromisso, "visita")
        self.assertEqual(entry.periodo, "Tarde")
        self.assertEqual(entry.status, "agendado")

    def test_consultor_nao_pode_criar_para_outro(self):
        self._login(self.consultor1)
        hoje = date.today()
        # Consultor tenta passar o ID do consultor2
        payload = {
            "usuario_id": self.consultor2.id,
            "tipo_compromisso": "demonstracao",
            "cliente": "Cliente Teste",
            "data_inicio": hoje.isoformat(),
        }
        res = self.client.post("/comercial/agenda/novo", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        entry = CommercialAgendaEntry.query.filter_by(cliente="Cliente Teste").first()
        self.assertIsNotNone(entry)
        # O backend força o usuario_id para o consultor logado
        self.assertEqual(entry.usuario_id, self.consultor1.id)

    def test_gestor_pode_criar_para_qualquer_consultor(self):
        self._login(self.gestor)
        hoje = date.today()
        payload = {
            "usuario_id": self.consultor2.id,
            "tipo_compromisso": "ferias",
            "cliente": "Férias Programadas",
            "data_inicio": hoje.isoformat(),
            "data_fim": (hoje + timedelta(days=15)).isoformat(),
            "periodo": "Dia todo",
        }
        res = self.client.post("/comercial/agenda/novo", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        entry = CommercialAgendaEntry.query.filter_by(cliente="Férias Programadas").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.usuario_id, self.consultor2.id)
        self.assertEqual(entry.tipo_compromisso, "ferias")

    def test_api_fullcalendar_e_tabela(self):
        hoje = date.today()
        entry = CommercialAgendaEntry(
            usuario_id=self.consultor1.id,
            tipo_compromisso="visita",
            cliente="Tech Corp",
            local="Barra da Tijuca",
            data_inicio=hoje,
            periodo="Manhã",
            status="agendado",
        )
        db.session.add(entry)
        db.session.commit()

        self._login(self.consultor1)

        # Modo Calendário
        res_cal = self.client.get(f"/comercial/api/agenda?start={hoje.isoformat()}&end={(hoje + timedelta(days=1)).isoformat()}&view_mode=calendar")
        self.assertEqual(res_cal.status_code, 200)
        events = res_cal.get_json()
        self.assertIsInstance(events, list)
        self.assertEqual(len(events), 1)
        self.assertIn("Tech Corp", events[0]["title"])

        # Modo Tabela
        res_tab = self.client.get("/comercial/api/agenda?view_mode=table&search=Tech")
        self.assertEqual(res_tab.status_code, 200)
        tab_data = res_tab.get_json()
        self.assertEqual(tab_data["total"], 1)
        self.assertEqual(tab_data["items"][0]["cliente"], "Tech Corp")

    def test_editar_e_excluir_compromisso(self):
        hoje = date.today()
        entry = CommercialAgendaEntry(
            usuario_id=self.consultor1.id,
            tipo_compromisso="visita",
            cliente="Original",
            data_inicio=hoje,
        )
        db.session.add(entry)
        db.session.commit()

        # Consultor edita seu próprio compromisso
        self._login(self.consultor1)
        res_edit = self.client.post(f"/comercial/agenda/{entry.id}/editar", data={
            "cliente": "Editado com Sucesso",
            "tipo_compromisso": "demonstracao",
            "data_inicio": hoje.isoformat(),
        }, follow_redirects=True)
        self.assertEqual(res_edit.status_code, 200)
        db.session.refresh(entry)
        self.assertEqual(entry.cliente, "Editado com Sucesso")
        self.assertEqual(entry.tipo_compromisso, "demonstracao")

        # Consultor2 tenta excluir compromisso do consultor1 -> Bloqueado
        self._login(self.consultor2)
        res_del_denied = self.client.post(f"/comercial/agenda/{entry.id}/excluir", follow_redirects=True)
        self.assertEqual(res_del_denied.status_code, 200)
        self.assertIsNotNone(CommercialAgendaEntry.query.get(entry.id))

        # Gestor exclui com sucesso
        self._login(self.gestor)
        res_del = self.client.post(f"/comercial/agenda/{entry.id}/excluir", follow_redirects=True)
        self.assertEqual(res_del.status_code, 200)
        self.assertIsNone(CommercialAgendaEntry.query.get(entry.id))
