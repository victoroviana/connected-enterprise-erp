from app import app
from extensions import db
from modules.propostas.models import Proposal

with app.app_context():
    p = Proposal.query.get(315)
    if p and "GF27" in (p.filename or "").upper():
        print(f"Fixing proposal {p.filename} (ID: {p.id})")
        print(f"Old Total: {p.sistema_preco_total}, Old Fixed: {p.sistema_preco_fixo}")
        
        p.sistema_preco_fixo = True
        p.sistema_preco_total = p.sistema_preco_unitario
        
        db.session.commit()
        print(f"New Total: {p.sistema_preco_total}, New Fixed: {p.sistema_preco_fixo}")
    else:
        print("Proposal GF27 (ID 315) not found or mismatch.")
