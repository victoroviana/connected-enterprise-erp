"""Suporte module integration point."""
from __future__ import annotations

from flask import Flask


def init_app(app: Flask) -> None:
    """Register suporte models and blueprints."""
    from . import models  # noqa: F401  # ensure tables are mapped
    from .blueprints.atendimentos import support_bp, tech_bp
    from .blueprints.assistencia import assist_bp
    from .blueprints.atestados import atestados_bp
    from .cli import register_commands
    from .services.assistencia import ensure_assistencia_schema

    app.register_blueprint(support_bp)
    app.register_blueprint(tech_bp)
    app.register_blueprint(assist_bp)
    app.register_blueprint(atestados_bp)
    register_commands(app)

    with app.app_context():
        ensure_assistencia_schema()
