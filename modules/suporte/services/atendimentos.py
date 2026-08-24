"""Camada de serviços para consultas e agregações de atendimentos."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from extensions import db

from ..forms import AtendimentoFilterForm
from ..models import AtendimentoSuporte

STATUS_VALUE_MAP = {
    "entrada": "Entrada",
    "atencao": "Atencao",
    "concluido": "Concluido",
}

STATUS_DISPLAY_MAP = {
    "entrada": "Entrada",
    "atencao": "Atenção",
    "concluido": "Concluído",
}

STATUS_ORDERING = {
    "entrada": (
        (func.date(AtendimentoSuporte.data_entrada) == func.current_date()).desc(),
        func.date(AtendimentoSuporte.data_entrada).asc(),
        AtendimentoSuporte.data_entrada.asc(),
    ),
    "atencao": (AtendimentoSuporte.data_entrada.asc(),),
    "concluido": (AtendimentoSuporte.data_atendimento.desc(),),
    "todos": (AtendimentoSuporte.data_entrada.desc(),),
}

DEFAULT_PAGE_SIZE = 15


def _base_filters(form: AtendimentoFilterForm):
    filters: List = []
    technician_id = form.technician_id()
    if technician_id:
        filters.append(AtendimentoSuporte.usuario_designado == technician_id)
    if form.data_entrada.data:
        filters.append(
            func.date(AtendimentoSuporte.data_entrada)
            == form.data_entrada.data
        )
    if form.os_entrada.data:
        filters.append(AtendimentoSuporte.os_entrada.ilike(f"%{form.os_entrada.data.strip()}%"))
    if form.empresa.data:
        filters.append(AtendimentoSuporte.cliente.ilike(f"%{form.empresa.data.strip()}%"))
    return filters


def _query_with_filters(form: AtendimentoFilterForm, include_status: bool = True):
    query = (
        AtendimentoSuporte.query.options(joinedload(AtendimentoSuporte.assigned_user))
        .order_by(None)
    )
    from flask import has_request_context, request
    if has_request_context():
        target_id = request.args.get("atendimento_id", type=int)
        if target_id:
            query = query.filter(AtendimentoSuporte.id == target_id)
            return query, "todos"

    filters = _base_filters(form)
    if filters:
        query = query.filter(*filters)

    status_key = (form.status.data or "entrada").lower()
    if include_status and status_key in STATUS_VALUE_MAP and status_key != "todos":
        query = query.filter(AtendimentoSuporte.status == STATUS_VALUE_MAP[status_key])
    return query, status_key


def fetch_paginated_atendimentos(
    form: AtendimentoFilterForm,
    page: int,
    per_page: int = DEFAULT_PAGE_SIZE,
):
    query, status_key = _query_with_filters(form, include_status=True)

    ordering = STATUS_ORDERING.get(status_key) or STATUS_ORDERING["todos"]
    query = query.order_by(*ordering)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    counters = summarize_status_counts(form)
    return pagination, counters, status_key


def summarize_status_counts(form: AtendimentoFilterForm) -> Dict[str, int]:
    query, _ = _query_with_filters(form, include_status=False)
    base_q = query.with_entities(AtendimentoSuporte.status)

    counts: Dict[str, int] = {key: 0 for key in STATUS_VALUE_MAP}
    counts["todos"] = base_q.count()

    for key, value in STATUS_VALUE_MAP.items():
        counts[key] = base_q.filter(AtendimentoSuporte.status == value).count()
    return counts
