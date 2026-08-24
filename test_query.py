from app import create_app
from extensions import db
from sqlalchemy import text
from modules.suporte.services.chamados import list_regions

app = create_app()
with app.app_context():
    regions = list_regions()
    region = regions[0]
    column_name = 'tecnico'
    try:
        rows = db.session.execute(
            text(
                f"SELECT DISTINCT {column_name} "
                f"FROM {region.table_name} "
                f"WHERE {column_name} IS NOT NULL AND {column_name} != '' "
                f"ORDER BY {column_name} ASC"
            )
        ).fetchall()
        print(len(rows))
    except Exception as e:
        print('ERROR:', e)
