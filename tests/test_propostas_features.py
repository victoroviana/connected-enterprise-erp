from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, url_for
from werkzeug.routing import BuildError

from extensions import db, login_manager
from modules.propostas.blueprints.propostas import propostas_bp
from modules.propostas.gerar_proposta import _build_html_context
from modules.propostas.models import ModalidadeType, Proposal, ServicoType, User


def _parse_br_currency(value: str | None) -> float:
    if not value:
        return 0.0
    cleaned = (
        value.replace("R$", "")
        .replace(" ", "")
        .replace(".", "")
        .replace(",", ".")
    )
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _make_equipment(
    eq_id,
    name,
    description,
    unit_price,
    *,
    quantity=1,
    discount_percent=0.0,
    is_acquisition=False,
):
    return SimpleNamespace(
        id=eq_id,
        name=name,
        description=description,
        unit_price=unit_price,
        quantity=quantity,
        discount_percent=discount_percent,
        illustration_path=None,
        is_acquisition=is_acquisition,
    )


def _make_proposal(**overrides):
    base = dict(
        servico_type=ServicoType.PONTO,
        modalidade_type=ModalidadeType.AQUISICAO,
        locacao_modelo="sintetico",
        locacao_vigencia=None,
        locacao_qtd_cnpjs=None,
        locacao_qtd_equipamentos=None,
        rep_categoria_programa=False,
        rep_tem_mobile=False,
        rep_qtd_mobile=None,
        rep_mobile_valor_mensal=None,
        sistema_quantidade=None,
        observacao_comercial=None,
        ambiente_incluir=False,
        ambiente_fotos=None,
        client_document_type="cnpj",
        cnpj="11222333000181",
        company="Empresa Teste",
        client_name="Cliente",
        email="cliente@example.com",
        telefone="",
        data_criacao=datetime(2025, 1, 1),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_context_locacao_analitico_keeps_items_separate():
    proposta = _make_proposal(
        modalidade_type=ModalidadeType.LOCACAO,
        locacao_modelo="analitico",
    )
    eq1 = _make_equipment(1, "Equip 1", "Desc 1", 100)
    eq2 = _make_equipment(2, "Equip 2", "Desc 2", 200, quantity=2)

    ctx = _build_html_context(proposta, [eq1, eq2])

    assert ctx["locacao_analitico"] is True
    assert len(ctx["equipamentos"]) == 2
    # descriptions are augmented with service terms by the context builder
    descriptions = [item["description"] for item in ctx["equipamentos"]]
    assert descriptions[0].startswith("Desc 1")
    assert descriptions[1].startswith("Desc 2")
    assert all(not item.get("is_bundle") for item in ctx["equipamentos"])


def test_context_rep_mobile_adds_item_and_quantity():
    proposta = _make_proposal(
        rep_categoria_programa=True,
        rep_tem_mobile=True,
        rep_qtd_mobile=3,
        rep_mobile_valor_mensal=300.0,
    )

    ctx = _build_html_context(proposta, [])

    assert ctx["rep_tem_mobile"] is True
    assert ctx["rep_qtd_mobile"] == 3
    mobile_rows = [
        item for item in ctx["equipamentos"]
        if "mobile" in (item.get("description") or "").lower()
    ]
    assert len(mobile_rows) == 1
    mobile = mobile_rows[0]
    assert mobile["quantity"] == 3
    # total_price may include 'mensais' suffix for recurring items
    total_str = mobile["total_price"].replace(" mensais", "").strip()
    assert _parse_br_currency(total_str) == pytest.approx(300.0)


def test_context_acquisicao_separates_system_and_equipment_totals():
    proposta = _make_proposal(modalidade_type=ModalidadeType.AQUISICAO)
    system = _make_equipment("system:main", "Sistema", "Sistema Ponto", 100.0)
    equipamento = _make_equipment(10, "Relogio", "Relogio", 200.0, quantity=2)

    ctx = _build_html_context(proposta, [system, equipamento])

    assert _parse_br_currency(ctx["investimento_mensal"]) == pytest.approx(100.0)
    assert _parse_br_currency(ctx["investimento_unico"]) == pytest.approx(400.0)
    # investimento_total reflects equipment costs only (system fee is separate/monthly)
    assert _parse_br_currency(ctx["investimento_total"]) == pytest.approx(400.0)


def test_context_locacao_with_acquisition_tracks_totals():
    proposta = _make_proposal(
        modalidade_type=ModalidadeType.LOCACAO,
        locacao_modelo="analitico",
    )
    equipamento_acq = _make_equipment(
        1,
        "Equip A",
        "Equip A",
        500.0,
        is_acquisition=True,
    )
    equipamento_mensal = _make_equipment(2, "Equip B", "Equip B", 100.0, quantity=2)

    ctx = _build_html_context(proposta, [equipamento_acq, equipamento_mensal])

    assert ctx["locacao_has_acquisition"] is True
    assert _parse_br_currency(ctx["investimento_unico"]) == pytest.approx(500.0)
    assert _parse_br_currency(ctx["investimento_mensal"]) == pytest.approx(200.0)


def test_context_observacao_comercial_in_condicoes():
    proposta = _make_proposal(observacao_comercial="Observacao teste")
    ctx = _build_html_context(proposta, [])
    assert ("Observacoes complementares", "Observacao teste") in ctx["condicoes"]


def test_context_ambiente_photos_optional(tmp_path):
    photo = tmp_path / "ambiente.jpg"
    photo.write_bytes(b"fake-image")

    proposta_hidden = _make_proposal(
        ambiente_incluir=False,
        ambiente_fotos=[str(photo)],
    )
    ctx_hidden = _build_html_context(proposta_hidden, [])
    assert ctx_hidden["ambiente_fotos"] == []

    proposta_visible = _make_proposal(
        ambiente_incluir=True,
        ambiente_fotos=[str(photo)],
    )
    ctx_visible = _build_html_context(proposta_visible, [])
    assert len(ctx_visible["ambiente_fotos"]) == 1
    # ambiente_fotos now yields dicts with 'url' and 'title' keys
    first = ctx_visible["ambiente_fotos"][0]
    assert isinstance(first, dict)
    assert first["url"].startswith("file:///")


@pytest.fixture()
def app(tmp_path):
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    base_dir = Path(__file__).resolve().parents[1]
    template_dir = base_dir / "templates"

    app = Flask(
        __name__,
        instance_path=str(instance_dir),
        template_folder=str(template_dir),
    )
    app.jinja_env.globals["csrf_token"] = lambda: ""

    def _safe_url_for(endpoint, **values):
        try:
            return url_for(endpoint, **values)
        except BuildError:
            return "#"

    app.jinja_env.globals["url_for"] = _safe_url_for
    app.config.update(
        SECRET_KEY="testing-key",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'test.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )

    db.init_app(app)
    login_manager.init_app(app)

    # Register the 'local' filter used in templates — mirrors what create_app() does
    from utils.timezone import get_local_timezone

    def _to_local(dt, fmt=None):
        if dt is None:
            return ""
        if isinstance(dt, str):
            try:
                from datetime import datetime as _dt
                dt = _dt.fromisoformat(dt.replace("Z", "+00:00"))
            except Exception:
                return dt
        if not hasattr(dt, "astimezone"):
            return dt
        from datetime import timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local_dt = dt.astimezone(get_local_timezone())
        if fmt:
            return local_dt.strftime(fmt)
        return local_dt

    app.jinja_env.filters["local"] = _to_local

    @login_manager.user_loader
    def _load_user(user_id):
        with app.app_context():
            return User.query.get(int(user_id))

    app.register_blueprint(propostas_bp)

    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.drop_all()


def _seed_user(app, *, username="tester", tipo="consultor"):
    with app.app_context():
        user = User(
            usuario=username,
            nome_completo="Tester",
            email=f"{username}@example.com",
            password_hash="hash",
            tipo=tipo,
            role=tipo,
        )
        db.session.add(user)
        db.session.commit()
        return user.id


def _seed_proposal(app, user_id, *, company="Empresa A", cnpj="11222333000181"):
    with app.app_context():
        proposal = Proposal(
            company=company,
            cnpj=cnpj,
            client_name="Cliente",
            email="cliente@example.com",
            telefone="",
            usuario_id=user_id,
            servico_type=ServicoType.PONTO,
            modalidade_type=ModalidadeType.AQUISICAO,
            filename="PROP-001",
        )
        db.session.add(proposal)
        db.session.commit()
        return proposal.id


def test_editar_proposta_creates_new_version(app):
    user_id = _seed_user(app)
    proposal_id = _seed_proposal(app, user_id)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["usuario_id"] = user_id
        sess["tipo"] = "consultor"

    payload = {
        "document_type": "cnpj",
        "document": "11222333000181",
        "company": "Empresa Editada",
        "client_name": "Cliente",
        "email": "cliente@example.com",
        "telefone": "5511999999999",
        "servico_type": "PONTO",
        "modalidade_type": "AQUISICAO",
        "usar_outro_usuario": "nao",
        "enviar_email": "0",
    }

    resp = client.post(f"/editar_proposta/{proposal_id}", data=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True

    with app.app_context():
        proposals = Proposal.query.order_by(Proposal.id.asc()).all()
        assert len(proposals) == 2
        original = Proposal.query.get(proposal_id)
        new_prop = Proposal.query.get(data["new_id"])

        assert original.is_current is False
        assert original.is_original is True
        assert original.version_number == 1

        assert new_prop.is_current is True
        assert new_prop.is_original is False
        assert new_prop.version_number == 2
        assert new_prop.original_proposal_id == proposal_id
        assert new_prop.filename == original.filename


def test_aprovar_proposta_marks_approved(app):
    user_id = _seed_user(app)
    proposal_id = _seed_proposal(app, user_id, company="Empresa Aprovar")

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["usuario_id"] = user_id
        sess["tipo"] = "consultor"

    resp = client.post(f"/aprovar_proposta/{proposal_id}")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True

    with app.app_context():
        proposal = Proposal.query.get(proposal_id)
        assert proposal.approved_at is not None
        assert proposal.approved_by_id == user_id


def test_historico_filter_by_company_or_cnpj(app):
    user_id = _seed_user(app)
    proposal_a = _seed_proposal(
        app,
        user_id,
        company="Alpha Ltda",
        cnpj="11222333000181",
    )
    proposal_b = _seed_proposal(
        app,
        user_id,
        company="Beta Ltda",
        cnpj="00987654000100",
    )

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["usuario_id"] = user_id
        sess["tipo"] = "consultor"

    resp_company = client.get("/historico_propostas?empresa=Alpha")
    assert resp_company.status_code == 200
    html_company = resp_company.get_data(as_text=True)
    assert f'data-proposal-id="{proposal_a}"' in html_company
    assert f'data-proposal-id="{proposal_b}"' not in html_company

    resp_cnpj = client.get("/historico_propostas?empresa=11222333000181")
    assert resp_cnpj.status_code == 200
    html_cnpj = resp_cnpj.get_data(as_text=True)
    assert f'data-proposal-id="{proposal_a}"' in html_cnpj
    assert f'data-proposal-id="{proposal_b}"' not in html_cnpj
