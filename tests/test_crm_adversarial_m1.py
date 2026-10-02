from __future__ import annotations
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from sqlalchemy.pool import StaticPool
from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department, ParamOption, ParamCategory
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmInteracao,
    CrmRegraAutomacao,
    CrmRoletaConsultor,
)
from modules.crm.services.crm_service import (
    distribute_deal_round_robin,
    check_and_trigger_stage_automations,
    move_deal_stage,
    capture_lead_from_website,
    toggle_task,
)

class TestConfigAdversarialM1:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-secret-adversarial-m1'
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }

class TestCrmAdversarialM1(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfigAdversarialM1)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        self.dept_comercial = Department.query.filter_by(slug='comercial').first()
        if not self.dept_comercial:
            self.dept_comercial = Department(name='COMERCIAL', slug='comercial')
            db.session.add(self.dept_comercial)
            db.session.commit()

        self.admin_user = User(
            usuario='admin_adv',
            nome_completo='Admin Adversarial',
            email='admin_adv@sollus.com',
            password_hash='hash_adv',
            tipo='admin',
            role='admin',
            department_id=None,
            is_active=True,
            permissions={'crm': True},
        )
        db.session.add(self.admin_user)

        self.funil = CrmFunil(
            id='funil_adv',
            nome='Funil Adversarial',
            slug='funil_adv',
            tipo='ponto',
            ordem=1,
            ativo=True,
        )
        db.session.add(self.funil)
        db.session.flush()

        self.etapa_entrada = CrmEtapa(
            id='etapa_entrada_adv',
            funil_id=self.funil.id,
            nome='Entrada',
            ordem=1,
            tipo='normal',
            probabilidade=10.0,
        )
        self.etapa_qualif = CrmEtapa(
            id='etapa_qualif_adv',
            funil_id=self.funil.id,
            nome='Qualificação',
            ordem=2,
            tipo='normal',
            probabilidade=30.0,
        )
        self.etapa_proposta = CrmEtapa(
            id='etapa_proposta_adv',
            funil_id=self.funil.id,
            nome='Proposta',
            ordem=3,
            tipo='normal',
            probabilidade=60.0,
        )
        db.session.add_all([self.etapa_entrada, self.etapa_qualif, self.etapa_proposta])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _create_consultant(self, username: str, nome: str, active: bool = True) -> User:
        user = User(
            usuario=username,
            nome_completo=nome,
            email=f'{username}@sollus.com',
            password_hash='pwd',
            tipo='consultor',
            is_active=active,
            department_id=self.dept_comercial.id,
        )
        db.session.add(user)
        db.session.commit()
        return user

    def test_adversarial_roulette_high_volume_bursts(self):
        c1 = self._create_consultant('c1', 'Consultor Alfa')
        c2 = self._create_consultant('c2', 'Consultor Beta')
        c3 = self._create_consultant('c3', 'Consultor Gama')

        assigned = []
        for i in range(1, 31):
            res = capture_lead_from_website({
                'nome': f'Lead Rajada {i}',
                'email': f'rajada{i}@teste.com',
                'empresa': f'Empresa Rajada {i}',
            })
            self.assertTrue(res['success'])
            deal = CrmNegociacao.query.get(res['deal_id'])
            assigned.append(deal.user_id)

        self.assertEqual(assigned.count(c1.id), 10)
        self.assertEqual(assigned.count(c2.id), 10)
        self.assertEqual(assigned.count(c3.id), 10)
        self.assertEqual(assigned, [c1.id, c2.id, c3.id] * 10)

        for j in (31, 32):
            res = capture_lead_from_website({
                'nome': f'Lead Rajada {j}',
                'email': f'rajada{j}@teste.com',
                'empresa': f'Empresa Rajada {j}',
            })
            self.assertTrue(res['success'])
            deal = CrmNegociacao.query.get(res['deal_id'])
            assigned.append(deal.user_id)

        counts = [assigned.count(c1.id), assigned.count(c2.id), assigned.count(c3.id)]
        self.assertEqual(counts, [11, 11, 10])
        self.assertLessEqual(max(counts) - min(counts), 1)

        r1 = CrmRoletaConsultor.query.filter_by(consultor_id=c1.id).first()
        r2 = CrmRoletaConsultor.query.filter_by(consultor_id=c2.id).first()
        r3 = CrmRoletaConsultor.query.filter_by(consultor_id=c3.id).first()
        self.assertEqual(r1.total_distribuido, 11)
        self.assertEqual(r2.total_distribuido, 11)
        self.assertEqual(r3.total_distribuido, 10)

    def test_adversarial_roulette_inactive_consultants(self):
        c_active_1 = self._create_consultant('c_act_1', 'Ativo 1', active=True)
        c_active_2 = self._create_consultant('c_act_2', 'Ativo 2', active=True)
        c_inactive_1 = self._create_consultant('c_inact_1', 'Inativo 1', active=False)
        c_inactive_2 = self._create_consultant('c_inact_2', 'Inativo 2', active=False)

        assigned = []
        for i in range(1, 11):
            res = capture_lead_from_website({
                'nome': f'Lead Inactive Test {i}',
                'email': f'lead_inact_{i}@test.com',
                'empresa': f'Empresa Inact {i}',
            })
            self.assertTrue(res['success'])
            deal = CrmNegociacao.query.get(res['deal_id'])
            assigned.append(deal.user_id)

        self.assertEqual(assigned.count(c_inactive_1.id), 0)
        self.assertEqual(assigned.count(c_inactive_2.id), 0)
        self.assertEqual(assigned.count(c_active_1.id), 5)
        self.assertEqual(assigned.count(c_active_2.id), 5)

        c_active_1.is_active = False
        db.session.commit()

        subsequent = []
        for j in range(11, 17):
            res = capture_lead_from_website({
                'nome': f'Lead Dynamic Deact {j}',
                'email': f'lead_deact_{j}@test.com',
                'empresa': f'Empresa Deact {j}',
            })
            self.assertTrue(res['success'])
            deal = CrmNegociacao.query.get(res['deal_id'])
            subsequent.append(deal.user_id)

        self.assertEqual(subsequent.count(c_active_1.id), 0)
        self.assertEqual(subsequent.count(c_active_2.id), 6)

    def test_adversarial_roulette_zero_active_consultants(self):
        # Desativa todos os usuarios do sistema para simular zero consultores ativos
        User.query.update({'is_active': False})
        db.session.commit()

        res = capture_lead_from_website({
            'nome': 'Lead Orfao',
            'email': 'orfao@empresa.com',
            'empresa': 'Empresa Orfa Ltda',
        })
        self.assertTrue(res['success'])
        deal = CrmNegociacao.query.get(res['deal_id'])
        self.assertIsNotNone(deal)
        self.assertIsNone(deal.user_id, 'Com zero consultores ativos, user_id deve ser None')
        self.assertEqual(deal.user_name, 'Não atribuído')

    def test_adversarial_roulette_dynamic_add_and_remove(self):
        c1 = self._create_consultant('dyn_c1', 'Dinamico 1')
        c2 = self._create_consultant('dyn_c2', 'Dinamico 2')

        for i in range(1, 11):
            capture_lead_from_website({
                'nome': f'Fase1 Lead {i}',
                'email': f'fase1_{i}@teste.com',
                'empresa': f'Empresa F1 {i}',
            })

        r1 = CrmRoletaConsultor.query.filter_by(consultor_id=c1.id).first()
        r2 = CrmRoletaConsultor.query.filter_by(consultor_id=c2.id).first()
        self.assertEqual(r1.total_distribuido, 5)
        self.assertEqual(r2.total_distribuido, 5)

        c3 = self._create_consultant('dyn_c3', 'Dinamico 3')

        fase2_assigned = []
        for j in range(1, 16):
            res = capture_lead_from_website({
                'nome': f'Fase2 Lead {j}',
                'email': f'fase2_{j}@teste.com',
                'empresa': f'Empresa F2 {j}',
            })
            deal = CrmNegociacao.query.get(res['deal_id'])
            fase2_assigned.append(deal.user_id)

        self.assertEqual(fase2_assigned[:5], [c3.id, c3.id, c3.id, c3.id, c3.id])

        r1_pos = CrmRoletaConsultor.query.filter_by(consultor_id=c1.id).first()
        r2_pos = CrmRoletaConsultor.query.filter_by(consultor_id=c2.id).first()
        r3_pos = CrmRoletaConsultor.query.filter_by(consultor_id=c3.id).first()

        totais = [r1_pos.total_distribuido, r2_pos.total_distribuido, r3_pos.total_distribuido]
        self.assertEqual(sum(totais), 25)
        self.assertLessEqual(max(totais) - min(totais), 1)

    def test_adversarial_roulette_preassigned_consultant_bypass(self):
        c1 = self._create_consultant('bp_c1', 'Bypass 1')
        c2 = self._create_consultant('bp_c2', 'Bypass 2')

        res = capture_lead_from_website({
            'nome': 'Lead Indicado',
            'email': 'indicado@empresa.com',
            'empresa': 'Empresa Indicada',
            'consultor_id': c2.id,
        })
        self.assertTrue(res['success'])
        deal = CrmNegociacao.query.get(res['deal_id'])
        self.assertEqual(deal.user_id, c2.id)

        r1 = CrmRoletaConsultor.query.filter_by(consultor_id=c1.id).first()
        r2 = CrmRoletaConsultor.query.filter_by(consultor_id=c2.id).first()
        if r1:
            self.assertEqual(r1.total_distribuido, 0)
        if r2:
            self.assertEqual(r2.total_distribuido, 0)

        res2 = capture_lead_from_website({
            'nome': 'Lead Sem Indicacao',
            'email': 'sem_indicacao@empresa.com',
            'empresa': 'Empresa Normal',
        })
        deal2 = CrmNegociacao.query.get(res2['deal_id'])
        self.assertEqual(deal2.user_id, c1.id)

    def test_adversarial_duplicate_task_suppression_back_and_forth_transitions(self):
        regra = CrmRegraAutomacao(
            funil_id=self.funil.id,
            etapa_id=self.etapa_qualif.id,
            evento='etapa_entrada',
            acao_tipo='criar_tarefa',
            tarefa_titulo='Follow-up de Qualificacao Agendado',
            tarefa_tipo='ligacao',
            prazo_horas=24,
            ativo=True,
        )
        db.session.add(regra)
        db.session.commit()

        deal = CrmNegociacao(
            id='deal_ping_pong',
            nome='Negociacao Ping Pong',
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            status='aberto',
        )
        db.session.add(deal)
        db.session.commit()

        move_deal_stage(deal.id, self.etapa_qualif.id, user=self.admin_user)
        tarefas = CrmTarefa.query.filter_by(negociacao_id=deal.id).all()
        self.assertEqual(len(tarefas), 1)
        tarefa_id_inicial = tarefas[0].id

        for _ in range(10):
            move_deal_stage(deal.id, self.etapa_entrada.id, user=self.admin_user)
            move_deal_stage(deal.id, self.etapa_qualif.id, user=self.admin_user)

        tarefas_repetidas = CrmTarefa.query.filter_by(negociacao_id=deal.id).all()
        self.assertEqual(len(tarefas_repetidas), 1)
        self.assertEqual(tarefas_repetidas[0].id, tarefa_id_inicial)
        self.assertFalse(tarefas_repetidas[0].concluida)

        toggle_task(tarefa_id_inicial, concluida=True, user=self.admin_user)
        tarefa_concluida = CrmTarefa.query.get(tarefa_id_inicial)
        self.assertTrue(tarefa_concluida.concluida)

        move_deal_stage(deal.id, self.etapa_entrada.id, user=self.admin_user)
        move_deal_stage(deal.id, self.etapa_qualif.id, user=self.admin_user)

        tarefas_pos_conclusao = CrmTarefa.query.filter_by(negociacao_id=deal.id).all()
        self.assertEqual(len(tarefas_pos_conclusao), 2)
        tarefas_abertas = [t for t in tarefas_pos_conclusao if not t.concluida]
        tarefas_fechadas = [t for t in tarefas_pos_conclusao if t.concluida]
        self.assertEqual(len(tarefas_abertas), 1)
        self.assertEqual(len(tarefas_fechadas), 1)

    def test_adversarial_deadline_calculation_boundaries(self):
        deal = CrmNegociacao(
            id='deal_boundary_calc',
            nome='Negociacao Boundary Calc',
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            status='aberto',
        )
        db.session.add(deal)
        db.session.commit()

        scenarios = [
            (datetime(2026, 12, 31, 23, 30, 0), 1, datetime(2027, 1, 1, 0, 30, 0), 'Ano/Meia-noite'),
            (datetime(2026, 1, 31, 22, 0, 0), 4, datetime(2026, 2, 1, 2, 0, 0), 'Mes'),
            (datetime(2024, 2, 28, 10, 0, 0), 24, datetime(2024, 2, 29, 10, 0, 0), 'Bissexto 28->29'),
            (datetime(2024, 2, 29, 10, 0, 0), 24, datetime(2024, 3, 1, 10, 0, 0), 'Bissexto 29->01'),
            (datetime(2026, 6, 15, 12, 0, 0), 0, datetime(2026, 6, 15, 12, 0, 0), 'Prazo Zero'),
            (datetime(2026, 6, 15, 12, 0, 0), None, datetime(2026, 6, 16, 12, 0, 0), 'Prazo Nulo'),
        ]

        for idx, (frozen_now, prazo, expected, name) in enumerate(scenarios):
            regra = CrmRegraAutomacao(
                funil_id=self.funil.id,
                etapa_id=self.etapa_proposta.id,
                evento='etapa_entrada',
                acao_tipo='criar_tarefa',
                tarefa_titulo=f'Tarefa Boundary {idx}',
                tarefa_tipo='whatsapp',
                prazo_horas=prazo,
                ativo=True,
            )
            db.session.add(regra)
            db.session.commit()

            mock_dt = MagicMock(wraps=datetime)
            mock_dt.utcnow.return_value = frozen_now

            with patch('modules.crm.services.crm_service.datetime', mock_dt):
                created = check_and_trigger_stage_automations(deal, self.etapa_proposta)
                t = next(task for task in created if task.titulo == regra.tarefa_titulo)
                self.assertEqual(t.data_vencimento, expected)

    def test_adversarial_multiple_stage_rules_earliest_deadline_priority(self):
        regra_longa = CrmRegraAutomacao(
            funil_id=self.funil.id,
            etapa_id=self.etapa_qualif.id,
            evento='etapa_entrada',
            acao_tipo='criar_tarefa',
            tarefa_titulo='Apresentacao Formal Longa',
            tarefa_tipo='reuniao',
            prazo_horas=72,
            ativo=True,
        )
        regra_curta = CrmRegraAutomacao(
            funil_id=self.funil.id,
            etapa_id=self.etapa_qualif.id,
            evento='etapa_entrada',
            acao_tipo='criar_tarefa',
            tarefa_titulo='Mensagem Urgente WhatsApp',
            tarefa_tipo='whatsapp',
            prazo_horas=2,
            ativo=True,
        )
        db.session.add_all([regra_longa, regra_curta])
        db.session.commit()

        deal = CrmNegociacao(
            id='deal_priority_test',
            nome='Negociacao Prioridade Prazo',
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            status='aberto',
        )
        db.session.add(deal)
        db.session.commit()

        move_deal_stage(deal.id, self.etapa_qualif.id, user=self.admin_user)

        deal_reloaded = CrmNegociacao.query.get(deal.id)
        tarefas = deal_reloaded.tarefas.all()
        self.assertEqual(len(tarefas), 2)
        self.assertEqual(deal_reloaded.proxima_tarefa_titulo, 'Mensagem Urgente WhatsApp')
        self.assertEqual(deal_reloaded.proxima_tarefa_tipo, 'whatsapp')
        diferenca_horas = (deal_reloaded.proxima_tarefa_data - datetime.utcnow()).total_seconds() / 3600.0
        self.assertAlmostEqual(diferenca_horas, 2.0, delta=0.2)

    def test_adversarial_roleta_consultor_table_ativo_flag(self):
        c1 = self._create_consultant('roleta_act_1', 'Roleta Ativo')
        c2 = self._create_consultant('roleta_pause_2', 'Roleta Pausado')

        r2 = CrmRoletaConsultor(
            consultor_id=c2.id,
            total_distribuido=0,
            ultimo_recebimento=None,
            ativo=False
        )
        db.session.add(r2)
        db.session.commit()

        for i in range(1, 5):
            res = capture_lead_from_website({
                'nome': f'Lead Pausa {i}',
                'email': f'pausa{i}@empresa.com',
                'empresa': f'Empresa Pausa {i}',
            })
            deal = CrmNegociacao.query.get(res['deal_id'])
            self.assertEqual(deal.user_id, c1.id)

    def test_adversarial_negative_or_extreme_prazo_horas(self):
        deal = CrmNegociacao(
            id='deal_extreme_prazo',
            nome='Negociacao Prazos Extremos',
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            status='aberto',
        )
        db.session.add(deal)
        db.session.commit()

        regra_neg = CrmRegraAutomacao(
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            evento='etapa_entrada',
            acao_tipo='criar_tarefa',
            tarefa_titulo='Tarefa Vencida Imediata',
            tarefa_tipo='ligacao',
            prazo_horas=-24,
            ativo=True,
        )
        regra_ano = CrmRegraAutomacao(
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            evento='etapa_entrada',
            acao_tipo='criar_tarefa',
            tarefa_titulo='Follow-up Anual',
            tarefa_tipo='email',
            prazo_horas=8760,
            ativo=True,
        )
        db.session.add_all([regra_neg, regra_ano])
        db.session.commit()

        now = datetime.utcnow()
        tasks = check_and_trigger_stage_automations(deal, self.etapa_entrada)
        self.assertEqual(len(tasks), 2)

        t_neg = next(t for t in tasks if t.titulo == 'Tarefa Vencida Imediata')
        t_ano = next(t for t in tasks if t.titulo == 'Follow-up Anual')

        self.assertLess(t_neg.data_vencimento, now)
        self.assertGreater(t_ano.data_vencimento, now + timedelta(days=360))

if __name__ == '__main__':
    unittest.main()

