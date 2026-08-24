"""Propostas module setup and blueprint registration."""
from __future__ import annotations

from flask import Flask

from extensions import db


def init_app(app: Flask) -> None:
    """Register propostas blueprints and ensure legacy schema helpers run."""
    from .blueprints.auth import auth_bp
    from .blueprints.propostas import propostas_bp
    from .blueprints.equipamentos import equipamentos_bp
    from .blueprints.parametros import parametros_bp
    from .blueprints.admin_tools import admin_tools_bp
    from .api import api_bp
    from .utils.schema import (
        ensure_proposal_email_columns,
        ensure_user_signature_column,
        ensure_user_permissions_column,
        ensure_role_permissions,
        ensure_pdf_jobs_table,
        ensure_rh_department,
        ensure_user_departments_table,
        ensure_cracha_department,
        ensure_admin_tools_tables,
        ensure_assistencia_orcamentos_table,
        ensure_central_conhecimento_task_columns,
        ensure_central_conhecimento_comment_tables,
        ensure_parts_table,
    )

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(propostas_bp)
    app.register_blueprint(equipamentos_bp)
    app.register_blueprint(parametros_bp)
    app.register_blueprint(admin_tools_bp, url_prefix="/admin")
    app.register_blueprint(api_bp)

    with app.app_context():
        ensure_proposal_email_columns()
        ensure_user_signature_column()
        ensure_role_permissions()
        ensure_pdf_jobs_table()
        ensure_rh_department()
        ensure_user_departments_table()
        ensure_cracha_department()
        ensure_admin_tools_tables()
        ensure_assistencia_orcamentos_table()
        ensure_central_conhecimento_task_columns()
        ensure_central_conhecimento_comment_tables()
        ensure_parts_table()
