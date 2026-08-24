from pathlib import Path
from flask import Blueprint

_bp_dir = Path(__file__).resolve().parent
_root = _bp_dir.parents[3]

tickets_bp = Blueprint(
    "tickets",
    __name__,
    url_prefix="/tickets",
    template_folder=str(_root / "templates"),
    static_folder=str(_root / "static"),
)

from . import routes  # noqa: F401,E402
from . import views  # noqa: F401,E402

