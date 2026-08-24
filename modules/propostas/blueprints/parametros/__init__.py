# blueprints/parametros/__init__.py
from flask import Blueprint

parametros_bp = Blueprint(
    'parametros_bp',
    __name__,
    template_folder='../templates',
    static_folder='../static'
)

from . import parametros  # noqa: E402,F401
