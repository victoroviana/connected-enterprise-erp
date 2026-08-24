"""Sollus Tickets module integration."""
from __future__ import annotations

import json

import click
from flask import Flask


def _start_scheduler(app: Flask) -> None:
    """Inicia o APScheduler para processamento automático de e-mail e alertas SLA."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        app.logger.warning(
            "[tickets] APScheduler não instalado. Ingestão de e-mail será apenas manual. "
            "Execute: pip install apscheduler"
        )
        return

    scheduler = BackgroundScheduler(daemon=True, timezone="America/Sao_Paulo")

    def _sync_mail_job():
        with app.app_context():
            try:
                from .email_ingest import sync_enabled_mailboxes
                sync_enabled_mailboxes()
            except Exception as exc:
                from .services import log_system_event
                log_system_event("Scheduler Error: sync_mail", str(exc), level="error", source="cron")
                app.logger.exception("[tickets_scheduler] erro na sincronização de e-mail")

    def _sla_alerts_job():
        with app.app_context():
            try:
                from .ticket_mailer import run_sla_alerts
                from .services import update_sla_overdue, log_system_event
                
                # Atualiza flags de vencimento antes de enviar alertas
                update_sla_overdue()
                
                count = run_sla_alerts(app)
                if count:
                    log_system_event("Scheduler Task", f"Enviados {count} alertas de SLA.", level="info", source="cron")
                    app.logger.info("[tickets_scheduler] %s alertas de SLA enviados", count)
            except Exception as exc:
                from .services import log_system_event
                log_system_event("Scheduler Error: sla_alerts", str(exc), level="error", source="cron")
                app.logger.exception("[tickets_scheduler] erro nos alertas de SLA")

    def _process_email_queue_job():
        with app.app_context():
            try:
                from .ticket_mailer import process_email_queue
                process_email_queue(app)
            except Exception as exc:
                app.logger.exception("[tickets_scheduler] erro ao processar fila de e-mails")

    scheduler.add_job(_sync_mail_job, IntervalTrigger(minutes=5), id="tickets_sync_mail", replace_existing=True)
    scheduler.add_job(_sla_alerts_job, IntervalTrigger(minutes=15), id="tickets_sla_alerts", replace_existing=True)
    scheduler.add_job(_process_email_queue_job, IntervalTrigger(minutes=1), id="tickets_process_email_queue", replace_existing=True)

    scheduler.start()
    app.logger.info("[tickets] APScheduler iniciado: sync_mail(5min), sla_alerts(1h)")

    import atexit
    atexit.register(lambda: scheduler.shutdown(wait=False))


def init_app(app: Flask) -> None:
    from . import models  # noqa: F401
    from .blueprints.tickets import sollus_tickets_bp
    from .email_ingest import sync_enabled_mailboxes, sync_mailbox
    from .importer import (
        import_osticket,
        import_osticket_attachments,
        import_osticket_mailboxes,
        import_osticket_settings,
        parse_ost_config,
    )
    from .services import ensure_sollus_ticket_tables

    app.register_blueprint(sollus_tickets_bp)

    with app.app_context():
        ensure_sollus_ticket_tables()

    # Inicia o scheduler apenas quando rodando como servidor web (não em CLI)
    import sys
    is_cli = any(cmd in sys.argv[0] for cmd in ("flask", "pytest")) or "cli" in " ".join(sys.argv)
    if not is_cli and not app.config.get("TESTING"):
        _start_scheduler(app)

    @app.cli.command("sollus-tickets-import-osticket")
    @click.option("--config", "config_path", required=True, help="Caminho para include/ost-config.php.")
    @click.option("--limit", type=int, default=None, help="Limitar quantidade de tickets importados.")
    @click.option("--batch-size", type=int, default=100, help="Quantidade de tickets por commit.")
    @click.option("--dry-run", is_flag=True, help="Executa sem gravar alteracoes.")
    def import_osticket_command(config_path: str, limit: int | None, batch_size: int, dry_run: bool) -> None:
        """Import legacy osTicket records into Sollus Tickets."""
        config = parse_ost_config(config_path)
        stats = import_osticket(config, limit=limit, dry_run=dry_run, batch_size=batch_size)
        click.echo(json.dumps(stats, ensure_ascii=False, indent=2))

    @app.cli.command("sollus-tickets-sync-email")
    @click.option("--mailbox-id", type=int, default=None, help="Sincronizar apenas uma caixa.")
    @click.option("--limit", type=int, default=None, help="Quantidade maxima de mensagens por caixa.")
    @click.option("--force", is_flag=True, help="Ignora intervalo de busca configurado.")
    def sync_email_command(mailbox_id: int | None, limit: int | None, force: bool) -> None:
        """Fetch IMAP messages and create/reply Sollus Tickets."""
        if mailbox_id:
            stats = sync_mailbox(mailbox_id, limit=limit)
        else:
            stats = sync_enabled_mailboxes(limit=limit, force=force)
        click.echo(json.dumps(stats, ensure_ascii=False, indent=2))

    @app.cli.command("sollus-tickets-import-mailboxes")
    @click.option("--config", "config_path", required=True, help="Caminho para include/ost-config.php.")
    def import_mailboxes_command(config_path: str) -> None:
        """Import legacy osTicket mailbox settings into Sollus Tickets."""
        stats = import_osticket_mailboxes(parse_ost_config(config_path))
        click.echo(json.dumps(stats, ensure_ascii=False, indent=2))

    @app.cli.command("sollus-tickets-import-settings")
    @click.option("--config", "config_path", required=True, help="Caminho para include/ost-config.php.")
    def import_settings_command(config_path: str) -> None:
        """Import legacy osTicket settings without importing tickets."""
        stats = import_osticket_settings(parse_ost_config(config_path))
        click.echo(json.dumps(stats, ensure_ascii=False, indent=2))

    @app.cli.command("sollus-tickets-import-attachments")
    @click.option("--config", "config_path", required=True, help="Caminho para include/ost-config.php.")
    @click.option("--limit", type=int, default=None, help="Limitar quantidade de anexos importados.")
    def import_attachments_command(config_path: str, limit: int | None) -> None:
        """Import legacy osTicket attachments into Sollus Tickets."""
        stats = import_osticket_attachments(parse_ost_config(config_path), limit=limit)
        click.echo(json.dumps(stats, ensure_ascii=False, indent=2))

