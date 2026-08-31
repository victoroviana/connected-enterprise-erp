"""Serviços para leitura e manutenção dos chamados regionais.

Este módulo trabalha com tabelas legadas de chamados. As tabelas não usam
exatamente os mesmos nomes/colunas em todas as unidades, então o código abaixo
faz mapeamento por aliases e só grava colunas existentes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Mapping, Optional

from sqlalchemy import inspect, text
from sqlalchemy.engine import Row

from extensions import db


@dataclass(frozen=True)
class RegionalBoard:
    slug: str
    label: str
    table_name: str


# Tabelas reais encontradas no banco legado.
REGIONAL_BOARDS: List[RegionalBoard] = [
    RegionalBoard("rj", "Sollus RJ", "chamadossollus"),
    RegionalBoard("sp", "Sollus SP", "chamados_sp"),
    RegionalBoard("pr", "Sollus PR", "chamadospr"),
    RegionalBoard("es", "Sollus ES", "chamadoses"),
    RegionalBoard("cp", "Sollus Campos", "chamadoscampos"),
    RegionalBoard("coldrio", "ColdRio RJ", "chamadoscoldrio"),
    RegionalBoard("ae", "AE Soluções RJ", "chamadosae"),
]


# Nomes lógicos usados pelo Python/front-end.
DESIRED_COLUMNS: List[str] = [
    "id",
    "cliente",
    "bairro",
    "ordem_servico",
    "numero_manutencao",
    "tecnico",
    "tipo_atendimento",
    "retorno",
    "status",
    "data",
    "data_os_criada",
    "data_os_tecnico",
    "hora_entrada",
    "hora_saida",
    "descricao",
    "contrato",
    "cnpj",
    "numero_proposta",
    "cep",
    "email_responsavel",
    "quem_atendeu",
    "criado_por",
    "novo_cliente",
    "tempo_atendimento",
    "arquivo_entrada",
    "arquivo_saida",
    "arq_entrada",
    "arq_saida",
]


# Aliases de compatibilidade com o schema legado.
COLUMN_ALIASES: Mapping[str, tuple[str, ...]] = {
    "id": ("id",),
    "cliente": ("cliente",),
    "bairro": ("bairro",),
    "ordem_servico": ("ordem_servico",),
    "numero_manutencao": ("numero_manutencao",),
    "tecnico": ("tecnico",),
    "tipo_atendimento": ("tipo_atendimento",),
    "retorno": ("retorno",),
    "status": ("status",),
    "data": ("data",),
    "data_os_criada": ("data_os_criada",),
    "data_os_tecnico": ("data_os_tecnico",),
    "hora_entrada": ("hora_entrada",),
    "hora_saida": ("hora_saida",),
    "descricao": ("descricao",),
    "contrato": ("contrato",),
    "cnpj": ("cnpj", "CNPJ"),
    "numero_proposta": ("numero_proposta",),
    "cep": ("cep",),
    "email_responsavel": ("email_responsavel",),
    "quem_atendeu": ("quem_atendeu",),
    "criado_por": ("criado_por",),
    "novo_cliente": ("novo_cliente",),
    "tempo_atendimento": ("tempo_atendimento",),
    "arquivo_entrada": ("arquivo_entrada", "arq_entrada", "os_entrada"),
    "arquivo_saida": ("arquivo_saida", "arq_saida", "os_saida"),
    "arq_entrada": ("arq_entrada", "arquivo_entrada", "os_entrada"),
    "arq_saida": ("arq_saida", "arquivo_saida", "os_saida"),
}


# Defaults mínimos para colunas NOT NULL do legado.
# O técnico é tratado dinamicamente porque algumas tabelas usam ENUM.
INSERT_DEFAULTS: Mapping[str, object] = {
    "retorno": "ABERTO",
    "tipo_atendimento": "CHAMADO",
    "hora_entrada": "00:00:00",
    "hora_saida": "00:00:00",
    "descricao": "",
    "cnpj": "",
    "email_responsavel": "",
    "quem_atendeu": "",
    "criado_por": "",
    "novo_cliente": "NAO",
    "numero_proposta": 0,
}

_NUMERIC_COLUMNS = {"id", "numero_manutencao", "numero_proposta"}
_GENERATED_OR_READONLY_COLUMNS = {"tempo_atendimento"}
_ENUM_RE = re.compile(r"'((?:[^'\\]|\\.)*)'")


def _quote_identifier(identifier: str) -> str:
    return f"`{str(identifier).replace('`', '``')}`"


def _table_exists(table_name: str) -> bool:
    try:
        return inspect(db.engine).has_table(table_name)
    except Exception:
        from flask import current_app

        current_app.logger.exception("Falha ao verificar tabela %s", table_name)
        return False


def _column_infos(table_name: str) -> List[dict]:
    try:
        return list(inspect(db.engine).get_columns(table_name))
    except Exception:
        from flask import current_app

        current_app.logger.exception("Falha ao inspecionar colunas da tabela %s", table_name)
        return []


def _column_info_map(table_name: str) -> Dict[str, dict]:
    return {str(col.get("name")): col for col in _column_infos(table_name)}


def _available_column_map(table_name: str) -> Dict[str, str]:
    columns = _column_infos(table_name)
    if not columns:
        return {}

    real_names = [str(column["name"]) for column in columns]
    by_lower = {name.lower(): name for name in real_names}
    result: Dict[str, str] = {}
    used_real_names: set[str] = set()

    for logical in DESIRED_COLUMNS:
        for alias in COLUMN_ALIASES.get(logical, (logical,)):
            real = by_lower.get(alias.lower())
            if real and real not in used_real_names:
                result[logical] = real
                used_real_names.add(real)
                break

    return result


def _available_columns(table_name: str) -> List[str]:
    return list(_available_column_map(table_name).keys())


def list_regions() -> List[RegionalBoard]:
    return REGIONAL_BOARDS


def get_region(slug: str) -> Optional[RegionalBoard]:
    return next((region for region in REGIONAL_BOARDS if region.slug == slug), None)


def _select_clause(column_map: Mapping[str, str]) -> str:
    parts: list[str] = []
    for logical, actual in column_map.items():
        if logical == actual:
            parts.append(_quote_identifier(actual))
        else:
            parts.append(f"{_quote_identifier(actual)} AS {_quote_identifier(logical)}")
    return ", ".join(parts)


def _has_column(column_map: Mapping[str, str], logical: str) -> bool:
    return logical in column_map and bool(column_map[logical])


def fetch_chamados(
    region: RegionalBoard,
    *,
    data: Optional[str] = None,
    tecnico: Optional[str] = None,
    status: Optional[str] = None,
    ordem_servico: Optional[str] = None,
    limit: Optional[int] = 200,
    offset: Optional[int] = None,
    order_by_closed: bool = False,
) -> List[Dict[str, object]]:
    column_map = _available_column_map(region.table_name)
    if not column_map:
        from flask import current_app

        current_app.logger.error("Nenhuma coluna encontrada para a tabela %s", region.table_name)
        return []

    table = _quote_identifier(region.table_name)
    sql = f"SELECT {_select_clause(column_map)} FROM {table} WHERE 1=1"
    params: Dict[str, object] = {}

    if data and _has_column(column_map, "data_os_criada"):
        sql += f" AND DATE({_quote_identifier(column_map['data_os_criada'])}) = :data"
        params["data"] = data

    if tecnico and _has_column(column_map, "tecnico"):
        tecnico_col = _quote_identifier(column_map["tecnico"])
        if "|" in tecnico:
            variants = [v.strip() for v in tecnico.split("|") if v.strip()]
            placeholders = []
            for i, variant in enumerate(variants):
                p_name = f"tech_{i}"
                placeholders.append(f":{p_name}")
                params[p_name] = variant
            if placeholders:
                sql += f" AND {tecnico_col} IN ({', '.join(placeholders)})"
        else:
            sql += f" AND {tecnico_col} = :tecnico"
            params["tecnico"] = tecnico

    if status and _has_column(column_map, "retorno"):
        retorno_col = _quote_identifier(column_map["retorno"])
        if isinstance(status, (list, tuple)):
            placeholders = []
            for i, st in enumerate(status):
                p_name = f"status_{i}"
                placeholders.append(f":{p_name}")
                params[p_name] = st
            sql += f" AND {retorno_col} IN ({', '.join(placeholders)})"
        elif "," in str(status):
            variants = [v.strip() for v in str(status).split(",") if v.strip()]
            placeholders = []
            for i, st in enumerate(variants):
                p_name = f"status_{i}"
                placeholders.append(f":{p_name}")
                params[p_name] = st
            sql += f" AND {retorno_col} IN ({', '.join(placeholders)})"
        else:
            sql += f" AND {retorno_col} = :status"
            params["status"] = status

    if ordem_servico and _has_column(column_map, "ordem_servico"):
        sql += f" AND {_quote_identifier(column_map['ordem_servico'])} LIKE :ordem"
        params["ordem"] = f"%{ordem_servico}%"

    order_parts: list[str] = []
    if order_by_closed:
        for key in ("data_os_tecnico", "hora_saida", "data", "data_os_criada"):
            if _has_column(column_map, key):
                col = _quote_identifier(column_map[key])
                order_parts.append(f"({col} IS NULL) ASC")
                order_parts.append(f"{col} DESC")
        if _has_column(column_map, "id"):
            col = _quote_identifier(column_map["id"])
            order_parts.append(f"({col} IS NULL) ASC")
            order_parts.append(f"{col} DESC")
    else:
        if _has_column(column_map, "retorno"):
            retorno_col = _quote_identifier(column_map["retorno"])
            order_parts.append(f"(CASE WHEN {retorno_col} = 'ABERTO' THEN 1 ELSE 0 END) DESC")
            if _has_column(column_map, "data_os_criada"):
                data_col = _quote_identifier(column_map["data_os_criada"])
                order_parts.append(
                    f"(CASE WHEN {retorno_col} = 'ABERTO' THEN TIMESTAMPDIFF(SECOND, {data_col}, NOW()) ELSE 0 END) DESC"
                )
        if _has_column(column_map, "tecnico"):
            tecnico_col = _quote_identifier(column_map["tecnico"])
            order_parts.extend([f"{tecnico_col} IS NULL", f"{tecnico_col} = ''"])
        if _has_column(column_map, "data_os_criada"):
            order_parts.append(f"{_quote_identifier(column_map['data_os_criada'])} DESC")
        elif _has_column(column_map, "id"):
            order_parts.append(f"{_quote_identifier(column_map['id'])} DESC")

    if order_parts:
        sql += " ORDER BY " + ", ".join(order_parts)

    if limit is not None and limit > 0:
        sql += f" LIMIT {int(limit)}"
        if offset is not None and offset > 0:
            sql += f" OFFSET {int(offset)}"

    result = db.session.execute(text(sql), params)
    return [_row_to_dict(row, column_map.keys()) for row in result]


def count_chamados(
    region: RegionalBoard,
    *,
    data: Optional[str] = None,
    tecnico: Optional[str] = None,
    status: Optional[str] = None,
    ordem_servico: Optional[str] = None,
) -> int:
    column_map = _available_column_map(region.table_name)
    if not column_map:
        return 0

    table = _quote_identifier(region.table_name)
    sql = f"SELECT COUNT(*) FROM {table} WHERE 1=1"
    params: Dict[str, object] = {}

    if data and _has_column(column_map, "data_os_criada"):
        sql += f" AND DATE({_quote_identifier(column_map['data_os_criada'])}) = :data"
        params["data"] = data

    if tecnico and _has_column(column_map, "tecnico"):
        tecnico_col = _quote_identifier(column_map["tecnico"])
        if "|" in tecnico:
            variants = [v.strip() for v in tecnico.split("|") if v.strip()]
            placeholders = []
            for i, variant in enumerate(variants):
                p_name = f"tech_{i}"
                placeholders.append(f":{p_name}")
                params[p_name] = variant
            if placeholders:
                sql += f" AND {tecnico_col} IN ({', '.join(placeholders)})"
        else:
            sql += f" AND {tecnico_col} = :tecnico"
            params["tecnico"] = tecnico

    if status and _has_column(column_map, "retorno"):
        retorno_col = _quote_identifier(column_map["retorno"])
        if isinstance(status, (list, tuple)):
            placeholders = []
            for i, st in enumerate(status):
                p_name = f"status_{i}"
                placeholders.append(f":{p_name}")
                params[p_name] = st
            sql += f" AND {retorno_col} IN ({', '.join(placeholders)})"
        elif "," in str(status):
            variants = [v.strip() for v in str(status).split(",") if v.strip()]
            placeholders = []
            for i, st in enumerate(variants):
                p_name = f"status_{i}"
                placeholders.append(f":{p_name}")
                params[p_name] = st
            sql += f" AND {retorno_col} IN ({', '.join(placeholders)})"
        else:
            sql += f" AND {retorno_col} = :status"
            params["status"] = status

    if ordem_servico and _has_column(column_map, "ordem_servico"):
        sql += f" AND {_quote_identifier(column_map['ordem_servico'])} LIKE :ordem"
        params["ordem"] = f"%{ordem_servico}%"

    result = db.session.execute(text(sql), params).scalar()
    return int(result or 0)


def get_chamado(region: RegionalBoard, chamado_id: int) -> Optional[Dict[str, object]]:
    column_map = _available_column_map(region.table_name)
    if not column_map or "id" not in column_map:
        return None
    table = _quote_identifier(region.table_name)
    id_col = _quote_identifier(column_map["id"])
    sql = text(f"SELECT {_select_clause(column_map)} FROM {table} WHERE {id_col} = :id LIMIT 1")
    result = db.session.execute(sql, {"id": chamado_id}).first()
    if not result:
        return None
    return _row_to_dict(result, column_map.keys())


def create_chamado(region: RegionalBoard, payload: Dict[str, object]) -> Optional[int]:
    return _mutate_chamado(region, payload, insert=True)


def update_chamado(region: RegionalBoard, chamado_id: int, payload: Dict[str, object]) -> Optional[int]:
    payload = dict(payload)
    payload["id"] = chamado_id
    return _mutate_chamado(region, payload, insert=False)


def delete_chamado(region: RegionalBoard, chamado_id: int) -> None:
    column_map = _available_column_map(region.table_name)
    if not column_map or "id" not in column_map:
        return
    id_col = _quote_identifier(column_map["id"])
    sql = text(f"DELETE FROM {_quote_identifier(region.table_name)} WHERE {id_col} = :id")
    db.session.execute(sql, {"id": chamado_id})


def _enum_values(column_info: dict | None) -> list[str]:
    if not column_info:
        return []
    col_type = column_info.get("type")
    values = getattr(col_type, "enums", None)
    if values:
        return [str(v) for v in values]
    raw = str(col_type or "")
    return [v.replace("\\'", "'") for v in _ENUM_RE.findall(raw)]


def _column_length(column_info: dict | None) -> int | None:
    if not column_info:
        return None
    col_type = column_info.get("type")
    length = getattr(col_type, "length", None)
    try:
        return int(length) if length else None
    except Exception:
        return None


def _is_nullable(column_info: dict | None) -> bool:
    if not column_info:
        return True
    return bool(column_info.get("nullable", True))


def _clean_value(logical_key: str, value: object, column_info: dict | None = None) -> object:
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        if logical_key == "cnpj":
            # Guarda só os dígitos para não estourar CHAR/VARCHAR legado.
            digits = re.sub(r"\D+", "", value)
            value = digits or value
        if logical_key in _NUMERIC_COLUMNS:
            if value == "":
                return None
            try:
                return int(value)
            except ValueError:
                return None
        enum_values = _enum_values(column_info)
        if enum_values and value and value not in enum_values:
            # Não deixa um Select/valor antigo quebrar INSERT em coluna ENUM.
            return enum_values[0]
        if enum_values and not value:
            return None
        max_len = _column_length(column_info)
        if max_len and len(value) > max_len:
            value = value[:max_len]
        return value

    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value
    if isinstance(value, time):
        return value

    return value


def _default_for_column(logical: str, column_info: dict | None) -> object:
    enum_values = _enum_values(column_info)
    if logical == "tecnico":
        return enum_values[0] if enum_values else ""
    if logical == "contrato":
        # contrato é nullable no legado; não força se estiver vazio.
        return None
    default = INSERT_DEFAULTS.get(logical)
    if enum_values and default not in enum_values:
        return enum_values[0]
    return default


def _insert_payload_with_defaults(
    payload: Mapping[str, object],
    column_map: Mapping[str, str],
    info_by_actual: Mapping[str, dict],
) -> Dict[str, object]:
    prepared: Dict[str, object] = {}

    for logical, actual in column_map.items():
        if logical == "id" or logical in _GENERATED_OR_READONLY_COLUMNS:
            continue
        if logical not in payload:
            continue
        value = _clean_value(logical, payload.get(logical), info_by_actual.get(actual))
        if value is not None:
            prepared[logical] = value

    # Completa campos que o schema legado exige como NOT NULL sem default.
    for logical, actual in column_map.items():
        if logical == "id" or logical in _GENERATED_OR_READONLY_COLUMNS:
            continue
        if logical in prepared:
            continue
        info = info_by_actual.get(actual)
        has_server_default = info is not None and info.get("default") is not None
        if _is_nullable(info) or has_server_default:
            continue
        value = _default_for_column(logical, info)
        value = _clean_value(logical, value, info)
        if value is not None:
            prepared[logical] = value

    for logical in ("cliente", "ordem_servico"):
        if logical in column_map and logical not in prepared:
            actual = column_map[logical]
            value = _clean_value(logical, payload.get(logical), info_by_actual.get(actual))
            if value is not None:
                prepared[logical] = value

    return prepared


def _update_payload(
    payload: Mapping[str, object],
    column_map: Mapping[str, str],
    info_by_actual: Mapping[str, dict],
) -> Dict[str, object]:
    prepared: Dict[str, object] = {}
    for logical, actual in column_map.items():
        if logical == "id" or logical in _GENERATED_OR_READONLY_COLUMNS:
            continue
        if logical not in payload:
            continue
        value = _clean_value(logical, payload.get(logical), info_by_actual.get(actual))
        if value is not None:
            prepared[logical] = value
    return prepared


def _last_insert_id(result, table_name: str) -> Optional[int]:
    for attr in ("lastrowid", "inserted_primary_key"):
        value = getattr(result, attr, None)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        try:
            return int(value)
        except Exception:
            pass
    try:
        row = db.session.execute(text("SELECT LAST_INSERT_ID()")).first()
        if row and row[0]:
            return int(row[0])
    except Exception:
        db.session.rollback()
    return None


def _mutate_chamado(region: RegionalBoard, payload: Dict[str, object], *, insert: bool) -> Optional[int]:
    from flask import current_app

    if not _table_exists(region.table_name):
        current_app.logger.error("Tabela de chamados não encontrada: %s", region.table_name)
        return None

    column_map = _available_column_map(region.table_name)
    if not column_map:
        current_app.logger.error("Nenhuma coluna disponível para a tabela %s", region.table_name)
        return None

    info_by_actual = _column_info_map(region.table_name)
    table = _quote_identifier(region.table_name)
    chamado_id = payload.get("id")

    try:
        if insert:
            allowed = _insert_payload_with_defaults(payload, column_map, info_by_actual)
            if not allowed:
                current_app.logger.error(
                    "Tentativa de criar chamado sem campos válidos na tabela %s. Payload: %s",
                    region.table_name,
                    payload,
                )
                return None

            actual_columns = [column_map[logical] for logical in allowed.keys()]
            col_clause = ", ".join(_quote_identifier(column) for column in actual_columns)
            placeholders = ", ".join(f":{logical}" for logical in allowed.keys())
            sql = text(f"INSERT INTO {table} ({col_clause}) VALUES ({placeholders})")
            result = db.session.execute(sql, allowed)
            return _last_insert_id(result, region.table_name)

        if not chamado_id:
            current_app.logger.error(
                "Tentativa de atualizar chamado sem ID na tabela %s. Payload: %s",
                region.table_name,
                payload,
            )
            return None

        allowed = _update_payload(payload, column_map, info_by_actual)
        if not allowed:
            return int(chamado_id) if str(chamado_id).isdigit() else chamado_id  # type: ignore[return-value]

        set_clause = ", ".join(
            f"{_quote_identifier(column_map[logical])} = :{logical}"
            for logical in allowed.keys()
        )
        params = dict(allowed)
        params["id"] = chamado_id
        id_col = _quote_identifier(column_map.get("id", "id"))
        sql = text(f"UPDATE {table} SET {set_clause} WHERE {id_col} = :id")
        db.session.execute(sql, params)
        return int(chamado_id) if str(chamado_id).isdigit() else chamado_id  # type: ignore[return-value]

    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Erro ao %s chamado na tabela %s. Payload: %s",
            "criar" if insert else "atualizar",
            region.table_name,
            payload,
        )
        return None


def _serialize_value(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    return value


def _sanitize_mojibake(value: object) -> object:
    if value is None:
        return value
    if isinstance(value, str):
        if value == "":
            return value
        try:
            return value.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value
    if isinstance(value, (list, tuple)):
        fixed = [_sanitize_mojibake(item) for item in value]
        return type(value)(fixed)
    return value


def _row_to_dict(row: Row, columns: Iterable[str]) -> Dict[str, object]:
    data: Dict[str, object] = {}
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        for column in columns:
            if column in mapping:
                data[column] = _sanitize_mojibake(_serialize_value(mapping[column]))
        return data

    for column, value in zip(columns, row):
        data[column] = _sanitize_mojibake(_serialize_value(value))
    return data