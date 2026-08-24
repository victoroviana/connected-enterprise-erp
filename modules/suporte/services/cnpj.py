"""Integração simples com a API pública da Receita.

A versão antiga consumia diretamente o endpoint do Receita WS.
Mantemos essa abordagem para preencher o cadastro de empresas
quando um CNPJ é digitado no formulário de suporte.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict

import requests
from flask import current_app

from extensions import db
from sqlalchemy import inspect, text
from ..models import Empresa

_CNPJ_RE = re.compile(r"\d+")


class ReceitaAPIError(RuntimeError):
    pass


def normalize_cnpj(value: str | None) -> str:
    if not value:
        return ""
    digits = "".join(_CNPJ_RE.findall(value))
    return digits[:14]


def fetch_receita_data(cnpj: str) -> Dict[str, Any]:
    """Consulta a API da Receita e retorna os dados relevantes."""
    clean = normalize_cnpj(cnpj)
    if len(clean) != 14:
        raise ReceitaAPIError("CNPJ inválido")

    base_url = current_app.config.get(
        "SUPPORT_RECEITA_URL",
        "https://www.receitaws.com.br/v1/cnpj/{cnpj}",
    )
    url = base_url.format(cnpj=clean)
    headers = {"Accept": "application/json"}
    timeout = current_app.config.get("SUPPORT_RECEITA_TIMEOUT", 15)

    response = requests.get(url, headers=headers, timeout=timeout)
    if response.status_code != 200:
        raise ReceitaAPIError(
            f"Erro ao consultar ReceitaWS ({response.status_code})"
        )

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise ReceitaAPIError("Resposta inválida da ReceitaWS") from exc

    if payload.get("status") == "ERROR":
        message = payload.get("message") or payload.get("motivo") or "Erro desconhecido"
        raise ReceitaAPIError(message)

    return {
        "cnpj": clean,
        "razao_social": payload.get("nome"),
        "nome_fantasia": payload.get("fantasia"),
        "email": payload.get("email"),
        "observacoes": payload.get("observacoes"),
        "observacoes_alerta": payload.get("observacoesAlerta"),
    }


def upsert_empresa_from_receita(cnpj: str, data: Dict[str, Any]) -> Empresa:
    """Atualiza ou cria o registro de empresa com os dados retornados."""
    clean = normalize_cnpj(cnpj)
    empresa = Empresa.query.filter_by(cnpj=clean).first()
    if not empresa:
        empresa = Empresa(cnpj=clean)
        db.session.add(empresa)

    empresa.cliente = data.get("nome") or data.get("razao_social") or data.get("cliente") or data.get("fantasia") or data.get("nome_fantasia") or empresa.cliente or f"Empresa {clean}"
    if hasattr(empresa, "nome_fantasia"):
        setattr(empresa, "nome_fantasia", data.get("fantasia") or data.get("nome_fantasia") or getattr(empresa, "nome_fantasia", None))
    empresa.observacoes = data.get("observacoes") or empresa.observacoes
    empresa.observacoes_alerta = data.get("observacoes_alerta") or empresa.observacoes_alerta
    db.session.flush()
    return empresa


def ensure_empresa_record(cnpj: str | None, cliente: str | None) -> None:
    if not cnpj or not cliente:
        return
    try:
        inspector = inspect(db.engine)
        if not inspector.has_table("empresa"):
            return
    except Exception:
        return
    try:
        existing = db.session.execute(
            text("SELECT 1 FROM empresa WHERE cnpj = :cnpj LIMIT 1"),
            {"cnpj": cnpj},
        ).first()
        if existing:
            return
        db.session.execute(
            text("INSERT INTO empresa (cliente, cnpj) VALUES (:cliente, :cnpj)"),
            {"cliente": cliente, "cnpj": cnpj},
        )
    except Exception:
        current_app.logger.exception("Falha ao inserir empresa vinculada.")

