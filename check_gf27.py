from app import app
from extensions import db
from modules.propostas.models import Proposal

with app.app_context():
    p = Proposal.query.filter(Proposal.filename.like('%gf27%')).first()
    if p:
        print(f"ID: {p.id}")
        print(f"Filename: {p.filename}")
        print(f"Total: {p.sistema_preco_total}")
        print(f"Fixed: {p.sistema_preco_fixo}")
        print(f"Qty: {p.sistema_quantidade}")
        print(f"Price: {p.sistema_preco_unitario}")
    else:
        print("Proposal gf27 not found")
