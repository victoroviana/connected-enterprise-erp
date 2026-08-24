"""Automatic SQLAlchemy listeners to capture audit events."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, List, Optional
from uuid import UUID

from flask import has_request_context
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from extensions import db
from modules.audit.utils import write_audit

LOGGER = logging.getLogger(__name__)
_SESSION_KEY = "__audit_pending_entries__"
_SQL_DML_RE = re.compile(r"^\s*(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+`?([\\w.]+)`?", re.IGNORECASE)


def _should_track(obj: Any) -> bool:
    if obj is None:
        return False
    cls = obj.__class__
    if getattr(cls, "__audit_exclude__", False):
        return False
    tablename = getattr(cls, "__tablename__", "")
    if tablename == "audit_logs":
        return False
    try:
        inspect(obj)
    except Exception:
        return False
    return True


def _coerce(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.hex()
    if isinstance(value, (set, tuple)):
        return list(value)
    return value


def _excluded_fields(obj: Any) -> set[str]:
    excluded = getattr(obj.__class__, "__audit_exclude_fields__", None)
    if not excluded:
        return set()
    return set(excluded)


def _serialize_instance(obj: Any, only_keys: Optional[Iterable[str]] = None) -> Optional[dict[str, Any]]:
    if obj is None:
        return None
    if hasattr(obj, "to_audit_dict"):
        try:
            payload = obj.to_audit_dict()
            if isinstance(payload, dict):
                return payload
        except Exception:
            LOGGER.debug("Failed to build custom audit payload for %s", obj, exc_info=True)
    try:
        mapper = inspect(obj).mapper
    except Exception:
        return None
    excluded = _excluded_fields(obj)
    available = {column.key for column in mapper.columns}
    if only_keys is None:
        keys: Iterable[str] = [column.key for column in mapper.columns]
    else:
        keys = only_keys
    data: dict[str, Any] = {}
    for key in keys:
        if key in excluded or key not in available:
            continue
        try:
            value = getattr(obj, key)
        except AttributeError:
            continue
        data[key] = _coerce(value)
    return data


def _coerce_params(params: Any) -> Any:
    if params is None:
        return None
    if isinstance(params, dict):
        return {key: _coerce(value) for key, value in params.items()}
    if isinstance(params, (list, tuple)):
        return [_coerce_params(item) for item in params]
    return _coerce(params)


def _parse_dml(statement: str) -> tuple[Optional[str], Optional[str]]:
    match = _SQL_DML_RE.match(statement or "")
    if not match:
        return None, None
    verb = (match.group(1) or "").strip().upper()
    table = (match.group(2) or "").strip()
    if verb.startswith("INSERT"):
        action = "sql_insert"
    elif verb.startswith("UPDATE"):
        action = "sql_update"
    elif verb.startswith("DELETE"):
        action = "sql_delete"
    else:
        action = None
    return action, table or None


def _capture_before_update(obj: Any) -> tuple[dict[str, Any], List[str]]:
    state = inspect(obj)
    before: dict[str, Any] = {}
    changed: List[str] = []
    excluded = _excluded_fields(obj)
    for attr in state.mapper.column_attrs:
        key = attr.key
        if key in excluded:
            continue
        hist = state.attrs[key].history
        if not hist.has_changes():
            continue
        old_value = hist.deleted[0] if hist.deleted else None
        before[key] = _coerce(old_value)
        changed.append(key)
    return before, changed


def _entity_id(obj: Any) -> Any:
    def _sanitize(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            return _sanitize(value[0] if value else None)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value) if value.isdigit() else None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    try:
        state = inspect(obj)
    except Exception:
        return _sanitize(getattr(obj, "id", None))
    if state.identity:
        if len(state.identity) == 1:
            return _sanitize(state.identity[0])
        return _sanitize(state.identity)
    return _sanitize(getattr(obj, "id", None))


def _pending_entries(session: Session) -> list[dict[str, Any]]:
    pending = session.info.get(_SESSION_KEY)


def _capture_before_update(obj: Any) -> tuple[dict[str, Any], List[str]]:
    state = inspect(obj)
    before: dict[str, Any] = {}
    changed: List[str] = []
    excluded = _excluded_fields(obj)
    for attr in state.mapper.column_attrs:
        key = attr.key
        if key in excluded:
            continue
        hist = state.attrs[key].history
        if not hist.has_changes():
            continue
        old_value = hist.deleted[0] if hist.deleted else None
        before[key] = _coerce(old_value)
        changed.append(key)
    return before, changed


def _entity_id(obj: Any) -> Any:
    def _sanitize(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            return _sanitize(value[0] if value else None)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value) if value.isdigit() else None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    try:
        state = inspect(obj)
    except Exception:
        return _sanitize(getattr(obj, "id", None))
    if state.identity:
        if len(state.identity) == 1:
            return _sanitize(state.identity[0])
        return _sanitize(state.identity)
    return _sanitize(getattr(obj, "id", None))


def _pending_entries(session: Session) -> list[dict[str, Any]]:
    pending = session.info.get(_SESSION_KEY)
    if pending is None:
        pending = []
        session.info[_SESSION_KEY] = pending
    return pending


@event.listens_for(db.session, "before_flush")
def _gather_audit_changes(session: Session, flush_context, instances):  # type: ignore[override]
    from flask import current_app
    if not has_request_context() or current_app.config.get("TESTING"):
        return
    pending = _pending_entries(session)
    pending.clear()

    new_objects = list(session.new)
    deleted_objects = list(session.deleted)
    dirty_objects = [obj for obj in session.dirty if obj not in new_objects and obj not in deleted_objects]

    for obj in new_objects:
        if not _should_track(obj):
            continue
        pending.append(
            {
                "action": "create",
                "entity_type": obj.__class__.__name__,
                "obj": obj,
                "entity_id": None,
                "before": None,
                "changed_keys": None,
            }
        )

    for obj in dirty_objects:
        if not _should_track(obj):
            continue
        if not session.is_modified(obj, include_collections=False):
            continue
        before, changed_keys = _capture_before_update(obj)
        if not changed_keys:
            continue
        pending.append(
            {
                "action": "update",
                "entity_type": obj.__class__.__name__,
                "obj": obj,
                "entity_id": _entity_id(obj),
                "before": before,
                "changed_keys": changed_keys,
            }
        )

    for obj in deleted_objects:
        if not _should_track(obj):
            continue
        pending.append(
            {
                "action": "delete",
                "entity_type": obj.__class__.__name__,
                "obj": None,
                "entity_id": _entity_id(obj),
                "before": _serialize_instance(obj),
                "changed_keys": None,
            }
        )


@event.listens_for(db.session, "after_flush")
def _flush_audit_logs(session: Session, flush_context):  # type: ignore[override]
    from flask import current_app
    if not has_request_context() or current_app.config.get("TESTING"):
        return
    pending = session.info.pop(_SESSION_KEY, None)
    if not pending:
        return

    for entry in pending:
        obj = entry.get("obj")
        entity_id = entry.get("entity_id")
        if entity_id is None and obj is not None:
            entity_id = _entity_id(obj)
        action = entry["action"]
        after_payload: Optional[dict[str, Any]] = None
        if action == "create":
            after_payload = _serialize_instance(obj)
        elif action == "update":
            changed_keys = entry.get("changed_keys") or []
            after_payload = _serialize_instance(obj, changed_keys)
        before_payload = entry.get("before")

        if action in {"create", "update"} and not after_payload:
            continue
        if action == "update" and not before_payload:
            continue

        try:
            write_audit(
                entity_type=entry["entity_type"],
                entity_id=entity_id,
                action=action,
                before=before_payload,
                after=after_payload,
            )
        except Exception:
            LOGGER.exception("Failed to auto-log audit event for %s", entry["entity_type"])


@event.listens_for(db.session, "do_orm_execute")
def _audit_text_dml(execute_state):  # type: ignore[override]
    from flask import current_app
    if not has_request_context() or current_app.config.get("TESTING"):
        return
    if getattr(execute_state, "is_select", False):
        return
    if getattr(execute_state, "is_column_load", False) or getattr(execute_state, "is_relationship_load", False):
        return
    statement = execute_state.statement
    sql_text = str(statement).strip() if statement is not None else ""
    action, table = _parse_dml(sql_text)
    if not action:
        return
    if table and table.lower() == "audit_logs":
        return
    params = _coerce_params(getattr(execute_state, "parameters", None))
    payload = {"sql": sql_text, "params": params}
    message = f"Execucao SQL ({action}){f' em {table}' if table else ''}"
    try:
        write_audit(
            entity_type=table or "sql",
            action=action,
            message=message,
            after=payload,
        )
    except Exception:
        LOGGER.exception("Failed to auto-log SQL statement audit.")
