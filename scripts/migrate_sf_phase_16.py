#!/usr/bin/env python3
"""
Migration script for SollusFlow:
Inserts stage 15 ("Aguardando Resposta do Cliente") before "Pós-Venda",
moving existing "Pós-Venda" from phase 15 to phase 16.
Updates sf_pedidos, sf_checklist, sf_fase_historico, and sf_config.
"""
import sys
import os
import json

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platform_app import create_app
from extensions import db
from sqlalchemy import text

def run_migration():
    print("[MIGRATION] Initializing Flask application context...")
    app = create_app()
    with app.app_context():
        print("[MIGRATION] Executing database migration...")
        
        # 1. Check current status
        res = db.session.execute(text("SELECT COUNT(*) AS total FROM sf_pedidos WHERE fase_atual = 15")).fetchone()
        pedidos_15 = res[0]

        res = db.session.execute(text("SELECT COUNT(*) AS total FROM sf_checklist WHERE fase = 15")).fetchone()
        checklists_15 = res[0]

        res = db.session.execute(text("SELECT COUNT(*) AS total FROM sf_fase_historico WHERE fase_para = 15 OR fase_de = 15")).fetchone()
        historico_15 = res[0]

        res = db.session.execute(text("SELECT valor FROM sf_config WHERE chave = 'fases_ordem'")).fetchone()
        ordem_antiga = json.loads(res[0]) if res and res[0] else []

        print(f"[STATUS ANTES]")
        print(f" - Pedidos na fase 15 (Pós-Venda antiga): {pedidos_15}")
        print(f" - Itens de checklist na fase 15 (Pós-Venda antiga): {checklists_15}")
        print(f" - Registros de histórico envolvendo fase 15: {historico_15}")
        print(f" - Ordem atual em sf_config: {ordem_antiga}")

        # 2. Update sf_pedidos
        r1 = db.session.execute(text("UPDATE sf_pedidos SET fase_atual = 16 WHERE fase_atual = 15"))
        print(f"[UPDATE] sf_pedidos atualizados para fase 16: {r1.rowcount}")

        # 3. Update sf_checklist
        r2 = db.session.execute(text("UPDATE sf_checklist SET fase = 16 WHERE fase = 15"))
        print(f"[UPDATE] sf_checklist atualizados para fase 16: {r2.rowcount}")

        # 4. Update sf_fase_historico
        r3 = db.session.execute(text("UPDATE sf_fase_historico SET fase_de = 16 WHERE fase_de = 15"))
        r4 = db.session.execute(text("UPDATE sf_fase_historico SET fase_para = 16 WHERE fase_para = 15"))
        print(f"[UPDATE] sf_fase_historico: fase_de={r3.rowcount}, fase_para={r4.rowcount}")

        # 5. Update sf_config phases order
        nova_ordem = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
        nova_ordem_json = json.dumps(nova_ordem)
        db.session.execute(
            text(
                "INSERT INTO sf_config (chave, valor, updated_at) VALUES ('fases_ordem', :val, NOW()) "
                "ON DUPLICATE KEY UPDATE valor = VALUES(valor), updated_at = NOW()"
            ),
            {"val": nova_ordem_json}
        )
        print(f"[UPDATE] sf_config fases_ordem atualizado para: {nova_ordem}")

        # Commit transaction
        db.session.commit()
        print("[SUCCESS] Migração concluída com sucesso no banco de dados!")

        # 6. Verify post-migration state
        novo_15 = db.session.execute(text("SELECT COUNT(*) FROM sf_pedidos WHERE fase_atual = 15")).scalar()
        novo_16 = db.session.execute(text("SELECT COUNT(*) FROM sf_pedidos WHERE fase_atual = 16")).scalar()
        novo_chk_16 = db.session.execute(text("SELECT COUNT(*) FROM sf_checklist WHERE fase = 16")).scalar()

        print(f"[STATUS DEPOIS]")
        print(f" - Pedidos na fase 15 (Aguardando Resposta do Cliente): {novo_15}")
        print(f" - Pedidos na fase 16 (Pós-Venda): {novo_16}")
        print(f" - Itens de checklist na fase 16: {novo_chk_16}")

if __name__ == "__main__":
    run_migration()
