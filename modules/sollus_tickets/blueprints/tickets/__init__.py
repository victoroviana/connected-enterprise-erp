from __future__ import annotations

from pathlib import Path

from flask import Blueprint

_bp_dir = Path(__file__).resolve().parent
_root = _bp_dir.parents[3]

sollus_tickets_bp = Blueprint(
    "sollus_tickets",
    __name__,
    url_prefix="/sollus-tickets",
    template_folder=str(_root / "templates"),
    static_folder=str(_root / "static"),
)

from . import routes  # noqa: E402,F401
