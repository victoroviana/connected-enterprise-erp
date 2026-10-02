"""Import legacy contratos data from the SQL dump into the current database."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin1")


def _scan_statement(sql: str, start_index: int) -> str:
    in_string = False
    escaped = False
    idx = start_index
    while idx < len(sql):
        ch = sql[idx]
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
                return sql[start_index : idx + 1].strip()
        idx += 1
    raise RuntimeError("Statement terminator not found")


def _extract_statements(sql: str, prefix: str, label: str) -> list[str]:
    statements: list[str] = []
    start = 0
    while True:
        idx = sql.find(prefix, start)
        if idx < 0:
            break
        statements.append(_scan_statement(sql, idx))
        start = idx + len(prefix)
    if not statements:
        raise RuntimeError(f"Statement not found for {label}")
    return statements


def _ensure_create_if_missing(statement: str) -> str:
    return statement.replace("CREATE TABLE `contratos`", "CREATE TABLE IF NOT EXISTS `contratos`", 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy contratos from SQL dump.")
    parser.add_argument(
        "--dump-path",
        default=str(PROJECT_ROOT / "outputs" / "gestao_tarefas_atual.sql"),
        help="Path to the legacy SQL dump.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate contratos before importing.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Import all contratos (default keeps only cancelados).",
    )
    args = parser.parse_args()

    dump_path = Path(args.dump_path)
    if not dump_path.exists():
        raise FileNotFoundError(f"Dump not found: {dump_path}")

    sql = _read_text(dump_path)
    create_stmt = _extract_statements(
        sql,
        "CREATE TABLE `contratos`",
        "create contratos",
    )[0]
    insert_stmts = _extract_statements(
        sql,
        "INSERT INTO `contratos`",
        "insert contratos",
    )

    create_stmt = _ensure_create_if_missing(create_stmt)

    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    with engine.begin() as conn:
        conn.exec_driver_sql(create_stmt)

        if args.truncate:
            conn.execute(text("TRUNCATE TABLE contratos"))
        else:
            existing = conn.execute(text("SELECT COUNT(1) FROM contratos")).scalar() or 0
            if existing:
                raise RuntimeError(
                    "Table contratos already has data. Use --truncate to reimport."
                )

        for stmt in insert_stmts:
            conn.exec_driver_sql(stmt)

        if not args.all:
            conn.execute(text("DELETE FROM contratos WHERE status NOT LIKE 'Cancelado%'"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
