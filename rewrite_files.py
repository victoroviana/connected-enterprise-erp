import os

def write_clean_file(path, content):
    print(f"Escrevendo {path}...")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

# Shared Agenda
shared_agenda_content = """\"\"\"Lógica compartilhada da Agenda Técnica para múltiplos blueprints.\"\"\"
from __future__ import annotations

from datetime import date, datetime
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    session,
)
from flask_login import current_user, login_required
import unicodedata

from extensions import db
from modules.propostas.models import AgendaEntry, User
from modules.propostas.blueprints.auth.permissions_utils import normalize_role_key, raw_permissions

def fix_encoding(text):
    \"\"\"Corrige problemas de encoding (UTF-8 interpretado como Latin-1).\"\"\"
    if not text:
        return text
    if not isinstance(text, str):
        return str(text)
    try:
        return text.encode('latin1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

def _technician_role_slugs() -> list[str]:
    raw = current_app.config.get(\"TECHNICIAN_ROLE_SLUGS\") or [\"tecnico\"]
    if isinstance(raw, str):
        raw = [value.strip().lower() for value in raw.split(\",\") if value.strip()]
    return [value.strip().lower() for value in raw if value]

def _dept_names(user=None) -> set[str]:
    actor = user or current_user
    names: set[str] = set()
    try:
        for name in getattr(actor, \"department_names\", []) or []:
            cleaned = (name or \"\").strip()
            if cleaned:
                normalized = unicodedata.normalize(\"NFKD\", cleaned)
                normalized = \"\".join(ch for ch in normalized if not unicodedata.combining(ch))
                names.add(normalized.upper())
    except Exception:
        return set()
    return names

def _unit_from_user() -> str | None:
    for dept in getattr(current_user, \"departments\", []) or []:
        if dept.unit and dept.unit.name:
            return dept.unit.name
    return None

def _parse_iso_date(val: str | None) -> date | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val).date()
    except ValueError:
        return None

def register_agenda_routes(bp: Blueprint):
    \"\"\"Registra as rotas da agenda no blueprint fornecido.\"\"\"
    
    @bp.route(\"/agenda\")
    @login_required
    def agenda_tecnica():
        return render_template(\"admin/agenda_tecnica.html\")

    @bp.route(\"/api/agenda\")
    @login_required
    def agenda_tecnica_api():
        start_str = request.args.get(\"start\")
        end_str = request.args.get(\"end\")
        start_dt = _parse_iso_date(start_str)
        end_dt = _parse_iso_date(end_str)

        query = AgendaEntry.query
        if start_dt:
            query = query.filter(AgendaEntry.start >= start_dt)
        if end_dt:
            query = query.filter(AgendaEntry.end <= end_dt)

        entries = query.all()
        results = []
        for e in entries:
            results.append({
                \"id\": e.id,
                \"title\": fix_encoding(e.title),
                \"start\": e.start.isoformat() if e.start else None,
                \"end\": e.end.isoformat() if e.end else None,
                \"description\": fix_encoding(e.description),
                \"color\": e.color,
                \"allDay\": e.all_day,
                \"extendedProps\": {
                    \"tecnico\": fix_encoding(e.tecnico),
                    \"unidade\": fix_encoding(e.unidade),
                    \"departamento\": fix_encoding(e.departamento),
                }
            })
        return jsonify(results)

    @bp.route(\"/api/agenda/criar\", methods=[\"POST\"])
    @login_required
    def criar_agendamento():
        data = request.json
        try:
            entry = AgendaEntry(
                title=data.get(\"title\"),
                start=datetime.fromisoformat(data.get(\"start\")),
                end=datetime.fromisoformat(data.get(\"end\")),
                description=data.get(\"description\"),
                tecnico=data.get(\"tecnico\"),
                unidade=data.get(\"unidade\") or _unit_from_user(),
                departamento=data.get(\"departamento\") or \"SUPORTE\",
                color=data.get(\"color\", \"#3788d8\"),
                all_day=data.get(\"allDay\", False),
                user_id=current_user.id
            )
            db.session.add(entry)
            db.session.commit()
            return jsonify({\"ok\": True, \"id\": entry.id})
        except Exception as e:
            db.session.rollback()
            return jsonify({\"ok\": False, \"message\": str(e)}), 500

    @bp.route(\"/api/agenda/<int:entry_id>/atualizar\", methods=[\"POST\"])
    @login_required
    def atualizar_agendamento(entry_id):
        entry = AgendaEntry.query.get_or_404(entry_id)
        data = request.json
        try:
            if \"title\" in data: entry.title = data[\"title\"]
            if \"start\" in data: entry.start = datetime.fromisoformat(data[\"start\"])
            if \"end\" in data: entry.end = datetime.fromisoformat(data[\"end\"])
            if \"description\" in data: entry.description = data[\"description\"]
            if \"tecnico\" in data: entry.tecnico = data[\"tecnico\"]
            if \"color\" in data: entry.color = data[\"color\"]
            db.session.commit()
            return jsonify({\"ok\": True})
        except Exception as e:
            db.session.rollback()
            return jsonify({\"ok\": False, \"message\": str(e)}), 500

    @bp.route(\"/api/agenda/<int:entry_id>/excluir\", methods=[\"POST\"])
    @login_required
    def excluir_agendamento(entry_id):
        entry = AgendaEntry.query.get_or_404(entry_id)
        try:
            db.session.delete(entry)
            db.session.commit()
            return jsonify({\"ok\": True})
        except Exception as e:
            db.session.rollback()
            return jsonify({\"ok\": False, \"message\": str(e)}), 500
"""

write_clean_file(r'c:\Users\User\Desktop\sollus_connected\modules\suporte\blueprints\shared_agenda.py', shared_agenda_content)
