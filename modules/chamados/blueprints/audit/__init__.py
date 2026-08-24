from pathlib import Path
from flask import Blueprint

_bp_dir = Path(__file__).resolve().parent
_root = _bp_dir.parents[3]

audit_bp = Blueprint(
    "audit",
    __name__,
    url_prefix="/audit",
    template_folder=str(_root / "templates"),
    static_folder=str(_root / "static"),
)

from . import routes  # noqa: F401,E402
