"""Cracha module setup and blueprint registration."""
from __future__ import annotations

from flask import Flask


def init_app(app: Flask) -> None:
    """Register cracha blueprints."""
    from .blueprints.cracha import cracha_bp, ensure_cracha_legacy_tables

    app.register_blueprint(cracha_bp)

    with app.app_context():
        ensure_cracha_legacy_tables()
