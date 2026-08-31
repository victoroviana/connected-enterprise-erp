from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from flask import current_app

from extensions import db
from modules.propostas.gerar_proposta import render_proposta_html_pdf
from modules.propostas.models import Proposal, PdfJob
from modules.propostas.services.proposal_email import send_proposal_email


class PdfJobManager:
    def __init__(self, max_workers: int = 2):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit(
        self,
        *,
        owner_id: int,
        action: str,
        proposal_id: int,
        download_name: str,
        template_relpath: str,
        context: Dict[str, Any],
        email_payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        app = current_app._get_current_object()
        job_id = uuid.uuid4().hex
        job = PdfJob(
            id=job_id,
            owner_id=owner_id,
            proposal_id=proposal_id,
            action=action,
            download_name=download_name,
            status='queued',
            payload=email_payload or {},
        )
        db.session.add(job)
        db.session.commit()

        self._executor.submit(
            self._worker,
            app,
            job_id,
            action,
            proposal_id,
            download_name,
            template_relpath,
            context,
            email_payload or {},
        )
        return job_id

    def _worker(
        self,
        app,
        job_id: str,
        action: str,
        proposal_id: int,
        download_name: str,
        template_relpath: str,
        context: Dict[str, Any],
        email_payload: Dict[str, Any],
    ) -> None:
        with app.app_context():
            try:
                self._update(job_id, status='running')
                pdf_bytes = render_proposta_html_pdf(template_relpath, context)
                if action in {'baixar', 'visualizar'}:
                    folder = Path(app.instance_path) / 'generated_proposals'
                    folder.mkdir(parents=True, exist_ok=True)
                    file_path = folder / f'{job_id}.pdf'
                    file_path.write_bytes(pdf_bytes)
                    now = datetime.utcnow()
                    expires = now + timedelta(hours=1)
                    file_size = file_path.stat().st_size
                    self._update(
                        job_id,
                        status='done',
                        file_path=str(file_path),
                        file_size=file_size,
                        expires_at=expires,
                        generated_at=now,
                    )
                    return
                if action == 'enviar_email':
                    proposta = Proposal.query.get(proposal_id)
                    if not proposta:
                        raise RuntimeError('Proposta não encontrada para envio de e-mail.')
                    send_proposal_email(
                        proposta,
                        email_payload.get('body', ''),
                        email_payload.get('cc', []),
                        pdf_bytes=pdf_bytes,
                    )
                    self._update(
                        job_id,
                        status='done',
                        generated_at=datetime.utcnow(),
                        payload={'message': 'Proposta enviada por e-mail com sucesso.'},
                    )
                    return
                raise RuntimeError(f'Ação desconhecida: {action}')
            except Exception as exc:  # pragma: no cover
                db.session.rollback()
                current_app.logger.exception('Falha no processamento do job de PDF %s', job_id)
                self._update(job_id, status='error', error=str(exc))
            finally:
                db.session.remove()

    def _update(self, job_id: str, **kwargs) -> Optional[PdfJob]:
        try:
            job = PdfJob.query.get(job_id)
            if not job:
                return None
            for key, value in kwargs.items():
                if key == 'payload' and isinstance(value, dict):
                    job.payload = value
                else:
                    setattr(job, key, value)
            job.updated_at = datetime.utcnow()
            db.session.commit()
            return job
        except Exception:
            db.session.rollback()
            raise

    def get(self, job_id: str, owner_id: int) -> Optional[PdfJob]:
        job = PdfJob.query.get(job_id)
        if not job or job.owner_id != owner_id:
            return None
        return job

    def cleanup(self) -> None:
        try:
            now = datetime.utcnow()
            expired_jobs = PdfJob.query.filter(
                PdfJob.expires_at.isnot(None),
                PdfJob.expires_at < now,
            ).all()
            if not expired_jobs:
                return
            for job in expired_jobs:
                if job.file_path:
                    Path(job.file_path).unlink(missing_ok=True)
                db.session.delete(job)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Falha no cleanup de jobs de PDF')


manager = PdfJobManager()
