# blueprints/equipamentos/__init__.py
from flask import Blueprint

equipamentos_bp = Blueprint(
    "equipamentos_bp",
    __name__,
    template_folder="../../templates",
    url_prefix="",
)

from . import routes        # noqa: E402,F401


