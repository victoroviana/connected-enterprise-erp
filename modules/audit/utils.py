"""Shared helpers to persist audit events from any module.

Versão tolerante para bancos legados: se a tabela audit_logs ainda não existir
ou estiver incompleta, a auditoria é ignorada sem quebrar o fluxo principal.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from flask import current_app, has_app_context, has_request_context, request
from flask_login import AnonymousUserMixin, current_user
from sqlalchemy import inspect

from extensions import db
from .models import AuditLog


_AUDIT_TABLE_CACHE_KEY = "_audit_logs_table_available"
_REQUIRED_AUDIT_COLUMNS = {
    "id",
    "created_at",
    "actor_id",
    "actor_email",
    "actor_name",
    "ip",
    "ua",
    "entity_type",
    "entity_id",
    "action",
    "message",
    "before",
    "after",
}


def _json_dump(val: Any) -> Optional[str]:
    if val is None:
        return None
    try:
        return json.dumps(val, ensure_ascii=False, default=str)
    except Exception:
        try:
            return json.dumps(str(val), ensure_ascii=False, default=str)
        except Exception:
            return None


def _actor() -> tuple[Optional[int], Optional[str], Optional[str]]:
    try:
        if isinstance(current_user, AnonymousUserMixin) or not getattr(current_user, "is_authenticated", False):
            return None, None, None
        return (
            getattr(current_user, "id", None),
            getattr(current_user, "email", None),
            getattr(current_user, "name", None)
            or getattr(current_user, "username", None)
            or getattr(current_user, "nome_completo", None),
        )
    except Exception:
        return None, None, None


def _normalize_entity_id(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        return int(text) if text.isdigit() else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _audit_table_available() -> bool:
    """Return True only when audit_logs exists with the expected columns.

    O sistema de chamados usa tabelas legadas. Em algumas bases, a tabela
    audit_logs ainda não existe. Antes desta proteção, qualquer INSERT/UPDATE
    podia adicionar um AuditLog na sessão e o erro só aparecia no commit,
    derrubando a rota com 500.
    """
    if not has_app_context():
        return False

    cached = current_app.config.get(_AUDIT_TABLE_CACHE_KEY)
    if cached is not None:
        return bool(cached)

    try:
        inspector = inspect(db.engine)
        if not inspector.has_table("audit_logs"):
            current_app.config[_AUDIT_TABLE_CACHE_KEY] = False
            return False

        columns = {str(column.get("name")) for column in inspector.get_columns("audit_logs")}
        missing = _REQUIRED_AUDIT_COLUMNS - columns
        if missing:
            current_app.logger.warning(
                "Tabela audit_logs encontrada, mas faltam colunas: %s. Auditoria desativada.",
                ", ".join(sorted(missing)),
            )
            current_app.config[_AUDIT_TABLE_CACHE_KEY] = False
            return False

        current_app.config[_AUDIT_TABLE_CACHE_KEY] = True
        return True
    except Exception:
        try:
            current_app.logger.exception("Não foi possível validar a tabela audit_logs. Auditoria desativada.")
        except Exception:
            pass
        current_app.config[_AUDIT_TABLE_CACHE_KEY] = False
        return False


def reset_audit_table_cache() -> None:
    """Permite revalidar audit_logs após uma migração, se necessário."""
    if has_app_context():
        current_app.config.pop(_AUDIT_TABLE_CACHE_KEY, None)


def write_audit(
    *,
    entity_type: str,
    action: str,
    message: Optional[str] = None,
    entity_id: Optional[int] = None,
    before: Any = None,
    after: Any = None,
    extra: Optional[dict[str, Any]] = None,
    commit: bool = False,
) -> Optional[AuditLog]:
    """Persist a single audit row. Does not commit unless asked.

    Se a tabela audit_logs não existir, retorna None e não altera a sessão.
    Isso impede erro 500 em fluxos principais, como criar chamados.
    """

    if not _audit_table_available():
        return None

    actor_id, actor_email, actor_name = _actor()
    if has_request_context():
        try:
            ip = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or request.remote_addr
        except Exception:
            ip = None
        try:
            ua = request.headers.get("User-Agent")
        except Exception:
            ua = None
    else:
        ip = None
        ua = None

    payload_before = _json_dump(before)
    payload_after = _json_dump(after)
    normalized_entity_id = _normalize_entity_id(entity_id)

    row = AuditLog(
        actor_id=actor_id,
        actor_email=actor_email,
        actor_name=actor_name,
        ip=ip,
        ua=ua,
        entity_type=entity_type,
        entity_id=normalized_entity_id,
        action=action,
        message=message or "",
        before=payload_before,
        after=payload_after,
    )
    if extra:
        for key, value in extra.items():
            if hasattr(row, key):
                setattr(row, key, value)

    try:
        db.session.add(row)
        if commit:
            db.session.commit()
        return row
    except Exception:
        db.session.rollback()
        try:
            current_app.logger.exception("Falha ao gravar auditoria. Fluxo principal preservado.")
        except Exception:
            pass
        return None


def write_audit_external(
    *,
    entity_type: str,
    action: str,
    message: Optional[str] = None,
    entity_id: Optional[int] = None,
    before: Any = None,
    after: Any = None,
    extra: Optional[dict[str, Any]] = None,
) -> Optional[AuditLog]:
    """Persist an audit row for side-effects outside the DB.

    Commits the audit log only when the session was clean before adding it.
    """
    if not _audit_table_available():
        return None

    should_commit = not db.session.new and not db.session.dirty and not db.session.deleted
    row = write_audit(
        entity_type=entity_type,
        action=action,
        message=message,
        entity_id=entity_id,
        before=before,
        after=after,
        extra=extra,
        commit=False,
    )
    if should_commit and row is not None:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            try:
                current_app.logger.exception("Falha ao confirmar auditoria externa.")
            except Exception:
                pass
    return row
