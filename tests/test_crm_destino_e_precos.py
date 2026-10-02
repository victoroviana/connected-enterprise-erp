"""Testes unitários e de integração para:
1. Destino de Leads (Roteamento Regional por DDD, Estado/UF, Filial e Roleta).
2. Tabela de Consulta de Preços no Sollus CRM.
3. Sincronização Bidirecional Estoque <-> CRM e Histórico de Preços.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime
from sqlalchemy.pool import StaticPool

from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department, Equipment
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmRegraDistribuicao,
    CrmEquipamentoHistoricoPreco,
)
from modules.crm.services.crm_service import (
    detect_lead_region,
    extract_ddd_from_phone,
    find_matching_distribution_rule,
    distribute_deal_round_robin,
    update_equipment_price_and_description,
    get_equipment_price_history,
    create_deal,
    calculate_adjusted_price,
    apply_bulk_price_adjustment,
)
import io
from PIL import Image


class TestConfigDestinoPrecos:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key-crm-destino-precos"
    CRM_WEBHOOK_API_TOKEN = "token_test_destino_123"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class CrmDestinoEPrecosTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfigDestinoPrecos)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()

        # Departamento Comercial
        self.dept = Department(name="COMERCIAL", slug="comercial")
        db.session.add(self.dept)
        db.session.flush()

        # Consultores
        self.consultor_sp = User(
            id=5009,
            usuario="hizael.ferreira",
            nome_completo="Hizael Ferreira (SP)",
            email="hizael@sollustecnologia.com",
            password_hash="hash_sp",
            tipo="consultorsp",
            role="usuario",
            is_active=True,
            department_id=self.dept.id,
            permissions={"crm": True},
        )
        self.ricardo_pm = User(
            id=5006,
            usuario="ricardo.simoes",
            nome_completo="Ricardo Simões",
            email="ricardo@sollustecnologia.com",
            password_hash="hash_pm",
            tipo="admin",
            role="admin",
            is_active=True,
            department_id=self.dept.id,
            permissions={"crm": True},
        )
        self.consultor_rj = User(
            usuario="gilson_rj",
            nome_completo="Gilson Freitas (RJ)",
            email="gilson@sollustecnologia.com",
            password_hash="hash_rj",
            tipo="admin",
            role="admin",
            is_active=True,
            department_id=self.dept.id,
            permissions={"crm": True, "estoque": True},
        )
        self.consultor_geral = User(
            usuario="ana_comercial",
            nome_completo="Ana Clara Comercial",
            email="ana@sollustecnologia.com",
            password_hash="hash_ana",
            tipo="consultor",
            role="usuario",
            is_active=True,
            department_id=self.dept.id,
            permissions={"crm": True, "estoque": True},
        )
        db.session.add_all([self.consultor_sp, self.ricardo_pm, self.consultor_rj, self.consultor_geral])
        db.session.flush()

        # Funil Padrão e Etapas
        self.funil = CrmFunil(id="funil_teste", nome="Funil Vendas", ativo=True, ordem=1)
        db.session.add(self.funil)
        db.session.flush()

        self.etapa1 = CrmEtapa(id="etapa_lead", funil_id=self.funil.id, nome="Lead Recebido", ordem=1, tipo="normal")
        self.etapa2 = CrmEtapa(id="etapa_contato", funil_id=self.funil.id, nome="Contato Feito", ordem=2, tipo="normal")
        db.session.add_all([self.etapa1, self.etapa2])
        db.session.flush()

        # Regras de Distribuição Regional
        self.regra_sp = CrmRegraDistribuicao(
            nome="Regra São Paulo (SP)",
            regiao="SP",
            estados="SP",
            ddds="11,12,13,14,15,16,17,18,19",
            consultor_id=self.consultor_sp.id,
            ativo=True,
            ordem=10,
        )
        self.regra_rj = CrmRegraDistribuicao(
            nome="Regra Rio de Janeiro (RJ)",
            regiao="RJ",
            estados="RJ",
            ddds="21,22,24",
            consultor_id=self.consultor_rj.id,
            ativo=True,
            ordem=20,
        )
        db.session.add_all([self.regra_sp, self.regra_rj])

        # Equipamento para testes de preço
        self.equip = Equipment(
            name="Equipamento Teste Sollus",
            description="Descrição técnica original do equipamento.",
            unit_price=1000.0,
            quantity=15,
        )
        db.session.add(self.equip)
        db.session.commit()

        # Helper para login
        with self.client.session_transaction() as sess:
            sess["usuario_id"] = self.consultor_rj.id
            sess["user_id"] = self.consultor_rj.id
            sess["tipo"] = "admin"

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    # ----------------------------------------------------------------------- #
    # TESTES DE ROTEAMENTO REGIONAL (DESTINO DO LEAD)
    # ----------------------------------------------------------------------- #

    def test_extract_ddd_from_phone(self):
        self.assertEqual(extract_ddd_from_phone("+5511999998888"), "11")
        self.assertEqual(extract_ddd_from_phone("5521988887777"), "21")
        self.assertEqual(extract_ddd_from_phone("(19) 98765-4321"), "19")
        self.assertEqual(extract_ddd_from_phone("11987654321"), "11")
        self.assertEqual(extract_ddd_from_phone("4133334444"), "41")

    def test_detect_lead_region(self):
        # Detecção por DDD
        det = detect_lead_region(telefone="(11) 98765-4321")
        self.assertEqual(det["regiao"], "SP")
        self.assertEqual(det["ddd"], "11")

        det_rj = detect_lead_region(telefone="21999998888")
        self.assertEqual(det_rj["regiao"], "RJ")
        self.assertEqual(det_rj["ddd"], "21")

        # Detecção por Estado/UF
        det_uf = detect_lead_region(estado="SP")
        self.assertEqual(det_uf["regiao"], "SP")

        # Detecção por Filial
        det_fil = detect_lead_region(filial="SP")
        self.assertEqual(det_fil["regiao"], "SP")

    def test_find_matching_distribution_rule(self):
        rule_sp = find_matching_distribution_rule(ddd="11")
        self.assertIsNotNone(rule_sp)
        self.assertEqual(rule_sp.consultor_id, self.consultor_sp.id)

        rule_rj = find_matching_distribution_rule(ddd="21")
        self.assertIsNotNone(rule_rj)
        self.assertEqual(rule_rj.consultor_id, self.consultor_rj.id)

        rule_uf = find_matching_distribution_rule(uf="SP")
        self.assertIsNotNone(rule_uf)
        self.assertEqual(rule_uf.consultor_id, self.consultor_sp.id)

    def test_deal_automatic_routing_sp(self):
        # Lead de SP (telefone com DDD 11) deve ir para o consultor SP
        empresa = CrmEmpresa(id="emp_sp", nome="Empresa de São Paulo")
        contato = CrmContato(id="cont_sp", nome="Contato SP", celular="(11) 99887-7665")
        db.session.add_all([empresa, contato])
        db.session.flush()

        deal = create_deal(
            nome="Oportunidade SP Teste",
            valor=15000.0,
            funil_id=self.funil.id,
            empresa_id=empresa.id,
            contato_id=contato.id,
            filial="SP",
        )
        self.assertEqual(deal.user_id, self.consultor_sp.id)
        self.assertEqual(deal.user_name, self.consultor_sp.nome_completo)

    def test_deal_automatic_routing_rj(self):
        # Lead do RJ (telefone com DDD 21) deve ir para o consultor RJ
        empresa = CrmEmpresa(id="emp_rj", nome="Empresa do Rio")
        contato = CrmContato(id="cont_rj", nome="Contato RJ", celular="21999998888")
        db.session.add_all([empresa, contato])
        db.session.flush()

        deal = create_deal(
            nome="Oportunidade RJ Teste",
            valor=25000.0,
            funil_id=self.funil.id,
            empresa_id=empresa.id,
            contato_id=contato.id,
            filial="RJ",
        )
        self.assertEqual(deal.user_id, self.consultor_rj.id)

    def test_deal_unmapped_region_bahia_fallback_to_roleta(self):
        # Lead da Bahia (DDD 71) sem regra específica cadastrada para BA deve cair na Roleta Geral
        contato = CrmContato(id="cont_ba", nome="Contato Bahia", celular="(71) 98888-1122")
        db.session.add(contato)
        db.session.flush()

        deal = create_deal(
            nome="Lead Salvador Bahia",
            valor=5000.0,
            funil_id=self.funil.id,
            contato_id=contato.id,
        )
        # Deve ter sido atribuído a um dos consultores ativos da roleta
        self.assertIsNotNone(deal.user_id)
        self.assertIn(deal.user_id, [self.consultor_sp.id, self.consultor_rj.id, self.consultor_geral.id])

    def test_deal_unmapped_region_with_outros_rule(self):
        # Se o gestor cadastrar regra para 'OUTROS' (Demais Regiões), lead da Bahia vai para esse consultor
        regra_outros = CrmRegraDistribuicao(
            nome="Demais Regiões (Nacional)",
            regiao="OUTROS",
            consultor_id=self.consultor_geral.id,
            ativo=True,
            ordem=99,
        )
        db.session.add(regra_outros)
        db.session.commit()

        contato = CrmContato(id="cont_ba2", nome="Contato BA 2", celular="71999998888")
        db.session.add(contato)
        db.session.flush()

        deal = create_deal(
            nome="Lead Bahia Com Regra Outros",
            valor=8000.0,
            funil_id=self.funil.id,
            contato_id=contato.id,
        )
        self.assertEqual(deal.user_id, self.consultor_geral.id)

    def test_inbound_webhook_lead_destination(self):
        # Inbound webhook com lead de SP
        payload = {
            "nome_negociacao": "Lead Inbound SP Site",
            "valor": 12000.0,
            "filial": "SP",
            "empresa": {"nome": "Tech SP Ltda", "cnpj": "12.345.678/0001-90"},
            "contato": {"nome": "Diretor SP", "email": "diretor@techsp.com.br", "telefone": "(11) 91234-5678"},
        }
        res = self.client.post(
            "/crm/api/webhooks/inbound",
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-API-Token": "token_test_destino_123"},
        )
        self.assertEqual(res.status_code, 201)
        res_data = res.get_json()
        self.assertTrue(res_data["success"])
        self.assertEqual(res_data["consultor_id"], self.consultor_sp.id)

    def test_destino_leads_simular_endpoint(self):
        res = self.client.post(
            "/crm/destino-leads/simular",
            data=json.dumps({"telefone": "(11) 98765-4321", "estado": "SP"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["deteccao"]["regiao"], "SP")
        self.assertIsNotNone(data["consultor"])
        self.assertEqual(data["consultor"]["id"], self.consultor_sp.id)

    def test_destino_leads_crud(self):
        # Criar nova regra escolhendo APENAS o estado e o consultor (DDDs e Nome preenchidos automaticamente)
        res = self.client.post(
            "/crm/destino-leads/salvar",
            data=json.dumps({
                "regiao": "PR",
                "consultor_id": self.consultor_geral.id,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["regra"]["ddds"], "41,42,43,44,45,46")
        self.assertEqual(data["regra"]["estados"], "PR")
        self.assertIn("Paraná", data["regra"]["nome"])
        new_id = data["regra"]["id"]

        # Excluir regra
        res_del = self.client.post(f"/crm/destino-leads/excluir/{new_id}", content_type="application/json")
        self.assertEqual(res_del.status_code, 200)
        self.assertIsNone(CrmRegraDistribuicao.query.get(new_id))

    def test_ricardo_simoes_excluded_from_commercial_consultants(self):
        # A página de destino de leads não deve listar Ricardo Simões (pois agora é Gerente de Projetos)
        res = self.client.get("/crm/destino-leads")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertNotIn("ricardo.simoes", html)
        self.assertIn("Hizael Ferreira", html)

    # ----------------------------------------------------------------------- #
    # TESTES DE TABELA DE PREÇOS E SINCRONIZAÇÃO BIDIRECIONAL
    # ----------------------------------------------------------------------- #

    def test_tabela_precos_page_render(self):
        res = self.client.get("/crm/tabela-precos")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Tabela de Consulta de Preços", res.get_data(as_text=True))
        self.assertIn("Equipamento Teste Sollus", res.get_data(as_text=True))

    def test_update_equipment_price_and_description_service(self):
        eq, mudou = update_equipment_price_and_description(
            equipment_id=self.equip.id,
            new_price=1250.0,
            new_description="Descrição técnica atualizada.",
            user_name="Ricardo Simões",
            origem="crm_tabela_precos",
        )
        db.session.commit()

        self.assertTrue(mudou)
        self.assertEqual(eq.unit_price, 1250.0)
        self.assertEqual(eq.preco_anterior, 1000.0)
        self.assertEqual(eq.preco_alterado_por, "Ricardo Simões")
        self.assertIsNotNone(eq.preco_alterado_em)

        # Histórico registrado
        hist = get_equipment_price_history(self.equip.id)
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["preco_antigo"], 1000.0)
        self.assertEqual(hist[0]["preco_novo"], 1250.0)
        self.assertEqual(hist[0]["alterado_por"], "Ricardo Simões")

    def test_api_atualizar_preco_crm(self):
        res = self.client.post(
            f"/crm/api/equipamentos/{self.equip.id}/atualizar-preco",
            data=json.dumps({
                "preco": 1800.0,
                "descricao": "Descrição pelo CRM",
                "nome": "Equipamento Atualizado pelo CRM",
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["preco_mudou"])
        self.assertEqual(data["novo_preco"], 1800.0)
        self.assertEqual(data["preco_anterior"], 1000.0)

        # Verifica sincronização direta no modelo Equipment
        eq_db = Equipment.query.get(self.equip.id)
        self.assertEqual(eq_db.unit_price, 1800.0)
        self.assertEqual(eq_db.name, "Equipamento Atualizado pelo CRM")
        self.assertEqual(eq_db.preco_anterior, 1000.0)

    def test_estoque_price_update_syncs_to_crm_and_records_history(self):
        # Alteração feita pelo menu Estoque (rota /equipamentos/<id>)
        res = self.client.post(
            f"/equipamentos/{self.equip.id}",
            data=json.dumps({
                "nome": "Equipamento Alterado no Estoque",
                "descricao": "Descrição alterada no Estoque",
                "preco": "2.400,50",
                "quantidade": 20,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)

        # Verifica sincronização no Equipment
        eq_db = Equipment.query.get(self.equip.id)
        self.assertAlmostEqual(eq_db.unit_price, 2400.50, places=2)
        self.assertEqual(eq_db.preco_anterior, 1000.0)
        self.assertEqual(eq_db.quantity, 20)

        # Histórico deve registrar a origem "estoque"
        hist = get_equipment_price_history(self.equip.id)
        self.assertTrue(len(hist) >= 1)
        self.assertEqual(hist[0]["origem"], "estoque")
        self.assertAlmostEqual(hist[0]["preco_novo"], 2400.50, places=2)

    def test_api_historico_precos(self):
        # Altera preço duas vezes
        update_equipment_price_and_description(self.equip.id, new_price=1100.0, user_name="User1")
        db.session.commit()
        update_equipment_price_and_description(self.equip.id, new_price=1350.0, user_name="User2")
        db.session.commit()

        res = self.client.get(f"/crm/api/equipamentos/{self.equip.id}/historico-precos")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["historico"]), 2)
        self.assertEqual(data["historico"][0]["preco_novo"], 1350.0)
        self.assertEqual(data["historico"][1]["preco_novo"], 1100.0)

    # ----------------------------------------------------------------------- #
    # TESTES DE REAJUSTE EM MASSA E UPLOAD DE FOTO PELO CRM
    # ----------------------------------------------------------------------- #

    def test_calculate_adjusted_price_formula_and_rounding(self):
        # Aumento percentual (+10% em 1000 = 1100)
        p1 = calculate_adjusted_price(1000.0, "percentual_aumento", 10.0, "none")
        self.assertEqual(p1, 1100.0)

        # Desconto percentual (-15% em 1000 = 850)
        p2 = calculate_adjusted_price(1000.0, "percentual_desconto", 15.0, "none")
        self.assertEqual(p2, 850.0)

        # Aumento fixo (+250 em 1000 = 1250)
        p3 = calculate_adjusted_price(1000.0, "valor_aumento", 250.0, "none")
        self.assertEqual(p3, 1250.0)

        # Desconto fixo (-300 em 1000 = 700)
        p4 = calculate_adjusted_price(1000.0, "valor_desconto", 300.0, "none")
        self.assertEqual(p4, 700.0)

        # Arredondamento para inteiro
        p5 = calculate_adjusted_price(1000.0, "percentual_aumento", 10.45, "inteiro")
        self.assertEqual(p5, 1105.0)

        # Arredondamento com final .90 (centavos em ,90)
        p6 = calculate_adjusted_price(1000.0, "percentual_aumento", 10.0, "final_90")
        self.assertEqual(p6, 1100.90)

    def test_api_upload_foto_equipamento(self):
        # Cria imagem PNG em memória usando Pillow
        img = Image.new("RGB", (60, 60), color=(37, 99, 235))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        data = {
            "foto": (img_bytes, "equip_teste.png", "image/png"),
        }
        res = self.client.post(
            f"/crm/api/equipamentos/{self.equip.id}/upload-foto",
            data=data,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        self.assertTrue(res_json["success"])
        self.assertIn("image_src", res_json)

        # Verifica persistência no banco
        eq = Equipment.query.get(self.equip.id)
        self.assertIsNotNone(eq.illustration_path)
        self.assertTrue(eq.illustration_path.endswith(".png"))

    def test_api_previa_reajuste(self):
        # Adiciona segundo equipamento
        eq2 = Equipment(name="Equipamento Secundário", unit_price=2000.0, quantity=5)
        db.session.add(eq2)
        db.session.commit()

        # Simula aumento de 15% apenas para o equipamento 1
        res = self.client.post(
            "/crm/api/equipamentos/previa-reajuste",
            data=json.dumps({
                "equipment_ids": [self.equip.id],
                "adjustment_type": "percentual_aumento",
                "value": 15.0,
                "rounding_mode": "none",
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total_itens"], 1)
        self.assertEqual(data["itens"][0]["preco_atual"], 1000.0)
        self.assertEqual(data["itens"][0]["novo_preco"], 1150.0)
        self.assertEqual(data["itens"][0]["diferenca"], 150.0)

        # Simula desconto de 10% para todos os equipamentos (sem passar IDs)
        res_todos = self.client.post(
            "/crm/api/equipamentos/previa-reajuste",
            data=json.dumps({
                "adjustment_type": "percentual_desconto",
                "value": 10.0,
                "rounding_mode": "none",
            }),
            content_type="application/json",
        )
        self.assertEqual(res_todos.status_code, 200)
        data_todos = res_todos.get_json()
        self.assertTrue(data_todos["success"])
        self.assertTrue(data_todos["total_itens"] >= 2)

    def test_api_reajuste_massa_execution(self):
        # Cria outro equipamento
        eq_b = Equipment(name="Equipamento Beta", unit_price=500.0, quantity=10)
        db.session.add(eq_b)
        db.session.commit()

        res = self.client.post(
            "/crm/api/equipamentos/reajuste-massa",
            data=json.dumps({
                "equipment_ids": [self.equip.id, eq_b.id],
                "adjustment_type": "percentual_aumento",
                "value": 20.0,
                "rounding_mode": "inteiro",
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total_atualizados"], 2)

        # Verifica se os equipamentos foram atualizados no banco
        eq1 = Equipment.query.get(self.equip.id)
        self.assertEqual(eq1.unit_price, 1200.0)
        self.assertEqual(eq1.preco_anterior, 1000.0)

        eq2 = Equipment.query.get(eq_b.id)
        self.assertEqual(eq2.unit_price, 600.0)
        self.assertEqual(eq2.preco_anterior, 500.0)

        # Verifica histórico com origem crm_reajuste_massa
        hists1 = CrmEquipamentoHistoricoPreco.query.filter_by(equipment_id=self.equip.id).all()
        self.assertTrue(any(h.origem == "crm_reajuste_massa" for h in hists1))


if __name__ == "__main__":
    unittest.main()
