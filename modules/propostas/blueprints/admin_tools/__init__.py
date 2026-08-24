"""Blueprint com utilitários administrativos legados."""
from flask import Blueprint

admin_tools_bp = Blueprint(
    "admin_tools_bp",
    __name__,
    template_folder="../../templates",
)

from . import routes  # noqa: E402,F401
