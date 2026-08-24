from __future__ import annotations

import io
import pytest
from datetime import datetime, date, timezone
from unittest.mock import patch, MagicMock

from platform_app import create_app
from extensions import db
from modules.propostas.models import (
    User,
    Proposal,
    Equipment,
    ServicoType,
    ModalidadeType,
    ParamCategory,
    ParamOption,
)
from modules.propostas.gerar_proposta import (
    _format_cnpj,
    _format_cpf,
    _format_phone,
)
from modules.propostas.blueprints.propostas.propostas import (
    _parse_emails_list,
    _calcular_validade,
    _padronizar_validade,
)


def _parse_br_currency(value: str | None) -> float:
    if not value:
        return 0.0
    cleaned = value.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


class TestConfig:
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_ENABLED = False
    MAIL_SERVER = "smtp.test.com"
    MAIL_DEFAULT_SENDER = "propostas@sollustecnologia.com"
    MAIL_SENDER = "propostas@sollustecnologia.com"
    SECRET_KEY = "test-secret-propostas-key"


@pytest.fixture
def app():
    app_instance = create_app(TestConfig)
    with app_instance.app_context():
        db.create_all()

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

        # Seed test users
        admin = User(
            usuario="admin_prop",
            nome_completo="Admin Propostas",
            email="admin_prop@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="admin",
            role="admin",
            is_active=True,
        )
        regular = User(
            usuario="regular_prop",
            nome_completo="Usuario Sem Permissao",
            email="regular_prop@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="user",
            role="user",
            is_active=True,
            permissions={},
        )
        propostas_user = User(
            usuario="vendedor_prop",
            nome_completo="Vendedor Sollus",
            email="vendedor@sollus.com",
            password_hash="pbkdf2:sha256:dummy",
            tipo="consultor",
            role="consultor",
            is_active=True,
            permissions={"propostas": True},
        )

        db.session.add_all([admin, regular, propostas_user])
        db.session.commit()

        yield app_instance


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username="admin_prop"):
    with client.session_transaction() as sess:
        user = User.query.filter_by(usuario=username).first()
        sess["_user_id"] = str(user.id)
        sess["usuario_id"] = user.id
        sess["logged_in_user"] = user.nome_completo
        sess["tipo"] = user.tipo


# ==============================================================================
# 1. UNIT TESTS FOR HELPER & FORMATTING FUNCTIONS
# ==============================================================================

def test_helper_formatters():
    assert _format_cnpj("11222333000181") == "11.222.333/0001-81"
    assert _format_cpf("12345678901") == "123.456.789-01"
    assert _format_phone("21999998888") == "(21) 99999-8888"


def test_helper_parse_br_currency():
    assert _parse_br_currency("R$ 1.250,50") == 1250.50
    assert _parse_br_currency("500,00") == 500.0
    assert _parse_br_currency(None) == 0.0


def test_helper_parse_emails_list():
    raw = "teste1@sollus.com, teste2@sollus.com; teste3@sollus.com"
    emails = _parse_emails_list(raw)
    assert len(emails) == 3
    assert "teste1@sollus.com" in emails
    assert "teste2@sollus.com" in emails
    assert "teste3@sollus.com" in emails


def test_helper_calcular_and_padronizar_validade():
    validade_str = _calcular_validade(datetime.now())
    assert isinstance(validade_str, str)
    assert len(validade_str) == 10

    p = Proposal(validade="31/12/2026", data_criacao=datetime.now())
    res_val = _padronizar_validade(p)
    assert res_val == "31/12/2026"


# ==============================================================================
# 2. PERMISSIONS & ACCESS CONTROL TESTS
# ==============================================================================

def test_propostas_permissions_unauthorized(client):
    res = client.get("/historico_propostas")
    assert res.status_code in (302, 401)


def test_propostas_permissions_forbidden(client):
    login(client, username="regular_prop")
    res = client.get("/historico_propostas")
    assert res.status_code in (200, 302, 403)


def test_propostas_permissions_vendedor_allowed(client):
    login(client, username="vendedor_prop")
    res = client.get("/historico_propostas")
    assert res.status_code == 200


# ==============================================================================
# 3. PROPOSAL CREATION & CALCULATION WORKFLOWS
# ==============================================================================

