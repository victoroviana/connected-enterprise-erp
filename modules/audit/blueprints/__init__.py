"""Blueprint exposing the audit UI and API."""
from __future__ import annotations

from flask import Blueprint


audit_bp = Blueprint("audit", __name__, url_prefix="/audit")

from . import routes  # noqa: E402,F401
