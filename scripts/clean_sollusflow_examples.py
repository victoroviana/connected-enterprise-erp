# scripts/clean_sollusflow_examples.py
import sys
sys.path.insert(0, "/home/sollus/sollus_connected")

from platform_app import create_app
from extensions import db
from modules.chamados.models import SfPedido, SfFaseHistorico, SfChecklist, SfObservacao

app = create_app()
with app.app_context():
    pedidos = SfPedido.query.filter(SfPedido.numero_pedido.like("PED-2026-%")).all()
    count = len(pedidos)
    for p in pedidos:
        db.session.delete(p)
    db.session.commit()
    print(f"Limpeza concluida: {count} pedidos de exemplo removidos com sucesso.")
