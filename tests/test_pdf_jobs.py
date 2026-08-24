import os
from pathlib import Path

import pytest
from flask import Flask

from extensions import db, login_manager
from modules.propostas.blueprints.propostas import propostas_bp
from modules.propostas.models import PdfJob, Proposal, User
from modules.propostas.services import pdf_jobs


@pytest.fixture()
def app(tmp_path):
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()

    app = Flask(__name__, instance_path=str(instance_dir))
    app.config.update(
        SECRET_KEY="testing-key",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'test.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )

    db.init_app(app)
    login_manager.init_app(app)

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


def _sync_executor(monkeypatch):
    original_submit = pdf_jobs.manager._executor.submit
    monkeypatch.setattr(
        pdf_jobs.manager._executor,
        "submit",
        lambda func, app, *args, **kwargs: func(app, *args, **kwargs),
    )
    return original_submit


def _seed_user_and_proposal(app):
    with app.app_context():
        user = User(
            usuario="tester",
            nome_completo="Tester",
            email="tester@example.com",
            password_hash="hash",
            tipo="admin",
            role="admin",
        )
        db.session.add(user)
        db.session.commit()

        proposal = Proposal(
            company="ACME",
            cnpj="00",
            client_name="Cliente",
            email="cliente@example.com",
            telefone="",
            usuario_id=user.id,
        )
        db.session.add(proposal)
        db.session.commit()

        return user.id, proposal.id


def test_pdf_job_generates_metadata(app, monkeypatch, tmp_path):
    _sync_executor(monkeypatch)
    monkeypatch.setattr(
        pdf_jobs,
        "render_proposta_html_pdf",
        lambda template_relpath, context: b"%PDF-FAKE",
    )

    user_id, proposal_id = _seed_user_and_proposal(app)

    with app.app_context():
        job_id = pdf_jobs.manager.submit(
            owner_id=user_id,
            action="visualizar",
            proposal_id=proposal_id,
            download_name="teste.pdf",
            template_relpath="template.html",
            context={},
        )
        job = PdfJob.query.get(job_id)
        assert job is not None
        assert job.status == "done"
        assert job.file_size == len(b"%PDF-FAKE")
        assert job.generated_at is not None
        assert job.file_path
        assert Path(job.file_path).exists()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["usuario_id"] = user_id

    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["file_size"] == len(b"%PDF-FAKE")
    assert "file_size_readable" in payload
    assert payload["generated_at"] is not None

    download = client.get(f"/api/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.headers["Content-Disposition"].startswith("attachment")


def test_pdf_job_email_action_sets_message(app, monkeypatch):
    _sync_executor(monkeypatch)

    sent = {}

    def fake_render(template_relpath, context):
        return b"%PDF-FAKE"

    def fake_send_email(*args, **kwargs):
        sent["called"] = True

    monkeypatch.setattr(pdf_jobs, "render_proposta_html_pdf", fake_render)
    monkeypatch.setattr(pdf_jobs, "send_proposal_email", fake_send_email)

    user_id, proposal_id = _seed_user_and_proposal(app)

    with app.app_context():
        job_id = pdf_jobs.manager.submit(
            owner_id=user_id,
            action="enviar_email",
            proposal_id=proposal_id,
            download_name="teste.pdf",
            template_relpath="template.html",
            context={},
            email_payload={"body": "Olá"},
        )
        job = PdfJob.query.get(job_id)
        assert job.status == "done"
        assert job.file_path is None
        assert job.generated_at is not None
        assert job.payload.get("message")
        assert sent.get("called")

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["usuario_id"] = user_id

    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["message"] == "Proposta enviada por e-mail com sucesso."
