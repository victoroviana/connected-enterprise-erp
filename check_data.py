from app import create_app
from extensions import db
from sqlalchemy import text
from modules.suporte.services.chamados import list_regions

app = create_app()
with app.app_context():
    regions = list_regions()
    region = regions[0]
    try:
        rows = db.session.execute(text(f"SELECT DISTINCT tipo_atendimento FROM {region.table_name}")).fetchall()
        print("TIPO ATENDIMENTO:")
        for r in rows:
            print(f"'{r[0]}'")
        
        rows = db.session.execute(text(f"SELECT DISTINCT tecnico FROM {region.table_name}")).fetchall()
        print("\nTECNICO:")
        for r in rows:
            print(f"'{r[0]}'")
    except Exception as e:
        print("ERROR:", e)
