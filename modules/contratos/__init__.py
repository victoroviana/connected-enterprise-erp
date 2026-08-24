"""Contratos module integration point."""
from __future__ import annotations

from flask import Flask


def init_app(app: Flask) -> None:
    """Register contratos blueprints."""
    from .blueprints.contratos import contratos_bp

    app.register_blueprint(contratos_bp)
