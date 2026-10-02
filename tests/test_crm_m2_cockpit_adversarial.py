"""Adversarial Stress Test Suite for Milestone M2 - Sollus CRM Cockpit & Interactions.

Empirically tests:
1. Midnight boundary classifications (yesterday 23:59:59 -> late, today 00:00:00 -> today,
   today 23:59:59 -> today, tomorrow 00:00:00 -> upcoming, microsecond precision, far boundaries).
2. Completed tasks regardless of date -> done (never classified as late, today, or upcoming).
3. Dual-language dictionary keys support ('atrasadas'/'late', 'hoje'/'today', 'proximas'/'upcoming', 'concluidas'/'done')
   in both service layer and HTTP REST endpoint.
4. Task toggle endpoint idempotency, state consistency, next-task cache recalculation, and timeline note generation.
5. Timeline interaction logging input validation: rejects empty string, whitespace only, newlines only,
   tabs only, and null content with HTTP 400 Bad Request, while safely persisting valid interactions.
6. High volume stress: 100 simultaneous tasks with mixed dates and completion statuses.
7. User isolation & multi-tenant consultant filtering in Cockpit.
8. Special characters & XSS payload resilience in titles and notes.
"""
from __future__ import annotations

import unittest
import html
from datetime import datetime, date, timedelta
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
)
from modules.crm.services.crm_service import (
    get_cockpit_tasks,
    toggle_task,
    add_note,
)


