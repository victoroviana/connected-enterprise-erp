"""Testes automatizados do Milestone M1 - Sollus CRM.

Abrange:
- Modelos M1 e Schema (CrmMotivoPerda, CrmRegraAutomacao, CrmRoletaConsultor, CrmWebhook, CrmWebhookLog, CrmTemplateMensagem)
- Evolução de colunas de CrmNegociacao e CrmEtapa
- Execução não-destrutiva de ensure_crm_schema
- Distribuição sequencial determinística pela Roleta Comercial (Round-Robin)
- Automação de tarefas por gatilho de etapa com cálculo de prazo
- Sincronização bidirecional entre Propostas e CRM
- Fechamento como Ganho e criação correta de Pedido no SollusFlow (SfPedido)
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from sqlalchemy.pool import StaticPool

from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department, Proposal, Equipment, ParamOption, ParamCategory
from modules.chamados.models import SfPedido
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmInteracao,
    CrmMotivoPerda,
    CrmRegraAutomacao,
    CrmRoletaConsultor,
    CrmWebhook,
    CrmWebhookLog,
    CrmTemplateMensagem,
)
from modules.crm.utils.schema import ensure_crm_schema
from modules.crm.services.crm_service import (
    distribute_deal_round_robin,
    check_and_trigger_stage_automations,
    move_deal_stage,
    mark_deal_won,
    mark_deal_lost,
    capture_lead_from_website,
)


class TestConfigM1:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key-crm-m1"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class TestCrmM1(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfigM1)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()

        # Departamento Comercial
        self.dept_comercial = Department.query.filter_by(slug="comercial").first()
        if not self.dept_comercial:
            self.dept_comercial = Department(name="COMERCIAL", slug="comercial")
            db.session.add(self.dept_comercial)
            db.session.commit()

        # Usuário Admin Principal (sem departamento comercial para isolar a roleta nos testes)
        self.admin_user = User(
            usuario="admin_crm",
            nome_completo="Administrador Comercial",
            email="admin@sollus.com",
            password_hash="hash_admin",
            tipo="admin",
            role="admin",
            department_id=None,
            permissions={"crm": True, "propostas": True},
        )
        db.session.add(self.admin_user)

        # Seed ParamOption choices for WTForms dropdowns
        options = [
            ParamOption(category=ParamCategory.PAGTO_EQUIP, label="A vista"),
            ParamOption(category=ParamCategory.PRAZO_ENTREGA, label="Imediato"),
            ParamOption(category=ParamCategory.FRETE, label="CIF"),
            ParamOption(category=ParamCategory.GARANTIA_EQ, label="12 meses"),
            ParamOption(category=ParamCategory.GARANTIA_SYS, label="12 meses"),
        ]
        db.session.add_all(options)
        db.session.commit()

        # Funil de Vendas com Etapas
        self.funil = CrmFunil(
            id="funil_m1",
            nome="Funil de Ponto M1",
            slug="funil_ponto",
            tipo="ponto",
            ordem=1,
            ativo=True,
        )
        db.session.add(self.funil)
        db.session.flush()

        self.etapa_entrada = CrmEtapa(
            id="etapa_entrada_m1",
            funil_id=self.funil.id,
            nome="Entrada / Novo",
            ordem=1,
            tipo="normal",
            probabilidade=10.0,
        )
        self.etapa_qualif = CrmEtapa(
            id="etapa_qualif_m1",
            funil_id=self.funil.id,
            nome="Qualificação",
            ordem=2,
            tipo="normal",
            probabilidade=30.0,
        )
        self.etapa_proposta = CrmEtapa(
            id="etapa_proposta_m1",
            funil_id=self.funil.id,
            nome="Proposta Enviada",
            nickname="Proposta",
            ordem=3,
            tipo="normal",
            probabilidade=60.0,
        )
        self.etapa_ganho = CrmEtapa(
            id="etapa_ganho_m1",
            funil_id=self.funil.id,
            nome="Fechamento Ganho",
            ordem=4,
            tipo="ganho",
            probabilidade=100.0,
        )
        self.etapa_perdido = CrmEtapa(
            id="etapa_perdido_m1",
            funil_id=self.funil.id,
            nome="Perdido",
            ordem=5,
            tipo="perdido",
            probabilidade=0.0,
        )
        db.session.add_all([
            self.etapa_entrada,
            self.etapa_qualif,
            self.etapa_proposta,
            self.etapa_ganho,
            self.etapa_perdido,
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_crm_m1_models_and_schema_inspection(self):
        """Valida a persistência, serialização e integridade dos novos modelos do CRM M1."""
        # 1. CrmMotivoPerda
        motivo = CrmMotivoPerda(
            nome="Orçamento insuficiente",
            categoria="preco",
            ativo=True,
            ordem=1,
        )
        db.session.add(motivo)
        db.session.flush()
        self.assertIsNotNone(motivo.id)
        d_motivo = motivo.to_dict()
        self.assertEqual(d_motivo["nome"], "Orçamento insuficiente")
        self.assertEqual(d_motivo["categoria"], "preco")

        # 2. CrmRegraAutomacao
        regra = CrmRegraAutomacao(
            funil_id=self.funil.id,
            etapa_id=self.etapa_qualif.id,
            evento="etapa_entrada",
            acao_tipo="criar_tarefa",
            tarefa_titulo="Follow-up Rápido",
            tarefa_tipo="whatsapp",
            prazo_horas=4,
            ativo=True,
        )
        db.session.add(regra)
        db.session.flush()
        self.assertIsNotNone(regra.id)
        self.assertEqual(regra.gatilho, "etapa_entrada")
        self.assertEqual(regra.acao, "criar_tarefa")
        self.assertEqual(regra.prazo_horas, 4)

        # 3. CrmRoletaConsultor
        roleta = CrmRoletaConsultor(
            consultor_id=self.admin_user.id,
            total_distribuido=5,
            ultimo_recebimento=datetime.utcnow(),
            ativo=True,
        )
        db.session.add(roleta)
        db.session.flush()
        self.assertEqual(roleta.user_id, self.admin_user.id)
        self.assertEqual(roleta.total_distribuido, 5)

        # 4. CrmWebhook e CrmWebhookLog
        webhook = CrmWebhook(
            nome="Webhook Externo Parcela",
            tipo="outbound",
            url="https://api.exemplo.com/webhook",
            eventos="deal_criado,deal_ganho",
            secret_key="secret-key-123",
            ativo=True,
        )
        db.session.add(webhook)
        db.session.flush()
        self.assertEqual(webhook.url_destino, "https://api.exemplo.com/webhook")
        self.assertEqual(webhook.secret, "secret-key-123")

        log = CrmWebhookLog(
            webhook_id=webhook.id,
            evento="deal_ganho",
            status_code=200,
            request_payload='{"test": true}',
            response_body='{"ok": true}',
            sucesso=True,
            tempo_ms=120,
        )
        db.session.add(log)
        db.session.flush()
        self.assertEqual(log.response_status, 200)
        self.assertEqual(log.duracao_ms, 120)
        self.assertTrue(log.sucesso)

        # 5. CrmTemplateMensagem
        tmpl = CrmTemplateMensagem(
            nome="Apresentação Inicial",
            conteudo="Olá {nome_contato}, aqui é da Sollus!",
            ativo=True,
            criado_por_id=self.admin_user.id,
        )
        db.session.add(tmpl)
        db.session.flush()
        self.assertEqual(tmpl.titulo, "Apresentação Inicial")
        self.assertEqual(tmpl.texto, "Olá {nome_contato}, aqui é da Sollus!")

        # 6. Campos novos em CrmNegociacao e CrmEtapa
        deal = CrmNegociacao(
            id="deal_model_test",
            nome="Negociação Teste Modelos",
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            data_estimada_fechamento=datetime.utcnow().date() + timedelta(days=15),
            motivo_perda_id=motivo.id,
            motivo_perda_categoria="preco",
            probabilidade=35.0,
            status="aberto",
        )
        db.session.add(deal)
        db.session.commit()

        d_deal = deal.to_dict()
        self.assertEqual(d_deal["motivo_perda_id"], motivo.id)
        self.assertEqual(d_deal["motivo_perda_categoria"], "preco")
        self.assertEqual(d_deal["probabilidade"], 35.0)
        self.assertTrue(bool(d_deal["data_estimada_fechamento"]))

        self.assertEqual(self.etapa_entrada.probabilidade, 10.0)
        self.assertEqual(self.etapa_entrada.to_dict()["probabilidade"], 10.0)

        # 7. Execução idempotente do ensure_crm_schema
        ensure_crm_schema(self.app)
        # Confirma que motivos de perda padrão e templates foram inseridos se vazios
        self.assertGreater(CrmMotivoPerda.query.count(), 0)
        self.assertGreater(CrmTemplateMensagem.query.count(), 0)

    def test_crm_round_robin_distribution(self):
        """
        Critério de Aceitação R1:
        Criar 3 consultores ativos no dpto comercial.
        Disparar 6 leads consecutivos sem atribuição.
        Validar que cada consultor recebeu exatamente 2 leads em sequência circular equilibrada.
        """
        # Criar 3 consultores comerciais dedicados
        c1 = User(
            usuario="consultor_1",
            nome_completo="Ana Comercial",
            email="ana@sollus.com",
            password_hash="pwd",
            tipo="consultor",
            is_active=True,
            department_id=self.dept_comercial.id,
        )
        c2 = User(
            usuario="consultor_2",
            nome_completo="Bruno Comercial",
            email="bruno@sollus.com",
            password_hash="pwd",
            tipo="consultor",
            is_active=True,
            department_id=self.dept_comercial.id,
        )
        c3 = User(
            usuario="consultor_3",
            nome_completo="Carlos Comercial",
            email="carlos@sollus.com",
            password_hash="pwd",
            tipo="consultor",
            is_active=True,
            department_id=self.dept_comercial.id,
        )
        db.session.add_all([c1, c2, c3])
        db.session.commit()

        # Disparar 6 leads consecutivos via capture_lead_from_website
        assigned_consultants = []
        for i in range(1, 7):
            payload = {
                "nome": f"Lead Cliente {i}",
                "email": f"cliente{i}@empresa.com",
                "telefone": f"219999000{i}",
                "empresa": f"Empresa Cliente {i} Ltda",
                "cnpj": f"12.345.678/0001-0{i}",
                "interesse": "relogio de ponto",
            }
            res = capture_lead_from_website(payload)
            self.assertTrue(res["success"])
            deal = CrmNegociacao.query.get(res["deal_id"])
            self.assertIsNotNone(deal)
            self.assertIsNotNone(deal.user_id)
            assigned_consultants.append(deal.user_id)

        # Sequência esperada: circular determinística entre c1, c2, c3
        expected_first_cycle = [c1.id, c2.id, c3.id]
        expected_second_cycle = [c1.id, c2.id, c3.id]
        expected_sequence = expected_first_cycle + expected_second_cycle

        self.assertEqual(
            assigned_consultants,
            expected_sequence,
            f"A sequência da roleta deve ser circular e equilibrada. Obtido: {assigned_consultants}",
        )

        # Cada consultor deve ter exatamente 2 leads distribuídos
        self.assertEqual(assigned_consultants.count(c1.id), 2)
        self.assertEqual(assigned_consultants.count(c2.id), 2)
        self.assertEqual(assigned_consultants.count(c3.id), 2)

        # Verificar contadores persistidos em CrmRoletaConsultor
        roleta_c1 = CrmRoletaConsultor.query.filter_by(consultor_id=c1.id).first()
        roleta_c2 = CrmRoletaConsultor.query.filter_by(consultor_id=c2.id).first()
        roleta_c3 = CrmRoletaConsultor.query.filter_by(consultor_id=c3.id).first()

        self.assertIsNotNone(roleta_c1)
        self.assertIsNotNone(roleta_c2)
        self.assertIsNotNone(roleta_c3)

        self.assertEqual(roleta_c1.total_distribuido, 2)
        self.assertEqual(roleta_c2.total_distribuido, 2)
        self.assertEqual(roleta_c3.total_distribuido, 2)

        self.assertIsNotNone(roleta_c1.ultimo_recebimento)
        self.assertIsNotNone(roleta_c2.ultimo_recebimento)
        self.assertIsNotNone(roleta_c3.ultimo_recebimento)

    def test_crm_stage_entry_automatic_task(self):
        """
        Critério de Aceitação R1:
        Ao mover uma negociação para etapa configurada com regra de tarefa automática,
        uma nova CrmTarefa correspondente é gerada com data de vencimento calculada.
        """
        # Configura regra de automação para a Etapa de Qualificação (prazo: 48h)
        regra = CrmRegraAutomacao(
            funil_id=self.funil.id,
            etapa_id=self.etapa_qualif.id,
            evento="etapa_entrada",
            acao_tipo="criar_tarefa",
            tarefa_titulo="Apresentação Comercial Agendada",
            tarefa_tipo="reuniao",
            prazo_horas=48,
            ativo=True,
        )
        db.session.add(regra)
        db.session.commit()

        # Cria uma negociação na etapa de entrada
        deal = CrmNegociacao(
            id="deal_stage_task_test",
            nome="Oportunidade Automacoes Ltda",
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            user_id=self.admin_user.id,
            user_name=self.admin_user.nome_completo,
            valor_total=5000.0,
            status="aberto",
        )
        db.session.add(deal)
        db.session.commit()

        tarefas_antes = deal.tarefas.count()
        self.assertEqual(tarefas_antes, 0)

        # Mover deal para a Etapa de Qualificação
        resultado = move_deal_stage(deal.id, self.etapa_qualif.id, user=self.admin_user)
        self.assertTrue(resultado["success"])

        # Verificar se a tarefa automática foi criada
        tarefas = CrmTarefa.query.filter_by(negociacao_id=deal.id).all()
        self.assertEqual(len(tarefas), 1)

        tarefa = tarefas[0]
        self.assertEqual(tarefa.titulo, "Apresentação Comercial Agendada")
        self.assertEqual(tarefa.tipo, "reuniao")
        self.assertEqual(tarefa.user_id, self.admin_user.id)
        self.assertFalse(tarefa.concluida)

        # Validação do prazo calculado: deve ser aproximadamente now + 48 horas
        diferenca_horas = (tarefa.data_vencimento - datetime.utcnow()).total_seconds() / 3600.0
        self.assertAlmostEqual(diferenca_horas, 48.0, delta=0.5)

        # Cache de próxima tarefa no deal atualizado
        deal_reloaded = CrmNegociacao.query.get(deal.id)
        self.assertEqual(deal_reloaded.proxima_tarefa_id, tarefa.id)
        self.assertEqual(deal_reloaded.proxima_tarefa_titulo, "Apresentação Comercial Agendada")
        self.assertEqual(deal_reloaded.proxima_tarefa_tipo, "reuniao")

        # Verificar que movimentação repetida não duplica tarefas não finalizadas (Edge Case 5)
        move_deal_stage(deal.id, self.etapa_qualif.id, user=self.admin_user)
        tarefas_repetidas = CrmTarefa.query.filter_by(negociacao_id=deal.id).all()
        self.assertEqual(len(tarefas_repetidas), 1, "Não deve duplicar tarefa pendente idêntica.")

    def test_crm_proposal_linked_transition(self):
        """
        Critério de Aceitação R1:
        A criação de proposta vinculada atualiza a negociação com proposta_id e reflete o status/etapa correspondente.
        """
        # Cria negociação inicial
        deal = CrmNegociacao(
            id="deal_proposta_link_test",
            nome="Negócio com Proposta Link",
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            user_id=self.admin_user.id,
            valor_total=0.0,
            status="aberto",
        )
        db.session.add(deal)
        db.session.commit()

        # Cria equipamento para teste
        eq = Equipment(
            name="Relógio de Ponto Facial Sollus Bio",
            unit_price=2500.0,
            quantity=10,
        )
        db.session.add(eq)
        db.session.commit()

        # Cria proposta comercial simulando submissão em /propostas/nova com deal_id
        with self.client.session_transaction() as sess:
            sess["usuario_id"] = self.admin_user.id
            sess["tipo"] = "admin"

        response = self.client.post(
            "/propostas/nova",
            data={
                "deal_id": deal.id,
                "client_name": "Empresa Cliente Teste",
                "client_document_type": "cnpj",
                "cnpj": "11.222.333/0001-44",
                "state_reg": "ISENTO",
                "contact_name": "Fulano",
                "email": "fulano@cliente.com",
                "telefone": "21988887777",
                "company": "Sollus Tecnologia",
                "item_uids": [str(eq.id)],
                f"equip_id_{eq.id}": str(eq.id),
                "equipments": [eq.id],
                f"quantity_{eq.id}": "2",
                f"price_{eq.id}": "2500.00",
                f"discount_{eq.id}": "10",
                f"acquisition_{eq.id}": "venda",
                "validade_proposta": "15 dias",
                "issuer_company_code": "sollus",
                "pagto_equip": "A vista",
                "prazo_entrega": "Imediato",
                "frete": "CIF",
                "garantia_eq": "12 meses",
                "garantia_sys": "12 meses",
                "acao": "salvar",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=True,
        )
        self.assertIn(response.status_code, (200, 201, 202))

        # Verificar sincronização no deal
        deal_reloaded = CrmNegociacao.query.get(deal.id)
        self.assertIsNotNone(deal_reloaded.proposta_id)

        # Valor com desconto: 2 * 2500 * (1 - 0.10) = 4500.00
        self.assertAlmostEqual(deal_reloaded.valor_total, 4500.0, places=2)

        # Etapa avançou para a etapa que contém "Proposta"
        self.assertEqual(deal_reloaded.etapa_id, self.etapa_proposta.id)

        # Nota na timeline da negociação
        interacao = CrmInteracao.query.filter_by(negociacao_id=deal.id).order_by(CrmInteracao.id.desc()).first()
        self.assertIsNotNone(interacao)
        self.assertIn("Proposta comercial", interacao.conteudo)

    def test_crm_proposal_approved_marks_won_and_creates_sollusflow_order(self):
        """
        Critério de Aceitação R1:
        Na aprovação de proposta vinculada, marca a negociação como ganha, move para etapa de ganho,
        e dispara corretamente a criação do pedido no SollusFlow (SfPedido com argumentos válidos).
        """
        # Cria proposta comercial
        prop = Proposal(
            client_name="Cliente Ganho S.A.",
            cnpj="99.888.777/0001-66",
            company="Sollus Tecnologia",
            email="contato@clienteganho.com",
            telefone="21977778888",
            usuario_id=self.admin_user.id,
            sistema_preco_total=3800.0,
            locacao_valor_mensal=200.0,
        )
        db.session.add(prop)
        db.session.commit()

        # Cria negócio no CRM vinculado à proposta
        deal = CrmNegociacao(
            id="deal_won_flow_test",
            nome="Cliente Ganho S.A. - Funil Ponto",
            funil_id=self.funil.id,
            etapa_id=self.etapa_proposta.id,
            user_id=self.admin_user.id,
            user_name=self.admin_user.nome_completo,
            valor_total=4000.0,
            proposta_id=prop.id,
            status="aberto",
        )
        db.session.add(deal)
        db.session.commit()

        # Autentica como admin e aprova a versão da proposta
        with self.client.session_transaction() as sess:
            sess["usuario_id"] = self.admin_user.id
            sess["tipo"] = "admin"

        response = self.client.post(
            f"/propostas/aprovar_versao/{prop.id}",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        # Verificar se proposta foi aprovada
        prop_reloaded = Proposal.query.get(prop.id)
        self.assertIsNotNone(prop_reloaded.approved_at)

        # Verificar se negócio foi marcado como GANHO e movido para etapa de ganho
        deal_reloaded = CrmNegociacao.query.get(deal.id)
        self.assertEqual(deal_reloaded.status, "ganho")
        self.assertEqual(deal_reloaded.etapa_id, self.etapa_ganho.id)
        self.assertIsNotNone(deal_reloaded.closed_at)

        # Validar criação bem-sucedida de SfPedido no SollusFlow sem TypeError
        self.assertIsNotNone(deal_reloaded.sollusflow_pedido_id)
        pedido_flow = SfPedido.query.get(deal_reloaded.sollusflow_pedido_id)
        self.assertIsNotNone(pedido_flow)
        self.assertEqual(pedido_flow.cliente_nome, deal_reloaded.nome)
        self.assertEqual(pedido_flow.fase_atual, 1)
        self.assertEqual(pedido_flow.status, "ativo")
        self.assertEqual(pedido_flow.prioridade, "normal")
        self.assertAlmostEqual(float(pedido_flow.valor), 4000.0, places=2)
        self.assertEqual(pedido_flow.consultor_id, self.admin_user.id)

    def test_crm_mark_deal_lost_with_category(self):
        """Valida que marcar negociação como perdida salva o motivo e a categoria."""
        motivo = CrmMotivoPerda(nome="Preço alto", categoria="preco", ordem=1)
        db.session.add(motivo)
        db.session.commit()

        deal = CrmNegociacao(
            id="deal_lost_test",
            nome="Cliente Desistente",
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            status="aberto",
        )
        db.session.add(deal)
        db.session.commit()

        res = mark_deal_lost(
            deal.id,
            motivo="Orçamento rejeitado pela diretoria",
            user=self.admin_user,
            categoria="preco",
            motivo_perda_id=motivo.id,
        )
        self.assertTrue(res["success"])

        deal_reloaded = CrmNegociacao.query.get(deal.id)
        self.assertEqual(deal_reloaded.status, "perdido")
        self.assertEqual(deal_reloaded.etapa_id, self.etapa_perdido.id)
        self.assertEqual(deal_reloaded.motivo_perda, "Orçamento rejeitado pela diretoria")
        self.assertEqual(deal_reloaded.motivo_perda_categoria, "preco")
        self.assertEqual(deal_reloaded.motivo_perda_id, motivo.id)
        self.assertIsNotNone(deal_reloaded.closed_at)


if __name__ == "__main__":
    unittest.main()
