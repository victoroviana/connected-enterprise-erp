"""Registro de alterações para atendimentos de suporte."""
from __future__ import annotations

from typing import Iterable, Mapping

from flask_login import current_user

from extensions import db
from ..models import AtendimentoSuporteLog


def log_changes(entry_id: int, before: Mapping[str, object], after: Mapping[str, object], fields: Iterable[str]) -> None:
    actor = getattr(current_user, "nome_completo", None) or getattr(current_user, "email", None) or "Sistema"
    for field in fields:
        old_value = before.get(field)
        new_value = after.get(field)
        if old_value == new_value:
            continue
        log = AtendimentoSuporteLog(
            atendimento_suporte_id=entry_id,
            campo=field,
            valor_antigo=str(old_value) if old_value is not None else None,
            valor_novo=str(new_value) if new_value is not None else None,
            modificado_por=actor,
        )
        db.session.add(log)
    db.session.flush()
