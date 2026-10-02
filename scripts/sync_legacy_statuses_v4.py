"""Sync statuses of existing contratos and contas_receber records with Dump 4.

For any record that exists in both, updates the live DB status to match the Dump status.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(r'c:\Users\User\Desktop\sollus_connected')
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config

DUMP_PATH = PROJECT_ROOT / "implementar" / "gestao_tarefas (4).sql"

def parse_dump_statuses(file_path, table_name, status_field_idx):
    prefix = f"INSERT INTO `{table_name}`"
    statuses = {}
    
    if not os.path.exists(file_path):
        return statuses
        
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    start = 0
    while True:
        idx = content.find(prefix, start)
        if idx < 0:
            break
            
        in_string = False
        escaped = False
        scan_idx = idx
        while scan_idx < len(content):
            ch = content[scan_idx]
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
                    statement = content[idx : scan_idx + 1].strip()
                    values_start = statement.upper().find("VALUES")
                    if values_start > 0:
                        values_part = statement[values_start + 6 : -1].strip()
                        depth = 0
                        current_tuple = []
                        in_str = False
                        escap = False
                        for char in values_part:
                            if escap:
                                escap = False
                                current_tuple.append(char)
                                continue
                            if char == '\\':
                                escap = True
                                current_tuple.append(char)
                                continue
                            if char in ("'", '"', '`'):
                                if not in_str:
                                    in_str = char
                                elif in_str == char:
                                    in_str = False
                                current_tuple.append(char)
                                continue
                            if not in_str:
                                if char == '(':
                                    depth += 1
                                    if depth == 1:
                                        current_tuple = []
                                    else:
                                        current_tuple.append(char)
                                elif char == ')':
                                    depth -= 1
                                    if depth == 0:
                                        tup_str = "".join(current_tuple)
                                        parts = []
                                        curr = []
                                        in_s = False
                                        esc = False
                                        for c in tup_str:
                                            if esc:
                                                esc = False
                                                curr.append(c)
                                                continue
                                            if c == '\\':
                                                esc = True
                                                curr.append(c)
                                                continue
                                            if c == "'":
                                                in_s = not in_s
                                                curr.append(c)
                                                continue
                                            if c == ',' and not in_s:
                                                parts.append("".join(curr).strip())
                                                curr = []
                                            else:
                                                curr.append(c)
                                        if curr:
                                            parts.append("".join(curr).strip())
                                            
                                        if parts:
                                            try:
                                                rid = int(parts[0])
                                                if len(parts) >= status_field_idx:
                                                    status_val = parts[status_field_idx - 1].strip("'")
                                                    statuses[rid] = status_val
                                            except ValueError:
                                                pass
                                    else:
                                        current_tuple.append(char)
                                else:
                                    current_tuple.append(char)
                            else:
                                current_tuple.append(char)
                    break
            scan_idx += 1
        start = scan_idx + 1
        
    return statuses


def get_live_statuses(table_name, id_col, status_col):
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    statuses = {}
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT `{id_col}`, `{status_col}` FROM `{table_name}`"))
            for row in result:
                statuses[int(row[0])] = str(row[1])
    except Exception as e:
        print(f"Error reading from live DB for {table_name}: {e}")
    return statuses


def sync_table_statuses(table_name, id_col, status_col, dump_statuses, live_statuses):
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    updated_count = 0
    
    with engine.begin() as conn:
        for rid, dump_status in dump_statuses.items():
            if rid in live_statuses:
                live_status = live_statuses[rid]
                if live_status != dump_status:
                    print(f"Updating {table_name} ID {rid}: '{live_status}' -> '{dump_status}'")
                    conn.execute(
                        text(f"UPDATE `{table_name}` SET `{status_col}` = :status WHERE `{id_col}` = :id"),
                        {"status": dump_status, "id": rid}
                    )
                    updated_count += 1
    return updated_count


def main() -> int:
    if not DUMP_PATH.exists():
        print(f"Error: Legacy dump not found at {DUMP_PATH}")
        return 1

    print(f"Reading legacy dump: {DUMP_PATH.name}...")
    
    # for contratos, Field 18 is status (index 18)
    dump_contratos = parse_dump_statuses(DUMP_PATH, 'contratos', 18)
    # for contas_receber, Field 11 is status (index 11)
    dump_contas = parse_dump_statuses(DUMP_PATH, 'contas_receber', 11)
    
    print("Reading live DB statuses...")
    live_contratos = get_live_statuses('contratos', 'id', 'status')
    live_contas = get_live_statuses('contas_receber', 'id', 'status')
    
    print(f"Connecting to database: {Config.SQLALCHEMY_DATABASE_URI.split('@')[-1] if '@' in Config.SQLALCHEMY_DATABASE_URI else Config.SQLALCHEMY_DATABASE_URI}")
    
    print("\n--- Synchronizing table 'contratos' ---")
    contratos_sync = sync_table_statuses('contratos', 'id', 'status', dump_contratos, live_contratos)
    print(f"Finished. Updated {contratos_sync} status records in 'contratos'.")
    
    print("\n--- Synchronizing table 'contas_receber' ---")
    contas_sync = sync_table_statuses('contas_receber', 'id', 'status', dump_contas, live_contas)
    print(f"Finished. Updated {contas_sync} status records in 'contas_receber'.")
    
    print("\nStatus synchronization completed successfully!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
