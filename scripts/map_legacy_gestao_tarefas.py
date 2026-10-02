"""Build a mapped data-only dump from a legacy gestao_tarefas export."""
from __future__ import annotations

import argparse
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DUMP = PROJECT_ROOT / "bkp_bancos" / "gestao_tarefas (2).sql"
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "gestao_tarefas_depara.sql"

TABLE_MAP = {
    "agenda": "agenda",
    "aniversariantes": "aniversariantes",
    "ferias": "ferias",
    "empresa": "empresa",
    "atendimento_suporte": "atendimento_suporte",
    "atendimento_suporte_logs": "atendimento_suporte_logs",
    "tarefas": "tarefas",
    "tarefas_logs": "tarefas_logs",
    "anexos": "anexos",
    "chamadossollus": "chamados_rj",
    "chamados_sp": "chamados_sp",
    "chamadospr": "chamados_pr",
    "chamadoses": "chamados_es",
    "chamadoscampos": "chamados_cp",
    "chamadoscoldrio": "chamados_coldrio",
    "chamadosae": "chamados_ae",
}

CHAMADOS_TABLES = {
    "chamadossollus",
    "chamados_sp",
    "chamadospr",
    "chamadoses",
    "chamadoscampos",
    "chamadoscoldrio",
    "chamadosae",
}

CHAMADOS_COLUMN_MAP = {
    "chamadossollus": {"CNPJ": "cnpj", "os_entrada": "arquivo_entrada", "os_saida": "arquivo_saida"},
    "chamadoscampos": {"CNPJ": "cnpj", "os_entrada": "arquivo_entrada", "os_saida": "arquivo_saida"},
    "chamadospr": {"CNPJ": "cnpj", "os_entrada": "arquivo_entrada", "os_saida": "arquivo_saida"},
    "chamadoses": {"CNPJ": "cnpj", "os_entrada": "arquivo_entrada", "os_saida": "arquivo_saida"},
    "chamadoscoldrio": {"CNPJ": "cnpj", "os_entrada": "arquivo_entrada", "os_saida": "arquivo_saida"},
    "chamadosae": {"CNPJ": "cnpj", "os_entrada": "arquivo_entrada", "os_saida": "arquivo_saida"},
    # chamados_sp mantém CNPJ/os_entrada/os_saida como no schema atual.
}

TABLE_COLUMN_MAP = {}

INSERT_RE = re.compile(
    r"^INSERT INTO `(?P<table>[^`]+)`\s*\((?P<cols>[^)]*)\)\s*VALUES\s*(?P<values>.*);$",
    re.IGNORECASE | re.DOTALL,
)

ZERO_DATES = (
    "'0000-00-00 00:00:00'",
    "'0000-00-00'",
)


def _open_text(path: Path):
    for encoding in ("utf-8", "latin1"):
        try:
            handle = path.open("r", encoding=encoding)
            handle.read(1024)
            handle.seek(0)
            return handle
        except UnicodeDecodeError:
            continue
    return path.open("r", encoding="utf-8", errors="replace")


def _iter_insert_statements(path: Path):
    collecting = False
    buffer: list[str] = []
    with _open_text(path) as handle:
        for line in handle:
            stripped = line.lstrip()
            if not collecting:
                if not stripped.upper().startswith("INSERT INTO "):
                    continue
                collecting = True
            buffer.append(line.rstrip("\n"))
            if line.rstrip().endswith(";"):
                statement = "\n".join(buffer).strip()
                buffer = []
                collecting = False
                if statement:
                    yield statement
        if buffer:
            statement = "\n".join(buffer).strip()
            if statement:
                yield statement


def _transform_insert(statement: str) -> tuple[str, str] | None:
    match = INSERT_RE.match(statement)
    if not match:
        return None

    table = match.group("table")
    if table not in TABLE_MAP:
        return None

    target_table = TABLE_MAP[table]
    cols_text = match.group("cols")
    values_text = match.group("values").strip()

    cols_raw = [col.strip() for col in cols_text.split(",") if col.strip()]
    col_names = [col.strip("`") for col in cols_raw]

    column_map = dict(TABLE_COLUMN_MAP.get(table, {}))
    if table in CHAMADOS_TABLES:
        column_map.update(CHAMADOS_COLUMN_MAP.get(table, {}))
    if column_map:
        col_names = [column_map.get(col, col) for col in col_names]

    new_cols = ", ".join(f"`{col}`" for col in col_names)

    for zero in ZERO_DATES:
        values_text = values_text.replace(zero, "NULL")

    mapped = f"INSERT INTO `{target_table}` ({new_cols}) VALUES {values_text};"
    return target_table, mapped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate mapped INSERTs for legacy gestao_tarefas dumps."
    )
    parser.add_argument(
        "--dump-path",
        default=str(DEFAULT_DUMP),
        help="Path to the legacy gestao_tarefas SQL dump.",
    )
    parser.add_argument(
        "--output-path",
        default=str(DEFAULT_OUTPUT),
        help="Path to write the mapped data-only SQL file.",
    )
    parser.add_argument(
        "--no-fk-toggle",
        action="store_true",
        help="Do not emit FOREIGN_KEY_CHECKS toggles.",
    )
    args = parser.parse_args()

    dump_path = Path(args.dump_path)
    output_path = Path(args.output_path)

    if not dump_path.exists():
        raise FileNotFoundError(f"Dump not found: {dump_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    totals: dict[str, int] = {}
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(f"-- mapped from: {dump_path}\n")
        if not args.no_fk_toggle:
            handle.write("SET FOREIGN_KEY_CHECKS = 0;\n")

        for statement in _iter_insert_statements(dump_path):
            result = _transform_insert(statement)
            if not result:
                continue
            table, mapped = result
            totals[table] = totals.get(table, 0) + 1
            handle.write(mapped)
            handle.write("\n")

        if not args.no_fk_toggle:
            handle.write("SET FOREIGN_KEY_CHECKS = 1;\n")

    if totals:
        summary = ", ".join(f"{name}={count}" for name, count in sorted(totals.items()))
        print(f"Mapped statements written to {output_path}")
        print(f"Tables included: {summary}")
    else:
        print("No matching INSERT statements were found.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
