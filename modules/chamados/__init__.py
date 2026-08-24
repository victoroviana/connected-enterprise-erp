"""Chamados module integration point."""
from __future__ import annotations

from flask import Flask


def init_app(app: Flask) -> None:
    """Initialise chamados models and register blueprints."""
    from . import models  # noqa: F401
    from .blueprints.tickets import tickets_bp
    from .blueprints.central_conhecimento import central_conhecimento_bp
    from .blueprints.admin import admin_bp
    from .blueprints.audit import audit_bp

    app.register_blueprint(tickets_bp)
    app.register_blueprint(central_conhecimento_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(audit_bp)
