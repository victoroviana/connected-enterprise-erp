from flask import Blueprint

propostas_bp = Blueprint(
    'propostas_bp', __name__,
    template_folder='../../templates'
)

# IMPORTA as views (rotas) para dentro do blueprint  ↓↓↓
from . import propostas      # ← mantenha ESTA linha no fim do arquivo
