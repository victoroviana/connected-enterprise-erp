"""Import legacy data updates ONLY from gestao_tarefas (5).sql.

Uses INSERT IGNORE to merge missing records safely without overwriting existing data.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config

DUMP_PATH = Path(r"C:\Users\User\Downloads\gestao_tarefas (5).sql")
TABLES_TO_IMPORT = ["contratos", "contas_receber", "cota_mensal", "protocolos", "fotos", "permissoes"]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin1")


def _extract_statements(sql: str, table_name: str) -> list[str]:
    prefix = f"INSERT INTO `{table_name}`"
    statements: list[str] = []
    
    start = 0
    while True:
        idx = sql.find(prefix, start)
        if idx < 0:
            break
            
        in_string = False
        escaped = False
        scan_idx = idx
        while scan_idx < len(sql):
            ch = sql[scan_idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == "'":
                    in_string = False
            else:
                if ch == "'":
                    in_string = True
                elif ch == ";":
                    statement = sql[idx : scan_idx + 1].strip()
                    statements.append(statement)
                    break
            scan_idx += 1
            
        start = scan_idx + 1
        
    return statements


def import_legacy_v5_data() -> dict[str, int]:
    if not DUMP_PATH.exists():
        print(f"Error: Legacy dump 5 not found at {DUMP_PATH}")
        return {}

    print(f"Reading legacy dump 5: {DUMP_PATH.name}...")
    sql_content = _read_text(DUMP_PATH)
    
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    results = {}
    
    with engine.begin() as conn:
        for table in TABLES_TO_IMPORT:
            print(f"\n--- Importing new records for table '{table}' ---")
            
            initial_count = conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar() or 0
            
            stmts = _extract_statements(sql_content, table)
            if not stmts:
                print(f"No statements found for table '{table}'.")
                continue
                
            success_count = 0
            for stmt in stmts:
                mapped_stmt = stmt.replace(f"INSERT INTO `{table}`", f"INSERT IGNORE INTO `{table}`", 1)
                mapped_stmt = mapped_stmt.replace("'0000-00-00 00:00:00'", "NULL")
                mapped_stmt = mapped_stmt.replace("'0000-00-00'", "NULL")
                
                try:
                    conn.execute(text(mapped_stmt))
                    success_count += 1
                except Exception as e:
                    print(f"Error inserting into '{table}': {e}")
                    
            final_count = conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar() or 0
            added = final_count - initial_count
            results[table] = added
            print(f"Table '{table}': Initial={initial_count} | Final={final_count} | New Rows Inserted={added}")
            
    return results


if __name__ == "__main__":
    import_legacy_v5_data()
