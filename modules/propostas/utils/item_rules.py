from __future__ import annotations

import unicodedata
from typing import Any


def normalize_item_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def is_one_time_acquisition_item(*values: Any) -> bool:
    text = " ".join(normalize_item_text(value) for value in values if value)
    if not text:
        return False
    one_time_terms = (
        "instala",
        "instalacao",
        "instalacoes",
        "fixa",
        "fixacao",
        "fixacoes",
        "bobina",
        "bobinas",
        "cracha",
        "crachas",
        "comanda",
        "comandas",
        "cartao",
        "cartoes",
        "fita",
        "fitas",
        "pinhao",
        "pinhaes",
        "porta cartao",
        "porta cartoes",
        "bateria",
        "baterias",
        "fecho",
        "fechos",
        "botoeira",
        "botoeiras",
        "fonte",
        "fontes",
        "chave",
        "chaves",
        "receptor",
        "receptores",
        "modem",
        "modens",
    )
    return any(term in text for term in one_time_terms)
