"""Google Calendar integration to create Meet links for support entries."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from typing import Iterable, Tuple

from flask import current_app

from modules.audit.utils import write_audit_external

try:
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except Exception:  # pragma: no cover - optional dependency
    service_account = None
    Credentials = None
    Request = None
    build = None


SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _config_value(name: str, default: str | None = None) -> str | None:
    return current_app.config.get(name) or os.getenv(name) or default


def _get_service_credentials():
    if service_account is None:
        return None
    file_path = _config_value("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not file_path:
        return None
    creds = service_account.Credentials.from_service_account_file(
        file_path, scopes=SCOPES
    )
    delegated_user = _config_value("GOOGLE_DELEGATED_USER")
    if delegated_user:
        creds = creds.with_subject(delegated_user)
    return creds


def _get_oauth_credentials():
    if Credentials is None or Request is None:
        return None
    refresh_token = _config_value("GOOGLE_OAUTH_REFRESH_TOKEN")
    client_id = _config_value("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = _config_value("GOOGLE_OAUTH_CLIENT_SECRET")
    if not (refresh_token and client_id and client_secret):
        return None
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=_config_value(
            "GOOGLE_OAUTH_TOKEN_URI", "https://oauth2.googleapis.com/token"
        ),
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except Exception:
        try:
            current_app.logger.exception("Falha ao atualizar token OAuth do Google Meet.")
        except Exception:
            pass
        return None
    return creds


def _get_credentials():
    oauth_creds = _get_oauth_credentials()
    if oauth_creds:
        return oauth_creds
    return _get_service_credentials()


def meet_config_status() -> dict:
    if build is None:
        return {"ok": False, "reason": "missing_client"}
    calendar_id = _config_value("GOOGLE_CALENDAR_ID") or _config_value("GOOGLE_DELEGATED_USER")

    refresh_token = _config_value("GOOGLE_OAUTH_REFRESH_TOKEN")
    client_id = _config_value("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = _config_value("GOOGLE_OAUTH_CLIENT_SECRET")
    has_oauth_env = bool(refresh_token and client_id and client_secret)
    service_file = _config_value("GOOGLE_SERVICE_ACCOUNT_FILE")

    if has_oauth_env:
        creds = _get_oauth_credentials()
        if not creds:
            return {"ok": False, "reason": "refresh_failed"}
    elif service_file:
        if not os.path.isfile(service_file):
            return {"ok": False, "reason": "service_file_missing"}
        creds = _get_service_credentials()
        if not creds:
            return {"ok": False, "reason": "service_account_invalid"}
    else:
        return {"ok": False, "reason": "missing_credentials"}
    if not calendar_id:
        return {"ok": False, "reason": "missing_calendar"}
    return {"ok": True}


def _extract_meet_link(payload: dict) -> str | None:
    link = payload.get("hangoutLink")
    if link:
        return link
    entry_points = payload.get("conferenceData", {}).get("entryPoints", []) or []
    for entry in entry_points:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return entry["uri"]
    return None


def create_meet_event(
    *,
    summary: str,
    description: str,
    start_dt: datetime,
    duration_minutes: int,
    attendees: Iterable[str] | None = None,
    calendar_id: str | None = None,
    time_zone: str | None = None,
    send_updates: bool = True,
) -> Tuple[str | None, str | None]:
    if build is None:
        try:
            write_audit_external(
                entity_type="suporte_meet",
                action="meet_skip",
                message="Criação de Meet ignorada: cliente Google API indisponível.",
                after={"status": "no_client"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar criação de Meet (cliente indisponível).")
        return None, None
    creds = _get_credentials()
    calendar_id = calendar_id or _config_value("GOOGLE_CALENDAR_ID") or _config_value(
        "GOOGLE_DELEGATED_USER"
    )
    time_zone = time_zone or _config_value(
        "GOOGLE_MEET_TIMEZONE", "America/Sao_Paulo"
    )
    if not creds or not calendar_id:
        try:
            write_audit_external(
                entity_type="suporte_meet",
                action="meet_skip",
                message="Criação de Meet ignorada: credenciais ou calendário ausentes.",
                after={
                    "status": "missing_credentials",
                    "has_credentials": bool(creds),
                    "has_calendar_id": bool(calendar_id),
                },
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar criação de Meet (credenciais ausentes).")
        return None, None

    end_dt = start_dt + timedelta(minutes=duration_minutes)
    attendee_list = [email for email in (attendees or []) if email]
    event_body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": time_zone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": time_zone},
        "conferenceData": {
            "createRequest": {
                "requestId": uuid.uuid4().hex,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    if attendee_list:
        event_body["attendees"] = [{"email": email} for email in attendee_list]

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    request = service.events().insert(
        calendarId=calendar_id,
        body=event_body,
        conferenceDataVersion=1,
        sendUpdates="all" if (send_updates and attendee_list) else "none",
    )
    try:
        response = request.execute()
    except Exception:
        current_app.logger.exception("Falha ao criar evento de Meet")
        try:
            write_audit_external(
                entity_type="suporte_meet",
                action="meet_error",
                message="Falha ao criar evento de Meet.",
                after={"status": "error", "attendees": attendee_list},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar erro na criação do Meet.")
        raise

    meet_link = _extract_meet_link(response)
    event_id = response.get("id")
    try:
        write_audit_external(
            entity_type="suporte_meet",
            action="meet_create",
            message="Evento de Meet criado.",
            after={
                "status": "success",
                "event_id": event_id,
                "meet_link": meet_link,
                "attendees": attendee_list,
            },
        )
    except Exception:
        current_app.logger.exception("Falha ao auditar criação de Meet.")
    return meet_link, event_id


def update_meet_event(
    *,
    event_id: str,
    attendees: Iterable[str] | None = None,
    calendar_id: str | None = None,
    send_updates: bool = True,
) -> bool:
    if build is None:
        try:
            write_audit_external(
                entity_type="suporte_meet",
                action="meet_skip",
                message="Atualização de Meet ignorada: cliente Google API indisponível.",
                after={"status": "no_client"},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar atualização de Meet (cliente indisponível).")
        return False
    creds = _get_credentials()
    calendar_id = calendar_id or _config_value("GOOGLE_CALENDAR_ID") or _config_value(
        "GOOGLE_DELEGATED_USER"
    )
    if not creds or not calendar_id:
        try:
            write_audit_external(
                entity_type="suporte_meet",
                action="meet_skip",
                message="Atualização de Meet ignorada: credenciais ou calendário ausentes.",
                after={
                    "status": "missing_credentials",
                    "has_credentials": bool(creds),
                    "has_calendar_id": bool(calendar_id),
                },
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar atualização de Meet (credenciais ausentes).")
        return False
    attendee_list = [email for email in (attendees or []) if email]
    if not attendee_list:
        try:
            write_audit_external(
                entity_type="suporte_meet",
                action="meet_skip",
                message="Atualização de Meet ignorada: sem participantes.",
                after={"status": "no_attendees", "event_id": event_id},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar atualização de Meet (sem participantes).")
        return False
    event_body = {"attendees": [{"email": email} for email in attendee_list]}
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    request = service.events().patch(
        calendarId=calendar_id,
        eventId=event_id,
        body=event_body,
        sendUpdates="all" if (send_updates and attendee_list) else "none",
    )
    try:
        request.execute()
    except Exception:
        current_app.logger.exception("Falha ao atualizar evento de Meet")
        try:
            write_audit_external(
                entity_type="suporte_meet",
                action="meet_error",
                message="Falha ao atualizar evento de Meet.",
                after={"status": "error", "event_id": event_id, "attendees": attendee_list},
            )
        except Exception:
            current_app.logger.exception("Falha ao auditar erro na atualizacao do Meet.")
        raise
    try:
        write_audit_external(
            entity_type="suporte_meet",
            action="meet_update",
            message="Evento de Meet atualizado.",
            after={"status": "success", "event_id": event_id, "attendees": attendee_list},
        )
    except Exception:
        current_app.logger.exception("Falha ao auditar atualizacao do Meet.")
    return True
