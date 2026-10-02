"""Import legacy contratos and contas_receber from SQL dump into current database.

Uses INSERT IGNORE to merge missing records and maps zero-dates to NULL.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config

DUMP_PATH = PROJECT_ROOT / "implementar" / "gestao_tarefas (3).sql"
TABLES = ["contratos", "contas_receber", "novos_contratos"]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin1")


def _extract_statements(sql: str, table_name: str) -> list[str]:
    # Extract complete INSERT statements for a table
    # Standard format: INSERT INTO `table` ... ;
    prefix = f"INSERT INTO `{table_name}`"
    statements: list[str] = []
    
    # We find all occurrences of prefix
    start = 0
    while True:
        idx = sql.find(prefix, start)
        if idx < 0:
            break
            
        # Scan for statement terminator ';'
        # taking into account strings and escapes
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


def main() -> int:
    if not DUMP_PATH.exists():
        print(f"Error: Legacy dump not found at {DUMP_PATH}")
        return 1

    print(f"Reading legacy dump: {DUMP_PATH.name}...")
    sql_content = _read_text(DUMP_PATH)
    
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    
    with engine.begin() as conn:
        for table in TABLES:
            print(f"\n--- Processing table '{table}' ---")
            
            # Get initial count
            initial_count = conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar() or 0
            print(f"Initial row count in database: {initial_count}")
            
            # Extract insert statements
            stmts = _extract_statements(sql_content, table)
            print(f"Found {len(stmts)} legacy INSERT statements.")
            
            if not stmts:
                print(f"No statements found for table '{table}'. Skipping.")
                continue
                
            success_count = 0
            error_count = 0
            
            for i, stmt in enumerate(stmts, 1):
                # Apply "de-para" mapping rules:
                # 1. Convert INSERT INTO to INSERT IGNORE INTO
                mapped_stmt = stmt.replace(f"INSERT INTO `{table}`", f"INSERT IGNORE INTO `{table}`", 1)
                
                # 2. Replace zero dates with NULL
                mapped_stmt = mapped_stmt.replace("'0000-00-00 00:00:00'", "NULL")
                mapped_stmt = mapped_stmt.replace("'0000-00-00'", "NULL")
                
                try:
                    conn.exec_driver_sql(mapped_stmt)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    print(f"Error executing statement {i} for '{table}': {str(e)[:200]}")
            
            final_count = conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar() or 0
            rows_added = final_count - initial_count
            print(f"Finished processing '{table}': {success_count} statements run successfully, {error_count} failed.")
            print(f"Final row count in database: {final_count} (added {rows_added} rows)")
            
    print("\nLegacy import successfully completed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
