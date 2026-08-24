"""Audit module providing shared logging utilities and UI."""
from __future__ import annotations

from flask import Flask


def init_app(app: Flask) -> None:
    """Register audit blueprints and ensure models are imported."""
    from . import models  # noqa: F401  # ensure metadata is registered
    from . import listeners  # noqa: F401  # ensure event listeners are bound
    from .blueprints import audit_bp

    app.register_blueprint(audit_bp)
