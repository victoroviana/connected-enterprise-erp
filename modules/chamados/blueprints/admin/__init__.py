from pathlib import Path
from flask import Blueprint

_bp_dir = Path(__file__).resolve().parent
_root = _bp_dir.parents[3]

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder=str(_root / "templates"),
    static_folder=str(_root / "static"),
)

from . import routes  # noqa: F401,E402
