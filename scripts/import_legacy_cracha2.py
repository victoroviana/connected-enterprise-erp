"""Import legacy cracha/contratos CSV backups from integracao 2 into MySQL."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any, Iterable

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from modules.cracha.blueprints.cracha import _legacy_cracha_table_statements


class TableSpec:
    def __init__(
        self,
        name: str,
        csv_name: str,
        columns: list[str],
        *,
        bool_columns: Iterable[str] = (),
        int_columns: Iterable[str] = (),
        decimal_columns: Iterable[str] = (),
    ) -> None:
        self.name = name
        self.csv_name = csv_name
        self.columns = columns
        self.bool_columns = set(bool_columns)
        self.int_columns = set(int_columns)
        self.decimal_columns = set(decimal_columns)


TABLES: list[TableSpec] = [
    TableSpec(
        "ja_emp_empresas",
        "ja_emp_empresas.csv",
        ["id_pk", "nome", "ativo"],
        bool_columns=["ativo"],
        int_columns=["id_pk"],
    ),
    TableSpec(
        "ja_emp_empresas_usuarios",
        "ja_emp_empresas_usuarios.csv",
        ["id_pk", "idempresas_fk", "idusuarios_fk"],
        int_columns=["id_pk", "idempresas_fk", "idusuarios_fk"],
    ),
    TableSpec(
        "ja_sys_ufs",
        "ja_sys_ufs.csv",
        ["id_pk", "sigla", "estado"],
        int_columns=["id_pk"],
    ),
    TableSpec(
        "ja_prm_localidades",
        "ja_prm_localidades.csv",
        ["id_pk", "localidade"],
        int_columns=["id_pk"],
    ),
    TableSpec(
        "ja_cli_clientes",
        "ja_cli_clientes.csv",
        [
            "id_pk",
            "nome_fantasia",
            "razao_social",
            "cnpj",
            "cpf",
            "inscricao_estadual",
            "rg",
            "telefone1",
            "telefone2",
            "telefone3",
            "telefone4",
            "email",
            "website",
            "endereco",
            "endereco_numero",
            "endereco_complemento",
            "endereco_bairro",
            "endereco_municipio",
            "endereco_uf",
            "endereco_cep",
            "fax",
            "tipo",
            "ativo",
            "idlocalidades_fk",
            "contato",
            "contato_setor",
            "idempresas_fk",
        ],
        bool_columns=["ativo"],
        int_columns=["id_pk", "idlocalidades_fk", "idempresas_fk", "tipo"],
    ),
    TableSpec(
        "ja_usr_usuarios",
        "ja_usr_usuarios.csv",
        ["id_pk", "nome", "login", "senha", "email", "idclientes_fk", "ativo", "senha2"],
        bool_columns=["ativo"],
        int_columns=["id_pk", "idclientes_fk"],
    ),
    TableSpec(
        "ja_pro_produtos_grupo",
        "ja_pro_produtos_grupo.csv",
        ["id_pk", "nome", "ativo"],
        bool_columns=["ativo"],
        int_columns=["id_pk"],
    ),
    TableSpec(
        "ja_pro_produtos_marca",
        "ja_pro_produtos_marca.csv",
        ["id_pk", "nome", "ativo"],
        bool_columns=["ativo"],
        int_columns=["id_pk"],
    ),
    TableSpec(
        "ja_pro_fornecedor",
        "ja_pro_fornecedor.csv",
        ["id_pk", "nome", "ativo"],
        bool_columns=["ativo"],
        int_columns=["id_pk"],
    ),
    TableSpec(
        "ja_pro_produtos",
        "ja_pro_produtos.csv",
        [
            "id_pk",
            "produto",
            "codigo",
            "controlado_numero_serie",
            "observacoes",
            "idprodutos_grupo_fk",
            "idprodutos_marca_fk",
            "codigo_marca",
        ],
        bool_columns=["controlado_numero_serie"],
        int_columns=["id_pk", "idprodutos_grupo_fk", "idprodutos_marca_fk"],
    ),
    TableSpec(
        "ja_pro_produtos_detalhe",
        "ja_pro_produtos_detalhe.csv",
        [
            "id_pk",
            "idprodutos_fk",
            "quantidade_minima",
            "quantidade_maxima",
            "ativo",
            "idempresas_fk",
            "corredor",
            "prateleira",
            "gaveta",
            "quantidade_atual",
            "armario",
            "palete",
        ],
        bool_columns=["ativo"],
        int_columns=[
            "id_pk",
            "idprodutos_fk",
            "quantidade_minima",
            "quantidade_maxima",
            "idempresas_fk",
            "quantidade_atual",
        ],
    ),
    TableSpec(
        "ja_pro_produtos_numeros_series",
        "ja_pro_produtos_numeros_series.csv",
        ["id_pk", "idprodutos_fk", "numero_serie"],
        int_columns=["id_pk", "idprodutos_fk"],
    ),
    TableSpec(
        "ja_cra_crachas_modelos",
        "ja_cra_crachas_modelos.csv",
        ["id_pk", "idclientes_fk", "frente", "verso", "situacao", "obs_frente", "obs_verso"],
        bool_columns=["situacao"],
        int_columns=["id_pk", "idclientes_fk"],
    ),
    TableSpec(
        "ja_cra_crachas_extratos",
        "ja_cra_crachas_extratos.csv",
        ["id_pk", "idclientes_fk", "quantidade", "entrada_saida", "idprodutos_fk", "descricao", "data"],
        int_columns=["id_pk", "idclientes_fk", "quantidade", "entrada_saida", "idprodutos_fk"],
    ),
    TableSpec(
        "ja_cli_contrato_locacao_manutencao",
        "ja_cli_contrato_locacao_manutencao.csv",
        [
            "id_pk",
            "idclientes_fk",
            "manutencao_hardeware",
            "manutencao_software",
            "locacao",
            "contrato_numero",
            "tipo_atendimento",
            "valor",
            "reposicao_de_peca",
            "ficha_manutencao",
            "nota_fiscal",
            "emissao_boleto",
            "data_assinatura",
            "vigencia",
            "idcontrato_locacao_manutencao_fk",
            "tipo_pagamento",
        ],
        bool_columns=[
            "manutencao_hardeware",
            "manutencao_software",
            "locacao",
            "reposicao_de_peca",
            "ficha_manutencao",
            "nota_fiscal",
            "emissao_boleto",
        ],
        int_columns=[
            "id_pk",
            "idclientes_fk",
            "tipo_atendimento",
            "vigencia",
            "idcontrato_locacao_manutencao_fk",
            "tipo_pagamento",
        ],
        decimal_columns=["valor"],
    ),
    TableSpec(
        "ja_cli_contrato_localidade_equipamento",
        "ja_cli_contrato_localidade_equipamento.csv",
        [
            "id_pk",
            "idcontrato_locacao_manutencao_fk",
            "endereco_cliente",
            "descricao",
            "endereco",
            "endereco_numero",
            "endereco_complemento",
            "endereco_bairro",
            "endereco_municipio",
            "endereco_uf",
            "endereco_cep",
            "idlocalidades_fk",
            "contato",
            "contato_setor",
            "telefone1",
            "telefone2",
            "telefone3",
            "telefone4",
            "email",
        ],
        bool_columns=["endereco_cliente"],
        int_columns=["id_pk", "idcontrato_locacao_manutencao_fk", "idlocalidades_fk"],
    ),
    TableSpec(
        "ja_cli_contrato_equipamentos",
        "ja_cli_contrato_equipamentos.csv",
        [
            "id_pk",
            "marca",
            "modelo",
            "numero_serie",
            "modelo_software",
            "capacidade",
            "idcontrato_localidade_equipamento_fk",
        ],
        int_columns=["id_pk", "idcontrato_localidade_equipamento_fk"],
    ),
    TableSpec(
        "ja_fin_contas_a_receber_contratos",
        "ja_fin_contas_a_receber_contratos.csv",
        [
            "id_pk",
            "data_vencimento",
            "data_pagamento",
            "valor_cobrado",
            "valor_pago",
            "idcontrato_locacao_manutencao_fk",
        ],
        int_columns=["id_pk", "idcontrato_locacao_manutencao_fk"],
        decimal_columns=["valor_cobrado", "valor_pago"],
    ),
    TableSpec(
        "ja_cli_manutencao_agendamentos",
        "ja_cli_manutencao_agendamentos.csv",
        [
            "id_pk",
            "idusuarios_fk",
            "data",
            "hora_entrada",
            "hora_saida",
            "data_inicio_para_atendimento",
            "idcontrato_localidade_equipamento_fk",
        ],
        int_columns=["id_pk", "idusuarios_fk", "idcontrato_localidade_equipamento_fk"],
    ),
]


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value or text_value.lower() in {"null", "none"}:
        return None
    return text_value


def _to_bool(value: Any) -> int | None:
    if value is None:
        return None
    text_value = str(value).strip().lower()
    if text_value in {"true", "t", "1", "sim", "yes", "y"}:
        return 1
    if text_value in {"false", "f", "0", "nao", "não", "no"}:
        return 0
    return None


def _coerce_row(row: dict[str, Any], spec: TableSpec) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for column in spec.columns:
        value = _normalize_value(row.get(column))
        if column in spec.bool_columns:
            value = _to_bool(value)
        elif column in spec.int_columns:
            value = int(value) if value is not None else None
        elif column in spec.decimal_columns:
            value = Decimal(str(value)) if value is not None else None
        data[column] = value
    return data


def _chunked(rows: Iterable[dict[str, Any]], size: int = 500) -> Iterable[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _load_csv(path: Path, spec: TableSpec) -> Iterable[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield _coerce_row(row, spec)


def _build_insert(spec: TableSpec) -> str:
    columns = ", ".join(spec.columns)
    placeholders = ", ".join(f":{col}" for col in spec.columns)
    updates = ", ".join(f"{col}=VALUES({col})" for col in spec.columns if col != "id_pk")
    return f"INSERT INTO {spec.name} ({columns}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy integracao 2 CSV backups.")
    default_folder = None
    for candidate in PROJECT_ROOT.glob("integra* 2/bancobackup"):
        default_folder = str(candidate)
        break
    if default_folder is None:
        default_folder = str(PROJECT_ROOT / "integracao_2" / "bancobackup")
    parser.add_argument(
        "--folder",
        default=default_folder,
        help="Folder containing legacy CSV backups.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate target tables before importing.",
    )
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        raise FileNotFoundError(f"CSV folder not found: {folder}")

    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    with engine.begin() as conn:
        for name, ddl in _legacy_cracha_table_statements():
            conn.exec_driver_sql(ddl)

        if args.truncate:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for spec in TABLES:
                conn.execute(text(f"TRUNCATE TABLE {spec.name}"))

        for spec in TABLES:
            csv_path = folder / spec.csv_name
            if not csv_path.exists():
                print(f"Skipping {spec.name}: CSV not found ({spec.csv_name})")
                continue

            insert_sql = _build_insert(spec)
            total = 0
            for batch in _chunked(_load_csv(csv_path, spec)):
                conn.execute(text(insert_sql), batch)
                total += len(batch)
            print(f"Imported {total} rows into {spec.name}")

        if args.truncate:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