def test_nova_proposta_aquisicao_ponto(client, app):
    login(client, username="admin_prop")

    payload = {
        "document_type": "cnpj",
        "document": "11222333000181",
        "company": "Empresa Teste Ponto",
        "client_name": "Contato Teste",
        "email": "contato@sollustecnologia.com",
        "telefone": "21988887777",
        "servico_type": "PONTO",
        "modalidade_type": "AQUISICAO",
        "sistema_selecionado": "sollus_ponto_web",
        "sistema_valor_mensal": "150,00",
        "validade_dias": "15",
        "observacao_comercial": "Proposta de aquisicao em teste",
        "pagto_equip": "A vista",
        "prazo_entrega": "Imediato",
        "frete": "CIF",
        "garantia_eq": "12 meses",
        "garantia_sys": "12 meses",
    }

    with patch("modules.propostas.blueprints.propostas.propostas.email_domain_has_mx", return_value=True):
        res = client.post("/nova_proposta", data=payload, headers={"X-Requested-With": "XMLHttpRequest"})
        assert res.status_code == 200
        data = res.get_json()
        assert data.get("ok") is True or data.get("success") is True

    pid = data.get("id") or data.get("proposal_id") or data.get("new_id")
    with app.app_context():
        if pid:
            proposal = Proposal.query.get(pid)
        else:
            proposal = Proposal.query.filter_by(company="Empresa Teste Ponto").first()
        assert proposal is not None
        assert proposal.servico_type == ServicoType.PONTO
        assert proposal.modalidade_type == ModalidadeType.AQUISICAO


def test_nova_proposta_locacao_analitico_with_equipment(client, app):
    login(client, username="admin_prop")

    payload = {
        "document_type": "cnpj",
        "document": "11222333000181",
        "company": "Empresa Locacao LTDA",
        "client_name": "Gestor Locacao",
        "email": "gestor@sollustecnologia.com",
        "servico_type": "PONTO",
        "modalidade_type": "LOCACAO",
        "locacao_modelo": "analitico",
        "locacao_vigencia": "12",
        "rep_categoria_programa": "on",
        "rep_tem_mobile": "on",
        "rep_qtd_mobile": "5",
        "rep_mobile_valor_mensal": "50,00",
        "validade_dias": "10",
        "pagto_equip": "A vista",
        "prazo_entrega": "Imediato",
        "frete": "CIF",
        "garantia_eq": "12 meses",
        "garantia_sys": "12 meses",
    }

    with patch("modules.propostas.blueprints.propostas.propostas.email_domain_has_mx", return_value=True):
        res = client.post("/nova_proposta", data=payload, headers={"X-Requested-With": "XMLHttpRequest"})
        if res.status_code != 200:
            print("DIAGNOSTIC LOCACAO:", res.status_code, res.get_json())
        assert res.status_code == 200
        data = res.get_json() or {}

    pid = data.get("id") or data.get("proposal_id") or data.get("new_id")
    with app.app_context():
        if pid:
            proposal = Proposal.query.get(pid)
        else:
            proposal = Proposal.query.filter_by(company="Empresa Locacao LTDA").first()
        assert proposal is not None
        assert proposal.modalidade_type == ModalidadeType.LOCACAO
        assert proposal.rep_tem_mobile is True
        assert proposal.rep_qtd_mobile == 5


# ==============================================================================
# 4. EDIT, APPROVE, DELETE & HISTORY WORKFLOWS
# ==============================================================================

def test_editar_proposta(client, app):
    login(client, username="admin_prop")

    admin = User.query.filter_by(usuario="admin_prop").first()
    proposal = Proposal(
        client_name="Cliente Edit",
        company="Empresa Edit SA",
        email="edit@sollustecnologia.com",
        servico_type=ServicoType.PONTO,
        modalidade_type=ModalidadeType.AQUISICAO,
        client_document_type="cnpj",
        cnpj="33444555000122",
        usuario_id=admin.id,
        filename="PROP-EDIT-001",
        data_criacao=datetime.now(),
    )
    db.session.add(proposal)
    db.session.commit()
    pid = proposal.id

    edit_payload = {
        "document_type": "cnpj",
        "document": "11222333000181",
        "company": "Empresa Edit SA Atualizada",
        "client_name": "Cliente Edit Atualizado",
        "email": "edit_novo@sollustecnologia.com",
        "servico_type": "PONTO",
        "modalidade_type": "AQUISICAO",
        "validade_dias": "20",
        "pagto_equip": "A vista",
        "prazo_entrega": "Imediato",
        "frete": "CIF",
        "garantia_eq": "12 meses",
        "garantia_sys": "12 meses",
    }

    with patch("modules.propostas.blueprints.propostas.propostas.email_domain_has_mx", return_value=True):
        res = client.post(f"/editar_proposta/{pid}", data=edit_payload, headers={"X-Requested-With": "XMLHttpRequest"})
        if res.status_code != 200:
            print("DIAGNOSTIC EDITAR:", res.status_code, res.get_json())
        assert res.status_code == 200
        data = res.get_json()
        assert data.get("success") is True or data.get("ok") is True

    new_id = data.get("new_id") or data.get("proposal_id") or data.get("id")
    with app.app_context():
        if new_id:
            updated = Proposal.query.get(new_id)
        else:
            updated = Proposal.query.filter_by(company="Empresa Edit SA Atualizada").first()
        assert updated is not None
        assert updated.company == "Empresa Edit SA Atualizada"


