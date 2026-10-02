"""Sollus CRM module integration point."""
from __future__ import annotations

from flask import Flask


def init_app(app: Flask) -> None:
    """Register Sollus CRM blueprints and ensure database schema is up-to-date."""
    from .blueprints.crm import crm_bp
    from .utils.schema import ensure_crm_schema

    app.register_blueprint(crm_bp)

    with app.app_context():
        ensure_crm_schema(app)
