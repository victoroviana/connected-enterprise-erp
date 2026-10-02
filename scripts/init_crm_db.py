import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from platform_app import create_app
from extensions import db
from modules.crm.models import (
    CrmFunil,
    CrmEtapa,
    CrmEmpresa,
    CrmContato,
    CrmNegociacao,
    CrmTarefa,
    CrmInteracao,
    CrmLeadMarketing
)

app = create_app()
with app.app_context():
    db.create_all()
    print("[OK] Tabelas CRM criadas com sucesso no banco de dados.")
