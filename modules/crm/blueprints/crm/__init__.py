"""Blueprint para o módulo Sollus CRM."""
from flask import Blueprint

crm_bp = Blueprint("crm", __name__, url_prefix="/crm")

from . import routes  # noqa: E402, F401
