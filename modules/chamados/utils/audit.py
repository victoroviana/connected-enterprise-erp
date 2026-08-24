from __future__ import annotations
import json
from typing import Any, Optional
from flask import has_request_context, request
from flask_login import current_user, AnonymousUserMixin
from extensions import db
from modules.chamados.models import AuditLog

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

def _actor():
    try:
        if isinstance(current_user, AnonymousUserMixin) or not getattr(current_user, "is_authenticated", False):
            return None, None, None
        return getattr(current_user, "id", None), getattr(current_user, "email", None), getattr(current_user, "name", None) or getattr(current_user, "username", None)
    except Exception:
        return None, None, None

def write_audit(
    entity_type: str,
    action: str,
    message: Optional[str] = None,
    *,
    entity_id: Optional[int] = None,
    before: Any = None,
    after: Any = None,
    commit: bool = False,
):
    """Grava uma linha em audit_logs. Por padrão não faz commit."""
    aid, aem, anm = _actor()
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

    row = AuditLog(
        actor_id=aid, actor_email=aem, actor_name=anm,
        ip=ip, ua=ua,
        entity_type=entity_type, entity_id=entity_id,
        action=action, message=message or "",
        before=_json_dump(before), after=_json_dump(after),
    )
    db.session.add(row)
    if commit:
        db.session.commit()
    return row

