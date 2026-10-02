"""Testes de estresse adversariais para o Milestone M2 do Sollus CRM.

Abrange testes empíricos rigorosos sobre:
1. Sanitização de telefones WhatsApp (formatos nacionais, internacionais, zeros, símbolos, tipos inválidos, DDD 55)
2. Construção canônica de links WhatsApp e codificação de URL (emojis, quebras de linha, caracteres especiais &, ?, =, %)
3. Motor de templates dinâmicos com entidades nulas ou incompletas (contato, empresa, consultor, proposta)
4. Simulação de horários da saudação ({saudacao}) para limites de horário
5. Endpoints de API de templates (/crm/api/templates-whatsapp e /crm/api/templates-whatsapp/render) sob estresse e ACL
"""
from __future__ import annotations

import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
import urllib.parse
from sqlalchemy.pool import StaticPool

from extensions import db
from platform_app import create_app
from modules.propostas.models import User, Department, Proposal
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmTemplateMensagem,
)
from modules.crm.services.crm_service import (
    sanitize_whatsapp_phone,
    build_whatsapp_link,
    generate_whatsapp_url,
    render_whatsapp_template,
)


class TestConfigAdversarialM2:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-adversarial-m2"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }


class TestCrmAdversarialM2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(TestConfigAdversarialM2)

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        # Departamento Comercial
        self.dept_comercial = Department(name="COMERCIAL", slug="comercial")
        db.session.add(self.dept_comercial)
        db.session.commit()

        # Usuário de teste
        self.user = User(
            usuario="consultor_adv",
            nome_completo="Consultor Adversarial",
            email="adv@sollus.com",
            password_hash="hash_adv",
            tipo="consultor",
            role="consultor",
            department_id=self.dept_comercial.id,
            is_active=True,
            permissions={"crm": True},
        )
        db.session.add(self.user)
        db.session.commit()

        # Funil e etapa
        self.funil = CrmFunil(id="funil_adv_m2", nome="Funil M2", slug="funil_m2", tipo="ponto", ativo=True)
        db.session.add(self.funil)
        db.session.flush()

        self.etapa = CrmEtapa(id="etapa_adv_m2", funil_id=self.funil.id, nome="Etapa Inicial", ordem=1, tipo="normal")
        db.session.add(self.etapa)
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
    # 1. TESTES DE SANITIZAÇÃO DE TELEFONE (sanitize_whatsapp_phone)
    # =========================================================================

    def test_phone_sanitization_diverse_formats_required_by_spec(self):
        """Testa todos os formatos exigidos explicitamente pelo objetivo do usuário."""
        # "(11) 98765-4321" -> "5511987654321"
        self.assertEqual(sanitize_whatsapp_phone("(11) 98765-4321"), "5511987654321")
        # "011987654321" -> "5511987654321"
        self.assertEqual(sanitize_whatsapp_phone("011987654321"), "5511987654321")
        # "+55 11 98765-4321" -> "5511987654321"
        self.assertEqual(sanitize_whatsapp_phone("+55 11 98765-4321"), "5511987654321")
        # "5511987654321" -> "5511987654321"
        self.assertEqual(sanitize_whatsapp_phone("5511987654321"), "5511987654321")
        # "1133334444" (fixo 10 dígitos) -> "551133334444"
        self.assertEqual(sanitize_whatsapp_phone("1133334444"), "551133334444")
        # "01133334444" (fixo com zero) -> "551133334444"
        self.assertEqual(sanitize_whatsapp_phone("01133334444"), "551133334444")
        # invalid "123" -> None
        self.assertIsNone(sanitize_whatsapp_phone("123"))
        # "" -> None
        self.assertIsNone(sanitize_whatsapp_phone(""))
        # None -> None
        self.assertIsNone(sanitize_whatsapp_phone(None))
        # letters -> None
        self.assertIsNone(sanitize_whatsapp_phone("abcdef"))
        self.assertIsNone(sanitize_whatsapp_phone("telefone sem numero"))
        # symbols -> None
        self.assertIsNone(sanitize_whatsapp_phone("!@#$%^&*()_+"))
        self.assertIsNone(sanitize_whatsapp_phone("--- () /."))

    def test_phone_sanitization_edge_cases_and_adversarial_inputs(self):
        """Testa casos extremos: tipos inválidos, strings de tamanho limítrofe, zeros e DDD 55."""
        # Tipos não string
        for invalid_type in [11987654321, 5511987654321.0, True, False, [], {}, object()]:
            self.assertIsNone(sanitize_whatsapp_phone(invalid_type))  # type: ignore

        # Espaços e quebras de linha
        self.assertIsNone(sanitize_whatsapp_phone("   "))
        self.assertIsNone(sanitize_whatsapp_phone("\t\r\n"))

        # Zeros múltiplos
        self.assertEqual(sanitize_whatsapp_phone("00011987654321"), "5511987654321")
        self.assertEqual(sanitize_whatsapp_phone("005511987654321"), "5511987654321")
        self.assertIsNone(sanitize_whatsapp_phone("0000000000"))
        self.assertIsNone(sanitize_whatsapp_phone("00000000000"))

        # Números curtos demais (8 ou 9 dígitos sem DDD)
        self.assertIsNone(sanitize_whatsapp_phone("98765-4321"))  # 8 dígitos
        self.assertIsNone(sanitize_whatsapp_phone("987654321"))   # 9 dígitos
        self.assertIsNone(sanitize_whatsapp_phone("3333-4444"))   # 8 dígitos

        # Números longos demais (14 ou mais dígitos)
        self.assertIsNone(sanitize_whatsapp_phone("551198765432100"))  # 15 dígitos
        self.assertIsNone(sanitize_whatsapp_phone("+55 11 98765-4321 ramal 123"))  # letras + dígitos extras

        # Fixo com código do país (12 dígitos começando com 55)
        self.assertEqual(sanitize_whatsapp_phone("+55 (11) 3333-4444"), "551133334444")
        self.assertEqual(sanitize_whatsapp_phone("551133334444"), "551133334444")

        # DDD 55 (Santa Maria / RS) - números de 10 e 11 dígitos que já iniciam com 55
        self.assertEqual(sanitize_whatsapp_phone("(55) 99876-5432"), "5555998765432")
        self.assertEqual(sanitize_whatsapp_phone("55998765432"), "5555998765432")
        self.assertEqual(sanitize_whatsapp_phone("+55 (55) 99876-5432"), "5555998765432")
        self.assertEqual(sanitize_whatsapp_phone("(55) 3220-1234"), "555532201234")
        self.assertEqual(sanitize_whatsapp_phone("+55 (55) 3220-1234"), "555532201234")

    # =========================================================================
    # 2. TESTES DE CONSTRUÇÃO DE LINK E URL ENCODING (build_whatsapp_link)
    # =========================================================================

    def test_whatsapp_link_url_encoding_emojis(self):
        """Testa codificação de emojis, unicode multi-byte e sequências ZWJ."""
        phone = "(11) 98765-4321"
        emoji_msg = "Olá! 🚀 Parabéns pela contratação! 🎉 Contato: 🤝 🇧🇷"
        url = build_whatsapp_link(phone, emoji_msg)

        self.assertTrue(url.startswith("https://api.whatsapp.com/send?phone=5511987654321&text="))
        # Verifica se não há caracteres unicode brutos não codificados na URL
        query = url.split("?", 1)[1]
        params = urllib.parse.parse_qs(query)
        self.assertIn("phone", params)
        self.assertIn("text", params)
        self.assertEqual(params["phone"][0], "5511987654321")
        # Decodificação deve preservar exatamente a string original com emojis
        self.assertEqual(params["text"][0], emoji_msg)

    def test_whatsapp_link_url_encoding_linebreaks(self):
        """Testa codificação correta de quebras de linha Unix (\n) e Windows (\r\n)."""
        phone = "11987654321"
        msg_unix = "Item 1:\n- Proposta A\n- Proposta B\nObrigado!"
        url_unix = build_whatsapp_link(phone, msg_unix)
        self.assertIn("%0A", url_unix)
        query = url_unix.split("?", 1)[1]
        self.assertEqual(urllib.parse.parse_qs(query)["text"][0], msg_unix)

        msg_win = "Linha 1\r\nLinha 2\r\nLinha 3"
        url_win = build_whatsapp_link(phone, msg_win)
        self.assertIn("%0D%0A", url_win)
        query_win = url_win.split("?", 1)[1]
        self.assertEqual(urllib.parse.parse_qs(query_win)["text"][0], msg_win)

    def test_whatsapp_link_url_encoding_special_delimiters(self):
        """Testa caracteres críticos de URL: '&', '?', '=', '%' para evitar colisão de query params."""
        phone = "+55 (11) 98765-4321"
        tricky_msg = "Promoção: 100% de bônus & desconto de R$ 50? Sim=com certeza! Link: key=val&foo=bar"
        url = build_whatsapp_link(phone, tricky_msg)

        # O caractere '&' DEVE estar codificado como %26 para não criar um novo parâmetro HTTP
        self.assertIn("%26", url)
        self.assertIn("%3F", url)
        self.assertIn("%3D", url)
        self.assertIn("%25", url)

        # Ao fazer o parse da query string, DEVE haver APENAS 'phone' e 'text'
        query = url.split("?", 1)[1]
        params = urllib.parse.parse_qs(query)
        self.assertEqual(set(params.keys()), {"phone", "text"})
        self.assertEqual(params["text"][0], tricky_msg)

    def test_whatsapp_link_empty_and_null_texts(self):
        """Testa mensagens vazias, nulas e compostas apenas por espaços."""
        phone = "11987654321"
        self.assertEqual(build_whatsapp_link(phone, ""), "https://api.whatsapp.com/send?phone=5511987654321&text=")
        self.assertEqual(build_whatsapp_link(phone, None), "https://api.whatsapp.com/send?phone=5511987654321&text=")  # type: ignore
        self.assertEqual(build_whatsapp_link(phone, "   "), "https://api.whatsapp.com/send?phone=5511987654321&text=%20%20%20")

    def test_whatsapp_link_alias_equivalence(self):
        """Verifica que o alias generate_whatsapp_url é estritamente idêntico a build_whatsapp_link."""
        phone = "(21) 98765-4321"
        msg = "Mensagem teste"
        self.assertEqual(build_whatsapp_link(phone, msg), generate_whatsapp_url(phone, msg))

    # =========================================================================
    # 3. TESTES DO MOTOR DE TEMPLATES DINÂMICOS (render_whatsapp_template)
    # =========================================================================

    def test_template_all_entities_null_complete_fallback(self):
        """Garante que nenhum placeholder residual permaneça quando TODOS os objetos forem None."""
        template = "{saudacao}, {nome_contato}! Aqui é {consultor} da {empresa}. Proposta: {link_proposta}."
        rendered = render_whatsapp_template(
            template,
            deal=None,
            contato=None,
            empresa=None,
            consultor=None,
            proposal=None
        )

        # Verificações de fallbacks esperados
        self.assertIn("Cliente", rendered)
        self.assertIn("sua empresa", rendered)
        self.assertIn("Consultor Comercial", rendered)
        self.assertTrue(rendered.startswith("Bom dia") or rendered.startswith("Boa tarde") or rendered.startswith("Boa noite"))
        # Nenhum marcador dinâmico original deve sobrar
        self.assertNotIn("{nome_contato}", rendered)
        self.assertNotIn("{empresa}", rendered)
        self.assertNotIn("{consultor}", rendered)
        self.assertNotIn("{link_proposta}", rendered)
        self.assertNotIn("{saudacao}", rendered)

    def test_template_partial_entities_with_empty_or_whitespace_fields(self):
        """Testa entidades que existem mas possuem nomes vazios, nulos ou apenas espaços."""
        empresa_vazia = CrmEmpresa(id="emp_vazia", nome="   ")
        contato_vazio = CrmContato(id="cont_vazio", empresa_id=empresa_vazia.id, nome="")
        deal_sem_nomes = CrmNegociacao(
            id="deal_sem_nomes",
            nome="Deal Vazio",
            funil_id=self.funil.id,
            etapa_id=self.etapa.id,
            empresa_id=empresa_vazia.id,
            contato_id=contato_vazio.id,
            user_name="   ",
            user_id=None,
            proposta_id=None
        )
        db.session.add_all([empresa_vazia, contato_vazio, deal_sem_nomes])
        db.session.commit()

        template = "{nome_contato} - {empresa} - {consultor} - {link_proposta}"
        rendered = render_whatsapp_template(template, deal_id=deal_sem_nomes.id)

        self.assertIn("Cliente", rendered)
        self.assertIn("sua empresa", rendered)
        self.assertIn("Consultor Comercial", rendered)
        self.assertNotIn("{link_proposta}", rendered)

    def test_template_proposal_link_variations(self):
        """Testa as diversas origens do link da proposta (deal.proposta_id, proposal object, kwargs)."""
        template = "Veja: {link_proposta}"

        # 1. Proposta via deal.proposta_id
        deal = CrmNegociacao(
            id="deal_prop",
            nome="Deal Prop",
            funil_id=self.funil.id,
            etapa_id=self.etapa.id,
            proposta_id=1234
        )
        db.session.add(deal)
        db.session.commit()
        res1 = render_whatsapp_template(template, deal=deal)
        self.assertIn("/propostas/visualizar/1234", res1)

        # 2. Proposta via objeto proposal mock
        class FakeProposal:
            id = 5678
        res2 = render_whatsapp_template(template, proposal=FakeProposal())
        self.assertIn("/propostas/visualizar/5678", res2)

        # 3. Proposta via kwargs['proposta_id']
        res3 = render_whatsapp_template(template, proposta_id=9999)
        self.assertIn("/propostas/visualizar/9999", res3)

        # 4. Sem proposta alguma -> string vazia
        res4 = render_whatsapp_template(template)
        self.assertEqual(res4, "Veja: ")

    def test_template_consultor_variations(self):
        """Testa resolução de consultor via string, objetos com múltiplos atributos ou User em banco."""
        template = "Consultor: {consultor}"

        # 1. String direta
        self.assertEqual(render_whatsapp_template(template, consultor="Mariana Silva"), "Consultor: Mariana Silva")

        # 2. Objeto com nome_completo
        class UserA:
            nome_completo = "Mariana Completo"
        self.assertEqual(render_whatsapp_template(template, consultor=UserA()), "Consultor: Mariana Completo")

        # 3. Objeto com nome apenas
        class UserB:
            nome = "Mariana Nome"
        self.assertEqual(render_whatsapp_template(template, consultor=UserB()), "Consultor: Mariana Nome")

        # 4. Objeto com usuario apenas
        class UserC:
            usuario = "mariana_user"
        self.assertEqual(render_whatsapp_template(template, consultor=UserC()), "Consultor: mariana_user")

        # 5. Deal com user_id vinculado a User no banco
        deal = CrmNegociacao(
            id="deal_user_rel",
            nome="Deal User Rel",
            funil_id=self.funil.id,
            etapa_id=self.etapa.id,
            user_id=self.user.id
        )
        db.session.add(deal)
        db.session.commit()
        self.assertEqual(render_whatsapp_template(template, deal=deal), f"Consultor: {self.user.nome_completo}")

    def test_template_time_of_day_greetings(self):
        """Simula os horários do dia no fuso horário do Brasil (UTC-3) para testar limites de saudação."""
        template = "{saudacao}"

        # Manhã: 05:00 às 11:59 (Brasília) -> UTC 08:00 às 14:59
        with patch("modules.crm.services.crm_service.datetime") as mock_dt:
            # 05:00 Brasília = 08:00 UTC
            mock_dt.utcnow.return_value = datetime(2026, 9, 21, 8, 0, 0)
            self.assertEqual(render_whatsapp_template(template), "Bom dia")

            # 11:59 Brasília = 14:59 UTC
            mock_dt.utcnow.return_value = datetime(2026, 9, 21, 14, 59, 0)
            self.assertEqual(render_whatsapp_template(template), "Bom dia")

        # Tarde: 12:00 às 17:59 (Brasília) -> UTC 15:00 às 20:59
        with patch("modules.crm.services.crm_service.datetime") as mock_dt:
            # 12:00 Brasília = 15:00 UTC
            mock_dt.utcnow.return_value = datetime(2026, 9, 21, 15, 0, 0)
            self.assertEqual(render_whatsapp_template(template), "Boa tarde")

            # 17:59 Brasília = 20:59 UTC
            mock_dt.utcnow.return_value = datetime(2026, 9, 21, 20, 59, 0)
            self.assertEqual(render_whatsapp_template(template), "Boa tarde")

        # Noite: 18:00 às 04:59 (Brasília) -> UTC 21:00 às 07:59
        with patch("modules.crm.services.crm_service.datetime") as mock_dt:
            # 18:00 Brasília = 21:00 UTC
            mock_dt.utcnow.return_value = datetime(2026, 9, 21, 21, 0, 0)
            self.assertEqual(render_whatsapp_template(template), "Boa noite")

            # 23:00 Brasília = 02:00 UTC (+1 dia)
            mock_dt.utcnow.return_value = datetime(2026, 9, 22, 2, 0, 0)
            self.assertEqual(render_whatsapp_template(template), "Boa noite")

            # 04:30 Brasília = 07:30 UTC
            mock_dt.utcnow.return_value = datetime(2026, 9, 21, 7, 30, 0)
            self.assertEqual(render_whatsapp_template(template), "Boa noite")

    def test_template_robustness_with_non_template_braces(self):
        """Garante que chaves não reconhecidas (ex: JSON, regex, expressões) não causem crash."""
        template = "Olá {nome_contato}! Veja config: {\"status\": 200} e regex: \\d{2,4}."
        rendered = render_whatsapp_template(template, contato=None)
        self.assertEqual(rendered, "Olá Cliente! Veja config: {\"status\": 200} e regex: \\d{2,4}.")

    def test_template_robustness_with_empty_or_none_template(self):
        """Garante que templates None ou vazios retornem string vazia com segurança."""
        self.assertEqual(render_whatsapp_template(""), "")
        self.assertEqual(render_whatsapp_template(None), "")  # type: ignore

    # =========================================================================
    # 4. TESTES DE API REST E SEGURANÇA (ACL GATEKEEPER)
    # =========================================================================

    def test_api_render_template_whatsapp_unauthenticated_rejected(self):
        """Garante que usuário anônimo seja redirecionado ou receba 401/403 (ACL)."""
        res = self.client.post("/crm/api/templates-whatsapp/render", json={"template_text": "Olá"})
        # login_required redireciona para login (302) ou rejeita (401)
        self.assertIn(res.status_code, (302, 401))

    def test_api_render_template_whatsapp_authenticated_stress(self):
        """Testa o endpoint de renderização com diferentes cargas de telefone e emojis."""
        self._login(self.user)

        # 1. Telefone formatado com emojis e quebras de linha
        payload = {
            "template_text": "Olá {nome_contato}!\n{saudacao}! 🚀 Proposta: {link_proposta}",
            "telefone": "(11) 99999-8888",
        }
        res = self.client.post("/crm/api/templates-whatsapp/render", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["phone_sanitized"], "5511999998888")
        self.assertIn("5511999998888", data["whatsapp_url"])
        self.assertIn("Cliente", data["rendered_text"])

        # 2. Telefone inválido "123"
        payload_invalid = {
            "template_text": "Olá {nome_contato}",
            "telefone": "123",
        }
        res_inv = self.client.post("/crm/api/templates-whatsapp/render", json=payload_invalid)
        self.assertEqual(res_inv.status_code, 200)
        data_inv = res_inv.get_json()
        self.assertTrue(data_inv["success"])
        self.assertIsNone(data_inv["phone_sanitized"])

        # 3. Telefone vazio ""
        payload_empty = {
            "template_text": "Olá {nome_contato}",
            "telefone": "",
        }
        res_emp = self.client.post("/crm/api/templates-whatsapp/render", json=payload_empty)
        self.assertEqual(res_emp.status_code, 200)
        data_emp = res_emp.get_json()
        self.assertTrue(data_emp["success"])
        self.assertEqual(data_emp["whatsapp_url"], "")
        self.assertIsNone(data_emp["phone_sanitized"])

    def test_api_list_templates_whatsapp(self):
        """Garante retorno de templates padrão ou cadastrados em banco."""
        self._login(self.user)
        res = self.client.get("/crm/api/templates-whatsapp")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(len(data["templates"]), 3)
        # Verifica a estrutura de cada template
        for tpl in data["templates"]:
            self.assertIn("id", tpl)
            self.assertIn("nome", tpl)
            self.assertIn("conteudo", tpl)


if __name__ == "__main__":
    unittest.main()
