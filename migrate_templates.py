import sys
from app import create_app
from extensions import db
from modules.suporte.models import OrcamentoTemplate
from modules.suporte.services.orcamentos import ORCAMENTO_DEFINITIONS

def migrate():
    app = create_app()
    with app.app_context():
        # create table if it doesn't exist
        db.create_all()
        for key, value in ORCAMENTO_DEFINITIONS.items():
            existing = OrcamentoTemplate.query.filter_by(chave=key).first()
            if not existing:
                template = OrcamentoTemplate(
                    chave=key,
                    label=value.get('label', key),
                    table_title=value.get('table_title', key),
                    items=value.get('items', []),
                    condicoes=value.get('condicoes', []),
                    observacao=value.get('observacao', ''),
                    aceite=value.get('aceite', [])
                )
                db.session.add(template)
                print(f"Migrated template: {key}")
            else:
                print(f"Template already exists: {key}")
        db.session.commit()
        print("Migration complete.")

if __name__ == "__main__":
    migrate()
