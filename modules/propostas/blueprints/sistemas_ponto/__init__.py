from flask import Blueprint

sistemas_ponto_bp = Blueprint(
    'sistemas_ponto_bp',
    __name__,
    template_folder='../templates',
    static_folder='../static'
)

from . import sistemas  # noqa: E402,F401
