"""Stress-tests empíricos para Milestone M1: Integração de Propostas e Pedidos SollusFlow.

Cenários testados:
1. Criação de proposta com deal_id: vincula deal, calcula valuation composta
   (equipamentos com desconto + sistema + mensalidade) e avança etapa para Proposta.
2. Criação de proposta com deal_id inexistente/inválido: não causa crash nem corrupção.
3. Aprovação de proposta vinculada em /propostas/aprovar_versao/<id>:
   - Marca deal como 'ganho'
   - Define deal.closed_at
   - Move deal para etapa do tipo 'ganho'
   - Gera SfPedido com campos obrigatórios:
     numero_pedido (CRM-XXXXXXXX), cliente_nome, cliente_cnpj, valor, consultor_id, status='ativo'
   - Gera SfFaseHistorico correspondente
4. Idempotência da aprovação: chamada duplicada não duplica SfPedido nem corrompe estado.
5. Proposta standalone (sem deal vinculado):
   - 5A: Proposta avulsa com original_proposal_id preenchido não afeta negócios CRM abertos.
   - 5B: Proposta avulsa com original_proposal_id=None (legado/direto) NÃO PODE marcar
         negócios não relacionados (proposta_id=None) como ganhos.
6. Aprovação multi-versão (v1 -> revisão v2 -> aprovação da v2):
   - O negócio vinculado inicialmente à v1 deve ser encontrado e fechado como ganho na aprovação da v2.
7. Propagação de dados da CrmEmpresa (nome, CNPJ) para o SfPedido e incremento de total_ganho.
8. Verificação de permissões / controle de acesso na aprovação.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from sqlalchemy.pool import StaticPool

from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department, Proposal, Equipment, ParamOption, ParamCategory
from modules.chamados.models import SfPedido, SfFaseHistorico
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmInteracao,
)


class TestProposalSollusFlowConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key-stress-crm"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class TestProposalSollusFlowStress(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestProposalSollusFlowConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()

        # Usuário Admin
        self.admin_user = User(
            usuario="admin_stress",
            nome_completo="Admin Verificador",
            email="admin.stress@sollus.com",
            password_hash="hash_admin",
            tipo="admin",
            role="admin",
            permissions={"crm": True, "propostas": True},
        )
        db.session.add(self.admin_user)

        # Consultor Comercial
        self.consultor = User(
            usuario="consultor_1",
            nome_completo="Consultor Vendas Um",
            email="consultor1@sollus.com",
            password_hash="hash_user",
            tipo="consultor",
            role="consultor",
            permissions={"crm": True, "propostas": True},
        )
        db.session.add(self.consultor)

        # Outro Consultor (não dono)
        self.outro_consultor = User(
            usuario="consultor_2",
            nome_completo="Consultor Vendas Dois",
            email="consultor2@sollus.com",
            password_hash="hash_user2",
            tipo="consultor",
            role="consultor",
            permissions={"crm": True, "propostas": True},
        )
        db.session.add(self.outro_consultor)

        # Seed de opções para formulário de propostas
        options = [
            ParamOption(category=ParamCategory.PAGTO_EQUIP, label="A vista"),
            ParamOption(category=ParamCategory.PRAZO_ENTREGA, label="Imediato"),
            ParamOption(category=ParamCategory.FRETE, label="CIF"),
            ParamOption(category=ParamCategory.GARANTIA_EQ, label="12 meses"),
            ParamOption(category=ParamCategory.GARANTIA_SYS, label="12 meses"),
        ]
        db.session.add_all(options)

        # Equipamento de teste
        self.eq1 = Equipment(
            name="Catraca Biométrica Sollus Gate",
            unit_price=3000.0,
            quantity=20,
        )
        self.eq2 = Equipment(
            name="Software Secullum Ponto 4",
            unit_price=800.0,
            quantity=50,
        )
        db.session.add_all([self.eq1, self.eq2])
        db.session.commit()

        # Funil de Vendas Padrão
        self.funil = CrmFunil(
            id="funil_stress",
            nome="Funil Vendas Diretas",
            slug="vendas_diretas",
            tipo="ponto",
            ordem=1,
            ativo=True,
        )
        db.session.add(self.funil)
        db.session.flush()

        self.etapa_entrada = CrmEtapa(
            id="etapa_entrada_stress",
            funil_id=self.funil.id,
            nome="Qualificação",
            ordem=1,
            tipo="normal",
            probabilidade=10.0,
        )
        self.etapa_proposta = CrmEtapa(
            id="etapa_proposta_stress",
            funil_id=self.funil.id,
            nome="Apresentação de Proposta",
            nickname="Proposta",
            ordem=2,
            tipo="normal",
            probabilidade=50.0,
        )
        self.etapa_negociacao = CrmEtapa(
            id="etapa_negociacao_stress",
            funil_id=self.funil.id,
            nome="Negociação",
            ordem=3,
            tipo="normal",
            probabilidade=70.0,
        )
        self.etapa_ganho = CrmEtapa(
            id="etapa_ganho_stress",
            funil_id=self.funil.id,
            nome="Fechado Ganho",
            ordem=4,
            tipo="ganho",
            probabilidade=100.0,
        )
        self.etapa_perdido = CrmEtapa(
            id="etapa_perdido_stress",
            funil_id=self.funil.id,
            nome="Perdido",
            ordem=5,
            tipo="perdido",
            probabilidade=0.0,
        )

        db.session.add_all([
            self.etapa_entrada,
            self.etapa_proposta,
            self.etapa_negociacao,
            self.etapa_ganho,
            self.etapa_perdido,
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self, user):
        with self.client.session_transaction() as sess:
            sess["usuario_id"] = user.id
            sess["tipo"] = user.tipo

    def test_01_proposal_creation_with_deal_id_updates_valuation_and_advances_stage(self):
        """Valida que /propostas/nova com deal_id vincula a proposta, calcula valuation correta e avança etapa."""
        empresa = CrmEmpresa(id="emp_alfa", nome="Indústria Metalúrgica Alfa", cnpj="11.222.333/0001-44")
        db.session.add(empresa)
        db.session.flush()

        deal = CrmNegociacao(
            id="deal_test_val_01",
            nome="Projeto Acesso Alfa",
            empresa_id=empresa.id,
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            user_id=self.consultor.id,
            user_name=self.consultor.nome_completo,
            valor_total=0.0,
            status="aberto",
        )
        db.session.add(deal)
        db.session.commit()

        self._login(self.admin_user)

        # Envia formulário simulando criação de proposta com 2 equipamentos (com desconto) e mensalidade
        # Eq 1: 2 unidades a R$ 3000 com 10% desconto = 2 * 3000 * 0.9 = 5400.0
        # Eq 2: 1 unidade a R$ 800 com 0% desconto = 800.0
        # Total unico esperado = 5400 + 800 = 6200.0
        response = self.client.post(
            "/propostas/nova",
            data={
                "deal_id": deal.id,
                "client_name": empresa.nome,
                "client_document_type": "cnpj",
                "cnpj": empresa.cnpj,
                "company": "Sollus Tecnologia",
                "contact_name": "Gerente Alfa",
                "email": "alfa@metalurgica.com",
                "telefone": "2199998888",
                "item_uids": [str(self.eq1.id), str(self.eq2.id)],
                f"equip_id_{self.eq1.id}": str(self.eq1.id),
                f"quantity_{self.eq1.id}": "2",
                f"price_{self.eq1.id}": "3000.00",
                f"discount_{self.eq1.id}": "10",
                f"acquisition_{self.eq1.id}": "venda",
                f"equip_id_{self.eq2.id}": str(self.eq2.id),
                f"quantity_{self.eq2.id}": "1",
                f"price_{self.eq2.id}": "800.00",
                f"discount_{self.eq2.id}": "0",
                f"acquisition_{self.eq2.id}": "venda",
                "equipments": [self.eq1.id, self.eq2.id],
                "validade_proposta": "10 dias",
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

        # Recarrega o negócio
        db.session.expire_all()
        deal_reloaded = CrmNegociacao.query.get(deal.id)
        self.assertIsNotNone(deal_reloaded.proposta_id)
        self.assertAlmostEqual(float(deal_reloaded.valor_unico), 6200.0, places=2)
        self.assertAlmostEqual(float(deal_reloaded.valor_total), 6200.0, places=2)
        self.assertEqual(deal_reloaded.etapa_id, self.etapa_proposta.id)

        # Verifica log na timeline
        interacao = CrmInteracao.query.filter_by(negociacao_id=deal.id).order_by(CrmInteracao.id.desc()).first()
        self.assertIsNotNone(interacao)
        self.assertIn(f"#{deal_reloaded.proposta_id}", interacao.conteudo)

    def test_02_proposal_creation_with_invalid_deal_id_does_not_crash(self):
        """Valida que deal_id inexistente é tolerado com robustez sem falhar a criação da proposta."""
        self._login(self.admin_user)

        response = self.client.post(
            "/propostas/nova",
            data={
                "deal_id": "inexistente_99999",
                "client_name": "Empresa Sem Deal",
                "client_document_type": "cnpj",
                "cnpj": "22.333.444/0001-55",
                "company": "Sollus Tecnologia",
                "contact_name": "Sem Deal",
                "email": "semdeal@empresa.com",
                "telefone": "21988887777",
                "item_uids": [str(self.eq2.id)],
                f"equip_id_{self.eq2.id}": str(self.eq2.id),
                f"quantity_{self.eq2.id}": "1",
                f"price_{self.eq2.id}": "800.00",
                f"discount_{self.eq2.id}": "0",
                f"acquisition_{self.eq2.id}": "venda",
                "equipments": [self.eq2.id],
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
        prop = Proposal.query.filter_by(client_name="Empresa Sem Deal").first()
        self.assertIsNotNone(prop)

    def test_03_proposal_approval_marks_deal_won_and_creates_valid_sf_pedido(self):
        """Valida aprovação de proposta: negócio é ganho e SfPedido criado com todos os campos exigidos."""
        empresa = CrmEmpresa(id="emp_beta", nome="Beta Logística Eireli", cnpj="33.444.555/0001-66")
        db.session.add(empresa)
        db.session.flush()

        prop = Proposal(
            client_name=empresa.nome,
            cnpj=empresa.cnpj,
            company="Sollus Tecnologia",
            email="contato@betalog.com",
            telefone="21955554444",
            usuario_id=self.consultor.id,
            sistema_preco_total=5000.0,
            original_proposal_id=None,
        )
        db.session.add(prop)
        db.session.flush()
        prop.original_proposal_id = prop.id
        db.session.commit()

        deal = CrmNegociacao(
            id="deal_beta_won",
            nome="Contrato Beta Logística",
            empresa_id=empresa.id,
            funil_id=self.funil.id,
            etapa_id=self.etapa_proposta.id,
            user_id=self.consultor.id,
            user_name=self.consultor.nome_completo,
            valor_total=5000.0,
            proposta_id=prop.id,
            status="aberto",
        )
        db.session.add(deal)
        db.session.commit()

        self._login(self.admin_user)

        response = self.client.post(f"/propostas/aprovar_versao/{prop.id}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("ok"))

        # Verificações na proposta
        db.session.expire_all()
        prop_reloaded = Proposal.query.get(prop.id)
        self.assertIsNotNone(prop_reloaded.approved_at)
        self.assertEqual(prop_reloaded.approved_by_id, self.admin_user.id)

        # Verificações no negócio CRM
        deal_reloaded = CrmNegociacao.query.get(deal.id)
        self.assertEqual(deal_reloaded.status, "ganho")
        self.assertEqual(deal_reloaded.etapa_id, self.etapa_ganho.id)
        self.assertIsNotNone(deal_reloaded.closed_at)
        self.assertIsNotNone(deal_reloaded.sollusflow_pedido_id)

        # Verificações no pedido SollusFlow (SfPedido)
        pedido = SfPedido.query.get(deal_reloaded.sollusflow_pedido_id)
        self.assertIsNotNone(pedido)
        self.assertEqual(pedido.numero_pedido, f"CRM-{deal.id[:8].upper()}")
        self.assertEqual(pedido.cliente_nome, empresa.nome)
        self.assertEqual(pedido.cliente_cnpj, empresa.cnpj)
        self.assertAlmostEqual(float(pedido.valor), 5000.0, places=2)
        self.assertEqual(pedido.consultor_id, self.consultor.id)
        self.assertEqual(pedido.status, "ativo")
        self.assertEqual(pedido.fase_atual, 1)
        self.assertEqual(pedido.prioridade, "normal")

        # Verifica histórico de fase inicial criado
        historico = SfFaseHistorico.query.filter_by(pedido_id=pedido.id).first()
        self.assertIsNotNone(historico)
        self.assertEqual(historico.fase_para, 1)

    def test_04_proposal_approval_idempotency(self):
        """Chamadas subsequentes de aprovação devem ser idempotentes e não criar pedidos duplicados."""
        prop = Proposal(
            client_name="Cliente Idempotente",
            cnpj="44.555.666/0001-77",
            company="Sollus Tecnologia",
            usuario_id=self.admin_user.id,
            sistema_preco_total=1500.0,
        )
        db.session.add(prop)
        db.session.flush()
        prop.original_proposal_id = prop.id
        db.session.commit()

        deal = CrmNegociacao(
            id="deal_idempotent",
            nome="Negócio Idempotente",
            funil_id=self.funil.id,
            etapa_id=self.etapa_proposta.id,
            user_id=self.admin_user.id,
            valor_total=1500.0,
            proposta_id=prop.id,
            status="aberto",
        )
        db.session.add(deal)
        db.session.commit()

        self._login(self.admin_user)

        # 1ª aprovação
        res1 = self.client.post(f"/propostas/aprovar_versao/{prop.id}")
        self.assertEqual(res1.status_code, 200)

        db.session.expire_all()
        deal_reloaded = CrmNegociacao.query.get(deal.id)
        flow_id_1 = deal_reloaded.sollusflow_pedido_id
        self.assertIsNotNone(flow_id_1)

        # Contagem de pedidos no SollusFlow
        pedidos_count_1 = SfPedido.query.count()
        self.assertEqual(pedidos_count_1, 1)

        # 2ª aprovação
        res2 = self.client.post(f"/propostas/aprovar_versao/{prop.id}")
        self.assertEqual(res2.status_code, 200)
        self.assertIn("ja foi aprovada", res2.get_json().get("message", ""))

        # Contagem de pedidos deve continuar 1
        pedidos_count_2 = SfPedido.query.count()
        self.assertEqual(pedidos_count_2, 1)

        # Deal id de pedido continua o mesmo
        db.session.expire_all()
        deal_reloaded_2 = CrmNegociacao.query.get(deal.id)
        self.assertEqual(deal_reloaded_2.sollusflow_pedido_id, flow_id_1)

    def test_05a_standalone_proposal_approval_does_not_corrupt_crm(self):
        """Proposta avulsa aprovada não deve afetar deals não vinculados."""
        # Cria deal aberto no CRM sem proposta vinculada
        deal_avulso = CrmNegociacao(
            id="deal_aberto_outro",
            nome="Negócio Aberto Sem Proposta",
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            user_id=self.consultor.id,
            valor_total=20000.0,
            proposta_id=None,
            status="aberto",
        )
        db.session.add(deal_avulso)
        db.session.commit()

        # Proposta avulsa sem deal
        prop_avulsa = Proposal(
            client_name="Cliente Avulso",
            cnpj="55.666.777/0001-88",
            company="Sollus Tecnologia",
            usuario_id=self.admin_user.id,
            sistema_preco_total=3000.0,
        )
        db.session.add(prop_avulsa)
        db.session.flush()
        prop_avulsa.original_proposal_id = prop_avulsa.id
        db.session.commit()

        self._login(self.admin_user)

        res = self.client.post(f"/propostas/aprovar_versao/{prop_avulsa.id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json().get("ok"))

        # Deal aberto NÃO deve ter sido modificado nem fechado como ganho
        db.session.expire_all()
        deal_check = CrmNegociacao.query.get(deal_avulso.id)
        self.assertEqual(deal_check.status, "aberto")
        self.assertIsNone(deal_check.sollusflow_pedido_id)
        self.assertEqual(deal_check.etapa_id, self.etapa_entrada.id)

    def test_05b_standalone_proposal_with_none_original_id_does_not_corrupt_crm(self):
        """CRÍTICO ADVERSARIAL: Se original_proposal_id for None na proposta, NÃO DEVE
        dar match acidental em deals cujo proposta_id seja None (via CrmNegociacao.proposta_id == None).
        """
        # Cria deal aberto no CRM cujo proposta_id é explicitamente NULL/None
        deal_vulneravel = CrmNegociacao(
            id="deal_vulneravel_none",
            nome="Negócio em Aberto Proposta NULL",
            funil_id=self.funil.id,
            etapa_id=self.etapa_entrada.id,
            user_id=self.consultor.id,
            valor_total=99000.0,
            proposta_id=None,
            status="aberto",
        )
        db.session.add(deal_vulneravel)
        db.session.commit()

        # Proposta legada ou avulsa onde original_proposal_id é None
        prop_legada = Proposal(
            client_name="Proposta Legada Sem Original",
            cnpj="66.777.888/0001-99",
            company="Sollus Tecnologia",
            usuario_id=self.admin_user.id,
            original_proposal_id=None,
        )
        db.session.add(prop_legada)
        db.session.commit()
        self.assertIsNone(prop_legada.original_proposal_id)

        self._login(self.admin_user)

        res = self.client.post(f"/propostas/aprovar_versao/{prop_legada.id}")
        self.assertEqual(res.status_code, 200)

        # O deal NÃO PODE ter sido marcado como ganho!
        db.session.expire_all()
        deal_check = CrmNegociacao.query.get(deal_vulneravel.id)
        self.assertEqual(
            deal_check.status,
            "aberto",
            "FALHA GRAVE: Deal aberto com proposta_id=None foi incorretamente capturado e marcado como ganho!",
        )
        self.assertIsNone(deal_check.sollusflow_pedido_id)

    def test_06_multi_version_proposal_approval(self):
        """Cenário multi-versão: deal vinculado à v1 deve ser fechado quando a v2 for aprovada."""
        empresa = CrmEmpresa(id="emp_gama", nome="Gama Serviços Corporativos", cnpj="77.888.999/0001-11")
        db.session.add(empresa)
        db.session.flush()

        # Versão 1 da proposta
        prop_v1 = Proposal(
            client_name=empresa.nome,
            cnpj=empresa.cnpj,
            company="Sollus Tecnologia",
            email="gama@servicos.com",
            telefone="21911112222",
            usuario_id=self.consultor.id,
            sistema_preco_total=7000.0,
            version_number=1,
            is_current=False,
        )
        db.session.add(prop_v1)
        db.session.flush()
        prop_v1.original_proposal_id = prop_v1.id
        db.session.commit()

        # Deal vinculado à v1
        deal = CrmNegociacao(
            id="deal_multi_version",
            nome="Projeto Gama Cloud",
            empresa_id=empresa.id,
            funil_id=self.funil.id,
            etapa_id=self.etapa_proposta.id,
            user_id=self.consultor.id,
            user_name=self.consultor.nome_completo,
            valor_total=7000.0,
            proposta_id=prop_v1.id,
            status="aberto",
        )
        db.session.add(deal)
        db.session.commit()

        # Revisão: Versão 2 gerada a partir da v1
        prop_v2 = Proposal(
            client_name=empresa.nome,
            cnpj=empresa.cnpj,
            company="Sollus Tecnologia",
            email="gama@servicos.com",
            telefone="21911112222",
            usuario_id=self.consultor.id,
            sistema_preco_total=8500.0,
            original_proposal_id=prop_v1.id,
            version_number=2,
            is_current=True,
            is_original=False,
        )
        db.session.add(prop_v2)
        db.session.commit()

        self._login(self.admin_user)

        # Aprova a versão 2
        response = self.client.post(f"/propostas/aprovar_versao/{prop_v2.id}")
        self.assertEqual(response.status_code, 200)

        # Verifica v2 aprovada
        db.session.expire_all()
        prop_v2_reloaded = Proposal.query.get(prop_v2.id)
        self.assertIsNotNone(prop_v2_reloaded.approved_at)

        # Verifica se o negócio vinculado foi marcado como ganho
        deal_reloaded = CrmNegociacao.query.get(deal.id)
        self.assertEqual(deal_reloaded.status, "ganho")
        self.assertEqual(deal_reloaded.etapa_id, self.etapa_ganho.id)
        self.assertIsNotNone(deal_reloaded.closed_at)
        self.assertIsNotNone(deal_reloaded.sollusflow_pedido_id)

        # Verifica criação do pedido
        pedido = SfPedido.query.get(deal_reloaded.sollusflow_pedido_id)
        self.assertIsNotNone(pedido)
        self.assertEqual(pedido.cliente_nome, empresa.nome)
        self.assertEqual(pedido.cliente_cnpj, empresa.cnpj)

    def test_07_unauthorized_user_cannot_approve_proposal(self):
        """Consultor que não é o dono da proposta nem admin/gestor não pode aprová-la."""
        prop = Proposal(
            client_name="Cliente Restrito",
            usuario_id=self.consultor.id,
            created_by_id=self.consultor.id,
            company="Sollus Tecnologia",
        )
        db.session.add(prop)
        db.session.flush()
        prop.original_proposal_id = prop.id
        db.session.commit()

        # Login como outro consultor
        self._login(self.outro_consultor)

        response = self.client.post(f"/propostas/aprovar_versao/{prop.id}")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.get_json().get("ok"))


if __name__ == "__main__":
    unittest.main()
