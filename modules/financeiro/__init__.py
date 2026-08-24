"""Financeiro module integration point."""
from __future__ import annotations

from flask import Flask


def init_app(app: Flask) -> None:
    """Register financeiro blueprints."""
    from .blueprints.financeiro import financeiro_bp

    app.register_blueprint(financeiro_bp)