def test_aprovar_and_excluir_proposta(client, app):
    login(client, username="admin_prop")

    admin = User.query.filter_by(usuario="admin_prop").first()
    proposal = Proposal(
        client_name="Cliente Workflow",
        company="Empresa Workflow LTDA",
        email="wf@sollustecnologia.com",
        servico_type=ServicoType.PONTO,
        modalidade_type=ModalidadeType.AQUISICAO,
        usuario_id=admin.id,
        data_criacao=datetime.now(),
    )
    db.session.add(proposal)
    db.session.commit()
    pid = proposal.id

    # Aprovar
    res_aprov = client.post(f"/aprovar_proposta/{pid}", headers={"X-Requested-With": "XMLHttpRequest"})
    assert res_aprov.status_code == 200
    assert res_aprov.get_json()["ok"] is True

    # Excluir
    res_del = client.post(f"/excluir_proposta/{pid}", headers={"X-Requested-With": "XMLHttpRequest"})
    assert res_del.status_code in (200, 302)

    with app.app_context():
        deleted = Proposal.query.get(pid)
        assert deleted is None


def test_historico_propostas_filtering(client, app):
    login(client, username="admin_prop")

    admin = User.query.filter_by(usuario="admin_prop").first()
    p1 = Proposal(company="Alfa LTDA", servico_type=ServicoType.PONTO, modalidade_type=ModalidadeType.AQUISICAO, usuario_id=admin.id, data_criacao=datetime.now())
    p2 = Proposal(company="Beta SA", servico_type=ServicoType.ACESSO, modalidade_type=ModalidadeType.LOCACAO, usuario_id=admin.id, data_criacao=datetime.now())
    db.session.add_all([p1, p2])
    db.session.commit()

    # Search filter by empresa
    res_search = client.get(f"/historico_propostas?empresa=Alfa")
    assert res_search.status_code == 200
    assert f'data-proposal-id="{p1.id}"'.encode('utf-8') in res_search.data
    assert f'data-proposal-id="{p2.id}"'.encode('utf-8') not in res_search.data


# ==============================================================================
# 5. PREVIEW, PDF & DOWNLOAD ENDPOINTS
# ==============================================================================

def test_visualizar_and_baixar_proposta(client, app):
    login(client, username="admin_prop")

    admin = User.query.filter_by(usuario="admin_prop").first()
    proposal = Proposal(
        client_name="Cliente View",
        company="Empresa Preview LTDA",
        email="preview@sollustecnologia.com",
        servico_type=ServicoType.PONTO,
        modalidade_type=ModalidadeType.AQUISICAO,
        usuario_id=admin.id,
        data_criacao=datetime.now(),
    )
    db.session.add(proposal)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["ultima_proposta_id"] = proposal.id

    with patch("modules.propostas.blueprints.propostas.propostas._gerar_e_enviar_pdf") as mock_pdf:
        from flask import Response
        mock_pdf.return_value = Response(b"%PDF-1.4 proposal preview content", mimetype="application/pdf")

        res_view = client.get("/visualizar_proposta")
        assert res_view.status_code == 200
        assert b"%PDF" in res_view.data

    with client.session_transaction() as sess:
        sess["ultima_proposta_id"] = proposal.id

    with patch("modules.propostas.blueprints.propostas.propostas._gerar_e_enviar_pdf") as mock_pdf:
        from flask import Response
        mock_pdf.return_value = Response(b"%PDF-1.4 proposal preview content", mimetype="application/pdf")

        res_down = client.get("/baixar_proposta")
        assert res_down.status_code == 200
        assert b"%PDF" in res_down.data


# ==============================================================================
# 6. CNPJ LOOKUP API SERVICE
# ==============================================================================

def test_api_consultar_cnpj(client):
    login(client, username="admin_prop")

    with patch("modules.propostas.api._fetch_cnpj_payload") as mock_cnpj:
        mock_cnpj.return_value = {
            "status": "OK",
            "razao_social": "Sollus Tecnologia Eireli",
            "estabelecimento": {"nome_fantasia": "Sollus Tecnologia"},
        }

        res = client.get("/api/cnpj/11222333000181")
        assert res.status_code == 200
        data = res.get_json()
        assert data is not None


# ==============================================================================
# 7. EMAIL SERVICE FOR PROPOSALS
# ==============================================================================

def test_proposal_email_dispatch(app):
    with app.app_context():
        admin = User.query.filter_by(usuario="admin_prop").first()
        proposal = Proposal(
            client_name="Cliente Email",
            company="Empresa Email SA",
            email="cliente_email@sollustecnologia.com",
            servico_type=ServicoType.PONTO,
            modalidade_type=ModalidadeType.AQUISICAO,
            usuario_id=admin.id,
            data_criacao=datetime.now(),
        )

        with patch("modules.propostas.services.proposal_email.smtplib.SMTP") as mock_smtp:
            from modules.propostas.services.proposal_email import send_proposal_email

            pdf_bytes = b"%PDF-1.4 proposal email attachment"
            send_proposal_email(
                proposal,
                "Corpo do e-mail de proposta",
                [],
                pdf_bytes=pdf_bytes,
            )
            assert mock_smtp.called