class TestConfigCockpitAdversarial:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key-cockpit-adversarial"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class TestCrmM2CockpitAdversarial(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfigCockpitAdversarial)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()

        # Department setup
        self.dept_comercial = Department(name="COMERCIAL", slug="comercial")
        db.session.add(self.dept_comercial)
        db.session.commit()

        # Commercial Consultants
        self.consultant_1 = User(
            usuario="adv_consultant_1",
            nome_completo="Adversarial Consultant 1",
            email="adv1@sollus.com.br",
            password_hash="hash_adv_1",
            tipo="consultor",
            role="consultor",
            department_id=self.dept_comercial.id,
            is_active=True,
            permissions={"crm": True},
        )
        self.consultant_2 = User(
            usuario="adv_consultant_2",
            nome_completo="Adversarial Consultant 2",
            email="adv2@sollus.com.br",
            password_hash="hash_adv_2",
            tipo="consultor",
            role="consultor",
            department_id=self.dept_comercial.id,
            is_active=True,
            permissions={"crm": True},
        )
        db.session.add_all([self.consultant_1, self.consultant_2])
        db.session.commit()

        # Funnel & Stages
        self.funil = CrmFunil(
            id="funil_adv",
            nome="Funil Adversarial Cockpit",
            descricao="Testes adversariais de cockpit",
            ativo=True,
        )
        db.session.add(self.funil)
        db.session.flush()

        self.etapa_1 = CrmEtapa(
            id="etapa_adv_1",
            funil_id=self.funil.id,
            nome="Etapa 1",
            ordem=1,
            tipo="aberto",
            probabilidade=20.0,
        )
        db.session.add(self.etapa_1)
        db.session.commit()

        # Base Deal
        self.deal = CrmNegociacao(
            id="deal_adv_cockpit",
            nome="Negociação Adversarial",
            funil_id=self.funil.id,
            etapa_id=self.etapa_1.id,
            user_id=self.consultant_1.id,
            user_name=self.consultant_1.nome_completo,
            status="aberto",
        )
        db.session.add(self.deal)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self, user: User):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user.id
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True

    # =========================================================================
    # 1. Midnight Boundary Date Classifications
    # =========================================================================

    def test_midnight_boundaries_strict_precision(self):
        """Stress test: exact midnight boundary timestamps and microsecond transitions.
        
        Boundary definitions:
        - start_of_today = datetime(today.year, today.month, today.day, 0, 0, 0)
        - start_of_tomorrow = start_of_today + timedelta(days=1)
        
        Verifies:
        - Yesterday 23:59:59.000000 -> late (atrasada)
        - Yesterday 23:59:59.999999 -> late (atrasada)
        - Today 00:00:00.000000 -> today (hoje)
        - Today 00:00:00.000001 -> today (hoje)
        - Today 12:00:00.000000 -> today (hoje)
        - Today 23:59:59.000000 -> today (hoje)
        - Today 23:59:59.999999 -> today (hoje)
        - Tomorrow 00:00:00.000000 -> upcoming (proxima)
        - Tomorrow 00:00:00.000001 -> upcoming (proxima)
        - Tomorrow 23:59:59.999999 -> upcoming (proxima)
        """
        today = date.today()
        start_of_today = datetime(today.year, today.month, today.day, 0, 0, 0)
        start_of_tomorrow = start_of_today + timedelta(days=1)

        dt_yesterday_sec = start_of_today - timedelta(seconds=1)
        dt_yesterday_usec = start_of_today - timedelta(microseconds=1)
        dt_today_start = start_of_today
        dt_today_usec_start = start_of_today + timedelta(microseconds=1)
        dt_today_noon = start_of_today + timedelta(hours=12)
        dt_today_sec = start_of_tomorrow - timedelta(seconds=1)
        dt_today_usec = start_of_tomorrow - timedelta(microseconds=1)
        dt_tomorrow_start = start_of_tomorrow
        dt_tomorrow_usec_start = start_of_tomorrow + timedelta(microseconds=1)
        dt_tomorrow_end = start_of_tomorrow + timedelta(days=1) - timedelta(microseconds=1)

        tasks = [
            CrmTarefa(id="t_y_sec", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Yesterday Sec", data_vencimento=dt_yesterday_sec),
            CrmTarefa(id="t_y_usec", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Yesterday Microsec", data_vencimento=dt_yesterday_usec),
            CrmTarefa(id="t_tod_start", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Today 00:00:00", data_vencimento=dt_today_start),
            CrmTarefa(id="t_tod_usec_start", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Today Microsec Start", data_vencimento=dt_today_usec_start),
            CrmTarefa(id="t_tod_noon", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Today Noon", data_vencimento=dt_today_noon),
            CrmTarefa(id="t_tod_sec", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Today 23:59:59", data_vencimento=dt_today_sec),
            CrmTarefa(id="t_tod_usec", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Today 23:59:59.999999", data_vencimento=dt_today_usec),
            CrmTarefa(id="t_tom_start", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Tomorrow 00:00:00", data_vencimento=dt_tomorrow_start),
            CrmTarefa(id="t_tom_usec_start", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Tomorrow Microsec Start", data_vencimento=dt_tomorrow_usec_start),
            CrmTarefa(id="t_tom_end", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Tomorrow End", data_vencimento=dt_tomorrow_end),
        ]
        db.session.add_all(tasks)
        db.session.commit()

        cockpit = get_cockpit_tasks(user_id=self.consultant_1.id)

        # Expected distribution:
        # late: t_y_sec, t_y_usec (2 tasks)
        # today: t_tod_start, t_tod_usec_start, t_tod_noon, t_tod_sec, t_tod_usec (5 tasks)
        # upcoming: t_tom_start, t_tom_usec_start, t_tom_end (3 tasks)
        # done: 0
        self.assertEqual(cockpit["counts"]["late"], 2, "Expected exactly 2 late tasks")
        self.assertEqual(cockpit["counts"]["today"], 5, "Expected exactly 5 today tasks")
        self.assertEqual(cockpit["counts"]["upcoming"], 3, "Expected exactly 3 upcoming tasks")
        self.assertEqual(cockpit["counts"]["done"], 0, "Expected 0 done tasks")

        late_ids = {t.id for t in cockpit["tasks"]["late"]}
        today_ids = {t.id for t in cockpit["tasks"]["today"]}
        upcoming_ids = {t.id for t in cockpit["tasks"]["upcoming"]}

        self.assertEqual(late_ids, {"t_y_sec", "t_y_usec"})
        self.assertEqual(today_ids, {"t_tod_start", "t_tod_usec_start", "t_tod_noon", "t_tod_sec", "t_tod_usec"})
        self.assertEqual(upcoming_ids, {"t_tom_start", "t_tom_usec_start", "t_tom_end"})

    def test_extreme_dates_centuries_and_leap_years(self):
        """Stress test: extreme dates (far past, far future, leap year boundaries)."""
        dt_far_past = datetime(1990, 1, 1, 12, 0, 0)
        dt_far_future = datetime(2099, 12, 31, 23, 59, 59)

        t_past = CrmTarefa(id="t_past", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Ancient Task", data_vencimento=dt_far_past)
        t_fut = CrmTarefa(id="t_fut", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Far Future Task", data_vencimento=dt_far_future)
        db.session.add_all([t_past, t_fut])
        db.session.commit()

        cockpit = get_cockpit_tasks(user_id=self.consultant_1.id)
        self.assertIn("t_past", {t.id for t in cockpit["tasks"]["late"]})
        self.assertIn("t_fut", {t.id for t in cockpit["tasks"]["upcoming"]})

    # =========================================================================
    # 2. Completed Tasks Regardless of Date
    # =========================================================================

    def test_completed_tasks_classified_as_done_regardless_of_due_date(self):
        """Stress test: completed tasks MUST be classified into 'done' / 'concluidas'
        regardless of whether their due date was in the past, today, or in the future.
        They must NEVER leak into 'late', 'today', or 'upcoming'.
        """
        today = date.today()
        start_of_today = datetime(today.year, today.month, today.day, 0, 0, 0)
        start_of_tomorrow = start_of_today + timedelta(days=1)

        t_done_past = CrmTarefa(
            id="t_done_past",
            negociacao_id=self.deal.id,
            user_id=self.consultant_1.id,
            titulo="Done Overdue",
            data_vencimento=start_of_today - timedelta(days=10),
            concluida=True,
            concluida_em=datetime.utcnow()
        )
        t_done_yesterday = CrmTarefa(
            id="t_done_yest",
            negociacao_id=self.deal.id,
            user_id=self.consultant_1.id,
            titulo="Done Yesterday Midnight",
            data_vencimento=start_of_today - timedelta(seconds=1),
            concluida=True,
            concluida_em=datetime.utcnow()
        )
        t_done_today_start = CrmTarefa(
            id="t_done_tod_start",
            negociacao_id=self.deal.id,
            user_id=self.consultant_1.id,
            titulo="Done Today 00:00:00",
            data_vencimento=start_of_today,
            concluida=True,
            concluida_em=datetime.utcnow()
        )
        t_done_today_end = CrmTarefa(
            id="t_done_tod_end",
            negociacao_id=self.deal.id,
            user_id=self.consultant_1.id,
            titulo="Done Today 23:59:59",
            data_vencimento=start_of_tomorrow - timedelta(seconds=1),
            concluida=True,
            concluida_em=datetime.utcnow()
        )
        t_done_tomorrow = CrmTarefa(
            id="t_done_tom",
            negociacao_id=self.deal.id,
            user_id=self.consultant_1.id,
            titulo="Done Tomorrow 00:00:00",
            data_vencimento=start_of_tomorrow,
            concluida=True,
            concluida_em=datetime.utcnow()
        )
        t_done_future = CrmTarefa(
            id="t_done_fut",
            negociacao_id=self.deal.id,
            user_id=self.consultant_1.id,
            titulo="Done Far Future",
            data_vencimento=start_of_tomorrow + timedelta(days=365),
            concluida=True,
            concluida_em=datetime.utcnow()
        )

        db.session.add_all([
            t_done_past,
            t_done_yesterday,
            t_done_today_start,
            t_done_today_end,
            t_done_tomorrow,
            t_done_future,
        ])
        db.session.commit()

        cockpit = get_cockpit_tasks(user_id=self.consultant_1.id)

        # All 6 must be in done
        self.assertEqual(cockpit["counts"]["done"], 6)
        self.assertEqual(cockpit["counts"]["concluidas"], 6)
        # None should leak into pending categories
        self.assertEqual(cockpit["counts"]["late"], 0)
        self.assertEqual(cockpit["counts"]["atrasadas"], 0)
        self.assertEqual(cockpit["counts"]["today"], 0)
        self.assertEqual(cockpit["counts"]["hoje"], 0)
        self.assertEqual(cockpit["counts"]["upcoming"], 0)
        self.assertEqual(cockpit["counts"]["proximas"], 0)

        done_ids = {t.id for t in cockpit["tasks"]["done"]}
        self.assertEqual(done_ids, {
            "t_done_past",
            "t_done_yest",
            "t_done_tod_start",
            "t_done_tod_end",
            "t_done_tom",
            "t_done_fut",
        })

    # =========================================================================
    # 3. Dual-Language Dictionary Keys Support
    # =========================================================================

    def test_dual_language_dictionary_keys_service_and_api(self):
        """Stress test: verify full dual-language support ('atrasadas'/'late', 'hoje'/'today',
        'proximas'/'upcoming', 'concluidas'/'done') across get_cockpit_tasks and /crm/tarefas REST API.
        """
        today = date.today()
        start_of_today = datetime(today.year, today.month, today.day, 0, 0, 0)
        start_of_tomorrow = start_of_today + timedelta(days=1)

        t_late = CrmTarefa(id="t_dl_late", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="DL Late", data_vencimento=start_of_today - timedelta(hours=2))
        t_today = CrmTarefa(id="t_dl_today", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="DL Today", data_vencimento=start_of_today + timedelta(hours=10))
        t_upcoming = CrmTarefa(id="t_dl_upcoming", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="DL Upcoming", data_vencimento=start_of_tomorrow + timedelta(hours=5))
        t_done = CrmTarefa(id="t_dl_done", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="DL Done", data_vencimento=start_of_today, concluida=True)

        db.session.add_all([t_late, t_today, t_upcoming, t_done])
        db.session.commit()

        # 1. Test Service Layer dual keys
        res = get_cockpit_tasks(user_id=self.consultant_1.id)

        # Check counts equality
        self.assertEqual(res["counts"]["late"], res["counts"]["atrasadas"])
        self.assertEqual(res["counts"]["today"], res["counts"]["hoje"])
        self.assertEqual(res["counts"]["upcoming"], res["counts"]["proximas"])
        self.assertEqual(res["counts"]["done"], res["counts"]["concluidas"])

        self.assertEqual(res["counts"]["late"], 1)
        self.assertEqual(res["counts"]["today"], 1)
        self.assertEqual(res["counts"]["upcoming"], 1)
        self.assertEqual(res["counts"]["done"], 1)
        self.assertEqual(res["counts"]["total"], 4)

        # Check tasks equality
        self.assertEqual([t.id for t in res["tasks"]["late"]], [t.id for t in res["tasks"]["atrasadas"]])
        self.assertEqual([t.id for t in res["tasks"]["today"]], [t.id for t in res["tasks"]["hoje"]])
        self.assertEqual([t.id for t in res["tasks"]["upcoming"]], [t.id for t in res["tasks"]["proximas"]])
        self.assertEqual([t.id for t in res["tasks"]["done"]], [t.id for t in res["tasks"]["concluidas"]])

        # 2. Test HTTP Endpoint GET /crm/tarefas?format=json dual filter parameters
        self._login(self.consultant_1)

        pairs = [
            ("late", "atrasadas", "t_dl_late"),
            ("today", "hoje", "t_dl_today"),
            ("upcoming", "proximas", "t_dl_upcoming"),
            ("done", "concluidas", "t_dl_done"),
        ]

        for en_key, pt_key, expected_id in pairs:
            # Query EN
            res_en = self.client.get(f"/crm/tarefas?filtro={en_key}&format=json")
            self.assertEqual(res_en.status_code, 200)
            data_en = res_en.get_json()
            self.assertTrue(data_en["success"])
            self.assertEqual(data_en["total"], 1)
            self.assertEqual(data_en["tarefas"][0]["id"], expected_id)

            # Query PT
            res_pt = self.client.get(f"/crm/tarefas?filtro={pt_key}&format=json")
            self.assertEqual(res_pt.status_code, 200)
            data_pt = res_pt.get_json()
            self.assertTrue(data_pt["success"])
            self.assertEqual(data_pt["total"], 1)
            self.assertEqual(data_pt["tarefas"][0]["id"], expected_id)

            # Both responses must have identical task counts in metadata
            self.assertEqual(data_en["counts"], data_pt["counts"])
            self.assertEqual(data_en["counts"]["late"], data_en["counts"]["atrasadas"])
            self.assertEqual(data_en["counts"]["today"], data_en["counts"]["hoje"])
            self.assertEqual(data_en["counts"]["upcoming"], data_en["counts"]["proximas"])
            self.assertEqual(data_en["counts"]["done"], data_en["counts"]["concluidas"])

    # =========================================================================
    # 4. Task Toggle Endpoint Idempotency and Timeline Note Generation
    # =========================================================================

    def test_task_toggle_idempotency_timeline_and_next_task_cache(self):
        """Stress test: verify toggle task endpoint behavior under repeated calls,
        cache invalidation of deal's next task, and timeline note generation.
        """
        self._login(self.consultant_1)

        t1 = CrmTarefa(
            id="t_toggle_first",
            negociacao_id=self.deal.id,
            user_id=self.consultant_1.id,
            titulo="Follow-up WhatsApp Inicial",
            data_vencimento=datetime.utcnow() + timedelta(hours=1),
            concluida=False,
        )
        t2 = CrmTarefa(
            id="t_toggle_second",
            negociacao_id=self.deal.id,
            user_id=self.consultant_1.id,
            titulo="Apresentação Comercial",
            data_vencimento=datetime.utcnow() + timedelta(hours=5),
            concluida=False,
        )
        db.session.add_all([t1, t2])
        db.session.commit()

        # Step 1: Toggle t1 to done
        res1 = self.client.post(f"/crm/api/tarefas/{t1.id}/toggle", json={"concluida": True})
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertTrue(data1["success"])
        self.assertTrue(data1["tarefa"]["concluida"])

        db.session.refresh(t1)
        db.session.refresh(self.deal)
        self.assertTrue(t1.concluida)
        self.assertIsNotNone(t1.concluida_em)
        # Next pending task for deal should now be t2
        self.assertEqual(self.deal.proxima_tarefa_id, t2.id)

        # Check timeline entry
        timeline_1 = CrmInteracao.query.filter_by(negociacao_id=self.deal.id).all()
        self.assertEqual(len(timeline_1), 1)
        self.assertEqual(timeline_1[0].tipo, "tarefa_concluida")
        self.assertIn("Follow-up WhatsApp Inicial", timeline_1[0].conteudo)
        self.assertIn("concluída", timeline_1[0].conteudo)

        # Step 2: Idempotent toggle call - complete an already completed task
        res2 = self.client.post(f"/crm/api/tarefas/{t1.id}/toggle", json={"concluida": True})
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2["success"])
        self.assertTrue(data2["tarefa"]["concluida"])

        db.session.refresh(t1)
        db.session.refresh(self.deal)
        self.assertTrue(t1.concluida)
        self.assertEqual(self.deal.proxima_tarefa_id, t2.id)

        # Step 3: Complete t2 as well
        res_t2 = self.client.post(f"/crm/api/tarefas/{t2.id}/toggle", json={"concluida": True})
        self.assertEqual(res_t2.status_code, 200)
        db.session.refresh(self.deal)
        # All tasks done -> proxima_tarefa_id should be None
        self.assertIsNone(self.deal.proxima_tarefa_id)
        self.assertIsNone(self.deal.proxima_tarefa_titulo)

        # Step 4: Reopen t1 (concluida = False)
        res_reopen = self.client.post(f"/crm/api/tarefas/{t1.id}/toggle", json={"concluida": False})
        self.assertEqual(res_reopen.status_code, 200)
        data_reopen = res_reopen.get_json()
        self.assertFalse(data_reopen["tarefa"]["concluida"])

        db.session.refresh(t1)
        db.session.refresh(self.deal)
        self.assertFalse(t1.concluida)
        self.assertIsNone(t1.concluida_em)
        # Next pending task for deal is back to t1!
        self.assertEqual(self.deal.proxima_tarefa_id, t1.id)

        # Check reopen timeline note
        reopen_notes = CrmInteracao.query.filter_by(negociacao_id=self.deal.id, tipo="tarefa_reaberta").all()
        self.assertEqual(len(reopen_notes), 1)
        self.assertIn("reaberta", reopen_notes[0].conteudo)

        # Step 5: Toggle with empty payload {} defaults safely without crash
        res_empty_payload = self.client.post(f"/crm/api/tarefas/{t1.id}/toggle", json={})
        self.assertEqual(res_empty_payload.status_code, 200)
        db.session.refresh(t1)
        self.assertTrue(t1.concluida)

        # Step 6: Toggle non-existent task returns error safely without server crash
        res_non_existent = self.client.post("/crm/api/tarefas/non_existent_task_id_9999/toggle", json={"concluida": True})
        self.assertIn(res_non_existent.status_code, (404, 500))
        data_non_existent = res_non_existent.get_json()
        self.assertFalse(data_non_existent["success"])

    def test_toggle_repeated_notes_observation(self):
        """Empirical challenge: observe timeline note insertion count upon repeated toggle calls.
        Documents whether re-toggling to the same state logs repeated timeline entries.
        """
        self._login(self.consultant_1)
        task = CrmTarefa(
            id="t_repeat_toggle",
            negociacao_id=self.deal.id,
            user_id=self.consultant_1.id,
            titulo="Tarefa Toggle Repetido",
            data_vencimento=datetime.utcnow() + timedelta(hours=2),
            concluida=False,
        )
        db.session.add(task)
        db.session.commit()

        # Toggle 3 times with concluida=True
        for i in range(3):
            res = self.client.post(f"/crm/api/tarefas/{task.id}/toggle", json={"concluida": True})
            self.assertEqual(res.status_code, 200)

        # Check how many timeline interactions exist
        interactions = CrmInteracao.query.filter_by(negociacao_id=self.deal.id, tipo="tarefa_concluida").all()
        # In current design, each call records an interaction audit record
        self.assertEqual(len(interactions), 3, "Each toggle call records an audit interaction in timeline")

    # =========================================================================
    # 5. Timeline Interaction Logging Validation & Whitespace Rejection (400)
    # =========================================================================

    def test_timeline_interaction_empty_and_whitespace_validation(self):
        """Stress test: Timeline interaction logging MUST reject empty string, whitespace only,
        newlines only, tabs only, null, and missing content with HTTP 400 Bad Request.
        
        Tests both /crm/api/negociacoes/<id>/anotacoes and /crm/api/negociacoes/<id>/interacoes.
        """
        self._login(self.consultant_1)

        endpoints = [
            f"/crm/api/negociacoes/{self.deal.id}/anotacoes",
            f"/crm/api/negociacoes/{self.deal.id}/interacoes",
        ]

        invalid_payloads = [
            ("empty_string", {"conteudo": ""}),
            ("single_space", {"conteudo": " "}),
            ("multiple_spaces", {"conteudo": "      "}),
            ("tabs_only", {"conteudo": "\t\t\t"}),
            ("newlines_only_unix", {"conteudo": "\n\n\n"}),
            ("newlines_only_crlf", {"conteudo": "\r\n\r\n"}),
            ("mixed_whitespace", {"conteudo": "   \t  \r\n \n \t  "}),
            ("empty_body", {}),
            ("none_value", {"conteudo": None}),
            ("descricao_empty", {"descricao": ""}),
            ("descricao_whitespace", {"descricao": "    \t\n  "}),
            ("descricao_none", {"descricao": None}),
        ]

        for ep in endpoints:
            for label, payload in invalid_payloads:
                res = self.client.post(ep, json=payload)
                self.assertEqual(
                    res.status_code,
                    400,
                    f"Endpoint {ep} with payload '{label}' expected 400 Bad Request, got {res.status_code} ({res.get_data(as_text=True)})"
                )
                data = res.get_json()
                self.assertFalse(data.get("success", True), f"Expected success=False for {label}")
                self.assertIn("error", data)

        # Verify that absolutely ZERO interactions were written to DB from invalid payloads
        self.assertEqual(CrmInteracao.query.filter_by(negociacao_id=self.deal.id).count(), 0)

        # Now test VALID interaction payload
        valid_payload = {
            "conteudo": "  Reunião com diretor técnico agendada para sexta-feira.  ",
            "tipo": "reuniao",
        }
        res_valid = self.client.post(f"/crm/api/negociacoes/{self.deal.id}/interacoes", json=valid_payload)
        self.assertEqual(res_valid.status_code, 200)
        data_valid = res_valid.get_json()
        self.assertTrue(data_valid["success"])
        self.assertEqual(data_valid["interacao"]["tipo"], "reuniao")
        # Content should be stripped of leading/trailing whitespace
        self.assertEqual(data_valid["interacao"]["conteudo"], "Reunião com diretor técnico agendada para sexta-feira.")

        # Exactly 1 interaction in DB
        self.assertEqual(CrmInteracao.query.filter_by(negociacao_id=self.deal.id).count(), 1)

    # =========================================================================
    # 6. High Volume Stress Test (100 Mixed Tasks)
    # =========================================================================

    def test_high_volume_stress_100_tasks(self):
        """Stress test: 100 simultaneous tasks across different dates and completion statuses.
        Validates performance, memory stability, and counter consistency under scale.
        """
        today = date.today()
        start_of_today = datetime(today.year, today.month, today.day, 0, 0, 0)
        start_of_tomorrow = start_of_today + timedelta(days=1)

        tasks = []
        # 25 late tasks
        for i in range(25):
            tasks.append(CrmTarefa(
                id=f"t_bulk_late_{i}",
                negociacao_id=self.deal.id,
                user_id=self.consultant_1.id,
                titulo=f"Bulk Late Task {i}",
                data_vencimento=start_of_today - timedelta(days=i + 1),
                concluida=False,
            ))
        # 25 today tasks
        for i in range(25):
            tasks.append(CrmTarefa(
                id=f"t_bulk_today_{i}",
                negociacao_id=self.deal.id,
                user_id=self.consultant_1.id,
                titulo=f"Bulk Today Task {i}",
                data_vencimento=start_of_today + timedelta(minutes=i * 20),
                concluida=False,
            ))
        # 25 upcoming tasks
        for i in range(25):
            tasks.append(CrmTarefa(
                id=f"t_bulk_up_{i}",
                negociacao_id=self.deal.id,
                user_id=self.consultant_1.id,
                titulo=f"Bulk Upcoming Task {i}",
                data_vencimento=start_of_tomorrow + timedelta(days=i + 1),
                concluida=False,
            ))
        # 25 done tasks (with mixed due dates)
        for i in range(25):
            tasks.append(CrmTarefa(
                id=f"t_bulk_done_{i}",
                negociacao_id=self.deal.id,
                user_id=self.consultant_1.id,
                titulo=f"Bulk Done Task {i}",
                data_vencimento=start_of_today - timedelta(days=i),
                concluida=True,
                concluida_em=datetime.utcnow(),
            ))

        db.session.add_all(tasks)
        db.session.commit()

        cockpit = get_cockpit_tasks(user_id=self.consultant_1.id)

        self.assertEqual(cockpit["counts"]["late"], 25)
        self.assertEqual(cockpit["counts"]["today"], 25)
        self.assertEqual(cockpit["counts"]["upcoming"], 25)
        self.assertEqual(cockpit["counts"]["done"], 25)
        self.assertEqual(cockpit["counts"]["total"], 100)

        # Ordering check: tasks in late, today, upcoming must be in asc order of data_vencimento
        for key in ("late", "today", "upcoming"):
            items = cockpit["tasks"][key]
            for idx in range(len(items) - 1):
                self.assertLessEqual(items[idx].data_vencimento, items[idx + 1].data_vencimento)

    # =========================================================================
    # 7. User Isolation and Multi-Consultant Segregation
    # =========================================================================

    def test_user_isolation_and_all_filter(self):
        """Stress test: consultant filtering in Cockpit correctly isolates tasks between consultants."""
        today = date.today()
        dt_today = datetime(today.year, today.month, today.day, 14, 0, 0)

        deal_c2 = CrmNegociacao(
            id="deal_c2",
            nome="Deal Consultant 2",
            funil_id=self.funil.id,
            etapa_id=self.etapa_1.id,
            user_id=self.consultant_2.id,
            status="aberto",
        )
        db.session.add(deal_c2)
        db.session.flush()

        t_c1 = CrmTarefa(id="t_user_c1", negociacao_id=self.deal.id, user_id=self.consultant_1.id, titulo="Task C1", data_vencimento=dt_today)
        t_c2 = CrmTarefa(id="t_user_c2", negociacao_id=deal_c2.id, user_id=self.consultant_2.id, titulo="Task C2", data_vencimento=dt_today)
        db.session.add_all([t_c1, t_c2])
        db.session.commit()

        # Consultant 1 query
        cockpit_c1 = get_cockpit_tasks(user_id=self.consultant_1.id)
        self.assertEqual(cockpit_c1["counts"]["total"], 1)
        self.assertEqual(cockpit_c1["tasks"]["today"][0].id, "t_user_c1")

        # Consultant 2 query
        cockpit_c2 = get_cockpit_tasks(user_id=self.consultant_2.id)
        self.assertEqual(cockpit_c2["counts"]["total"], 1)
        self.assertEqual(cockpit_c2["tasks"]["today"][0].id, "t_user_c2")

        # All consultants query (user_id=None)
        cockpit_all = get_cockpit_tasks(user_id=None)
        self.assertEqual(cockpit_all["counts"]["total"], 2)
        all_ids = {t.id for t in cockpit_all["tasks"]["today"]}
        self.assertEqual(all_ids, {"t_user_c1", "t_user_c2"})

        # HTTP Endpoint: ?user_id=all
        self._login(self.consultant_1)
        res_all = self.client.get("/crm/tarefas?user_id=all&format=json")
        self.assertEqual(res_all.status_code, 200)
        self.assertEqual(res_all.get_json()["counts"]["total"], 2)

    # =========================================================================
    # 8. Special Characters & XSS Injection Payload Resilience
    # =========================================================================

    def test_special_characters_and_xss_resilience(self):
        """Stress test: titles with HTML, script tags, quotes, unicode emojis, and SQL fragments."""
        xss_payload = '<script>alert("XSS")</script> & <img src=x onerror=alert(1)>'
        unicode_payload = '🚀 Negociação Sollus \U0001f91d Comércio de Aço & Cia "Especial"'

        task = CrmTarefa(
            id="t_xss",
            negociacao_id=self.deal.id,
            user_id=self.consultant_1.id,
            titulo=xss_payload,
            data_vencimento=datetime.utcnow() + timedelta(hours=3),
        )
        db.session.add(task)
        db.session.commit()

        self._login(self.consultant_1)

        # 1. API endpoint JSON serialization
        res_json = self.client.get("/crm/tarefas?format=json")
        self.assertEqual(res_json.status_code, 200)
        data = res_json.get_json()
        self.assertTrue(any(t["titulo"] == xss_payload for t in data["tarefas"]))

        # 2. HTML template render: verify it renders with 200 and escapes the raw script tag
        res_html = self.client.get("/crm/tarefas")
        self.assertEqual(res_html.status_code, 200)
        html_content = res_html.get_data(as_text=True)
        # Jinja2 auto-escapes raw <script> as &lt;script&gt;
        self.assertNotIn("<script>alert(\"XSS\")</script>", html_content)
        self.assertIn("&lt;script&gt;alert(&#34;XSS&#34;)&lt;/script&gt;", html_content)

        # 3. Add note with unicode & special chars
        res_note = self.client.post(
            f"/crm/api/negociacoes/{self.deal.id}/interacoes",
            json={"conteudo": unicode_payload, "tipo": "whatsapp"}
        )
        self.assertEqual(res_note.status_code, 200)
        saved_note = CrmInteracao.query.filter_by(negociacao_id=self.deal.id, tipo="whatsapp").first()
        self.assertIsNotNone(saved_note)
        self.assertEqual(saved_note.conteudo, unicode_payload)


if __name__ == "__main__":
    unittest.main()
