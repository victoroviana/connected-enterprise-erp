"""Importer from the legacy osTicket database into Sollus Tickets tables."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pymysql
from pymysql.cursors import DictCursor
from flask import current_app
from werkzeug.utils import secure_filename

from extensions import db
from modules.propostas.models import User

from .models import (
    SollusTicket,
    SollusTicketAttachment,
    SollusTicketCustomQueueColumn,
    SollusTicketCustomQueueSort,
    SollusTicketContact,
    SollusTicketDepartmentAccess,
    SollusTicketDepartment,
    SollusTicketEmailTemplate,
    SollusTicketEmailTemplateGroup,
    SollusTicketFilterRule,
    SollusTicketImportRun,
    SollusTicketMailbox,
    SollusTicketPriority,
    SollusTicketQueue,
    SollusTicketSLA,
    SollusTicketStatus,
    SollusTicketTask,
    SollusTicketTeam,
    SollusTicketTeamMember,
    SollusTicketThreadEntry,
    SollusTicketTopic,
    SollusTicketCannedResponse,
)
from .services import (
    bulk_add_events,
    ensure_sollus_ticket_tables,
    normalize_osticket_priority,
    normalize_osticket_status,
    slugify,
)


@dataclass(frozen=True)
class OsticketConfig:
    host: str
    database: str
    user: str
    password: str
    prefix: str = "ost_"
    port: int = 3306


def parse_ost_config(path: str | Path) -> OsticketConfig:
    content = Path(path).read_text(encoding="utf-8", errors="ignore")

    def get_define(name: str, default: str = "") -> str:
        pattern = rf"define\(\s*['\"]{re.escape(name)}['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)"
        match = re.search(pattern, content)
        return match.group(1) if match else default

    return OsticketConfig(
        host=get_define("DBHOST", "localhost"),
        database=get_define("DBNAME"),
        user=get_define("DBUSER"),
        password=get_define("DBPASS"),
        prefix=get_define("TABLE_PREFIX", "ost_"),
    )


def import_osticket(
    config: OsticketConfig,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    batch_size: int = 100,
) -> dict[str, int]:
    ensure_sollus_ticket_tables()
    run = SollusTicketImportRun(source="osticket", status="running")
    db.session.add(run)
    db.session.commit()

    stats = {
        "departments": 0,
        "statuses": 0,
        "priorities": 0,
        "teams": 0,
        "queues": 0,
        "slas": 0,
        "topics": 0,
        "contacts": 0,
        "tickets": 0,
        "entries": 0,
        "events": 0,
        "filter_rules": 0,
        "template_groups": 0,
        "templates": 0,
        "queue_columns": 0,
        "queue_sorts": 0,
        "team_members": 0,
        "department_access": 0,
        "tasks": 0,
        "canned_responses": 0,
        "attachments": 0,
        "skipped_attachments": 0,
        "skipped_tickets": 0,
    }

    connection = None
    try:
        connection = pymysql.connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            database=config.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
        )
        with connection.cursor() as cursor:
            _import_departments(cursor, config.prefix, stats)
            _import_statuses(cursor, config.prefix, stats)
            _import_priorities(cursor, config.prefix, stats)
            _import_teams(cursor, config.prefix, stats)
            _import_slas(cursor, config.prefix, stats)
            _import_queues(cursor, config.prefix, stats)
            _import_topics(cursor, config.prefix, stats)
            _import_contacts(cursor, config.prefix, stats)
            _import_team_members(cursor, config.prefix, stats)
            _import_department_access(cursor, config.prefix, stats)
            _import_filter_rules(cursor, config.prefix, stats)
            _import_email_templates(cursor, config.prefix, stats)
            _import_canned_responses(cursor, config.prefix, stats)
            _link_department_template_groups(cursor, config.prefix)
            _import_queue_customizations(cursor, config.prefix, stats)
            _import_tasks(cursor, config.prefix, stats)
            if not dry_run:
                db.session.commit()
            if limit != 0:
                _import_tickets(cursor, config.prefix, stats, limit=limit, batch_size=batch_size, dry_run=dry_run)
        run.status = "dry_run" if dry_run else "done"
        run.summary = json.dumps(stats, ensure_ascii=False)
        run.finished_at = datetime.utcnow()
        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()
        return stats
    except Exception as exc:
        db.session.rollback()
        run.status = "failed"
        run.summary = str(exc)
        run.finished_at = datetime.utcnow()
        db.session.add(run)
        db.session.commit()
        raise
    finally:
        if connection:
            connection.close()


def import_osticket_settings(config: OsticketConfig) -> dict[str, int]:
    ensure_sollus_ticket_tables()
    stats = {
        "departments": 0,
        "statuses": 0,
        "priorities": 0,
        "teams": 0,
        "queues": 0,
        "slas": 0,
        "topics": 0,
        "contacts": 0,
        "filter_rules": 0,
        "template_groups": 0,
        "templates": 0,
        "queue_columns": 0,
        "queue_sorts": 0,
        "team_members": 0,
        "department_access": 0,
        "tasks": 0,
        "canned_responses": 0,
    }
    connection = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        cursorclass=DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            _import_departments(cursor, config.prefix, stats)
            _import_statuses(cursor, config.prefix, stats)
            _import_priorities(cursor, config.prefix, stats)
            _import_teams(cursor, config.prefix, stats)
            _import_slas(cursor, config.prefix, stats)
            _import_queues(cursor, config.prefix, stats)
            _import_topics(cursor, config.prefix, stats)
            _import_contacts(cursor, config.prefix, stats)
            _import_team_members(cursor, config.prefix, stats)
            _import_department_access(cursor, config.prefix, stats)
            _import_filter_rules(cursor, config.prefix, stats)
            _import_email_templates(cursor, config.prefix, stats)
            _import_canned_responses(cursor, config.prefix, stats)
            _link_department_template_groups(cursor, config.prefix)
            _import_queue_customizations(cursor, config.prefix, stats)
            _import_tasks(cursor, config.prefix, stats)
        db.session.commit()
        return stats
    finally:
        connection.close()


def import_osticket_attachments(config: OsticketConfig, *, limit: int | None = None) -> dict[str, int]:
    ensure_sollus_ticket_tables()
    stats = {"attachments": 0, "skipped_attachments": 0}
    connection = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        cursorclass=DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            _import_attachments(cursor, config.prefix, stats, limit=limit)
        db.session.commit()
        return stats
    finally:
        connection.close()


def import_osticket_mailboxes(config: OsticketConfig) -> dict[str, int]:
    ensure_sollus_ticket_tables()
    stats = {"mailboxes": 0, "created": 0, "updated": 0}
    connection = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        cursorclass=DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            legacy_creds = _legacy_mailbox_credentials(cursor, config.prefix)
            cursor.execute(
                f"""
                SELECT e.email_id, e.email, e.name, e.dept_id, e.topic_id,
                       a.id AS account_id, a.active, a.host, a.port, a.folder,
                       a.protocol, a.encryption, a.fetchfreq, a.fetchmax,
                       a.postfetch, a.archivefolder
                FROM {config.prefix}email e
                JOIN {config.prefix}email_account a ON a.email_id = e.email_id
                WHERE a.type = 'mailbox'
                """
            )
            for row in cursor.fetchall():
                email = (row.get("email") or "").strip().lower()
                if not email:
                    continue
                mailbox = SollusTicketMailbox.query.filter_by(email=email).first()
                created = False
                if not mailbox:
                    mailbox = SollusTicketMailbox(
                        name=row.get("name") or email,
                        email=email,
                        host=row.get("host") or "",
                        username=email,
                        password="",
                    )
                    db.session.add(mailbox)
                    created = True
                dept = SollusTicketDepartment.query.filter_by(legacy_id=row.get("dept_id")).first() if row.get("dept_id") else None
                topic = SollusTicketTopic.query.filter_by(legacy_id=row.get("topic_id")).first() if row.get("topic_id") else None
                protocol = (row.get("protocol") or "imap").strip().lower()
                creds = legacy_creds.get((row.get("email_id"), row.get("account_id"))) or legacy_creds.get((row.get("email_id"), 0)) or {}
                mailbox.name = row.get("name") or mailbox.name
                mailbox.host = row.get("host") or mailbox.host
                mailbox.port = int(row.get("port") or (110 if protocol.startswith("pop") else 993))
                mailbox.protocol = "pop" if protocol.startswith("pop") else "imap"
                mailbox.username = creds.get("username") or mailbox.username or email
                mailbox.folder = row.get("folder") or "INBOX"
                mailbox.fetch_frequency_minutes = int(row.get("fetchfreq") or 5)
                mailbox.fetch_max = int(row.get("fetchmax") or 30)
                mailbox.postfetch = row.get("postfetch") or "nothing"
                mailbox.archive_folder = row.get("archivefolder") or None
                mailbox.use_ssl = mailbox.port in {993, 995}
                mailbox.mark_seen = True
                mailbox.enabled = bool(row.get("active"))
                mailbox.department_id = dept.id if dept else mailbox.department_id
                mailbox.topic_id = topic.id if topic else mailbox.topic_id
                stats["mailboxes"] += 1
                stats["created" if created else "updated"] += 1
        db.session.commit()
        return stats
    finally:
        connection.close()


def _legacy_mailbox_credentials(cursor, prefix: str) -> dict[tuple[int, int], dict[str, str]]:
    credentials: dict[tuple[int, int], dict[str, str]] = {}
    try:
        cursor.execute(
            f"""
            SELECT namespace, `key`, value
            FROM {prefix}config
            WHERE namespace LIKE 'email.%%.account.%%'
              AND `key` IN ('username', 'passwd')
            """
        )
    except Exception:
        return credentials
    for row in cursor.fetchall():
        match = re.match(r"email\.(\d+)\.account\.(\d+)", row.get("namespace") or "")
        if not match:
            continue
        key = (int(match.group(1)), int(match.group(2)))
        credentials.setdefault(key, {})[row.get("key")] = row.get("value") or ""
    return credentials


def _import_departments(cursor, prefix: str, stats: dict[str, int]) -> None:
    cursor.execute(f"SELECT id, name, ispublic, email_id, tpl_id, created, updated FROM {prefix}department")
    for row in cursor.fetchall():
        legacy_id = row.get("id")
        slug = slugify(row.get("name") or f"dept-{legacy_id}")
        dept = SollusTicketDepartment.query.filter_by(legacy_id=legacy_id).first()
        if not dept:
            dept = SollusTicketDepartment.query.filter_by(slug=slug).first()
        if not dept:
            dept = SollusTicketDepartment(slug=slug)
            db.session.add(dept)
            stats["departments"] += 1
        dept.legacy_id = legacy_id
        dept.name = row.get("name") or dept.slug
        dept.is_active = bool(row.get("ispublic", 1))
        tpl_id = row.get("tpl_id")
        if tpl_id:
            template_group = SollusTicketEmailTemplateGroup.query.filter_by(legacy_id=tpl_id).first()
            dept.email_template_group_id = template_group.id if template_group else dept.email_template_group_id
        dept.updated_at = row.get("updated") or datetime.utcnow()
    db.session.flush()


def _import_statuses(cursor, prefix: str, stats: dict[str, int]) -> None:
    cursor.execute(f"SELECT id, name, state, mode, sort, created, updated FROM {prefix}ticket_status")
    for row in cursor.fetchall():
        key = normalize_osticket_status(row.get("state") or row.get("name"), row.get("state") == "closed")
        status = SollusTicketStatus.query.filter_by(legacy_id=row.get("id")).first()
        if not status:
            status = SollusTicketStatus.query.filter_by(key=key).first()
        if not status:
            status = SollusTicketStatus(legacy_id=row.get("id"), key=key)
            db.session.add(status)
            stats["statuses"] += 1
        status.legacy_id = row.get("id")
        status.label = row.get("name") or key.title()
        status.state = row.get("state") or ("closed" if key in {"closed", "resolved"} else "open")
        status.is_closed = status.state == "closed" or key in {"closed", "resolved"}
        status.sort_order = row.get("sort") or 0
    db.session.flush()


def _import_priorities(cursor, prefix: str, stats: dict[str, int]) -> None:
    cursor.execute(f"SELECT priority_id, priority, priority_desc, priority_color, priority_urgency FROM {prefix}ticket_priority")
    for row in cursor.fetchall():
        key = normalize_osticket_priority(row.get("priority"))
        priority = SollusTicketPriority.query.filter_by(legacy_id=row.get("priority_id")).first()
        if not priority:
            priority = SollusTicketPriority.query.filter_by(key=key).first()
        if not priority:
            priority = SollusTicketPriority(legacy_id=row.get("priority_id"), key=key)
            db.session.add(priority)
            stats["priorities"] += 1
        priority.legacy_id = row.get("priority_id")
        priority.label = row.get("priority") or key.title()
        priority.level = row.get("priority_urgency") or 2
        priority.color = row.get("priority_color") or priority.color or "#0F7BC8"
    db.session.flush()


def _import_teams(cursor, prefix: str, stats: dict[str, int]) -> None:
    try:
        cursor.execute(f"SELECT team_id, name, flags, created, updated FROM {prefix}team")
    except Exception:
        return
    for row in cursor.fetchall():
        legacy_id = row.get("team_id")
        slug = slugify(row.get("name") or f"team-{legacy_id}")
        team = SollusTicketTeam.query.filter_by(legacy_id=legacy_id).first() or SollusTicketTeam.query.filter_by(slug=slug).first()
        if not team:
            team = SollusTicketTeam(slug=slug)
            db.session.add(team)
            stats["teams"] += 1
        team.legacy_id = legacy_id
        team.name = row.get("name") or slug
        team.is_active = True
    db.session.flush()


def _import_slas(cursor, prefix: str, stats: dict[str, int]) -> None:
    try:
        cursor.execute(f"SELECT id, name, grace_period, flags, created, updated FROM {prefix}sla")
    except Exception:
        return
    for row in cursor.fetchall():
        legacy_id = row.get("id")
        slug = slugify(row.get("name") or f"sla-{legacy_id}")
        sla = SollusTicketSLA.query.filter_by(legacy_id=legacy_id).first() or SollusTicketSLA.query.filter_by(slug=slug).first()
        if not sla:
            sla = SollusTicketSLA(slug=slug)
            db.session.add(sla)
            stats["slas"] += 1
        sla.legacy_id = legacy_id
        sla.name = row.get("name") or slug
        sla.grace_period_hours = row.get("grace_period") or 48
        sla.is_active = not bool((row.get("flags") or 0) & 1 << 31)
    db.session.flush()


def _import_queues(cursor, prefix: str, stats: dict[str, int]) -> None:
    try:
        cursor.execute(f"SELECT id, title, config FROM {prefix}queue")
    except Exception:
        return
    for row in cursor.fetchall():
        legacy_id = row.get("id")
        name = row.get("title") or f"Queue {legacy_id}"
        slug = slugify(name)
        queue = SollusTicketQueue.query.filter_by(legacy_id=legacy_id).first() or SollusTicketQueue.query.filter_by(slug=slug).first()
        if not queue:
            queue = SollusTicketQueue(slug=slug)
            db.session.add(queue)
            stats["queues"] += 1
        queue.legacy_id = legacy_id
        queue.name = name
        queue.is_active = True
    db.session.flush()


def _import_topics(cursor, prefix: str, stats: dict[str, int]) -> None:
    cursor.execute(
        f"SELECT topic_id, topic, dept_id, flags, created, updated FROM {prefix}help_topic"
    )
    for row in cursor.fetchall():
        legacy_id = row.get("topic_id")
        slug = slugify(row.get("topic") or f"topic-{legacy_id}")
        topic = SollusTicketTopic.query.filter_by(legacy_id=legacy_id).first()
        if not topic:
            topic = SollusTicketTopic.query.filter_by(slug=slug).first()
        if not topic:
            topic = SollusTicketTopic(slug=slug, name=row.get("topic") or slug)
            db.session.add(topic)
            stats["topics"] += 1
        topic.legacy_id = legacy_id
        topic.name = row.get("topic") or topic.slug
        dept = SollusTicketDepartment.query.filter_by(legacy_id=row.get("dept_id")).first()
        topic.department_id = dept.id if dept else None
        topic.is_active = True
    db.session.flush()


def _find_user_by_legacy(email: str | None, username: str | None) -> User | None:
    from sqlalchemy import func
    if not email and not username:
        return None
    email = (email or "").strip().lower()
    username = (username or "").strip().lower()
    
    # Mappings manual para legados conhecidos que mudaram de nome/email
    mismatches = {
        "rosangela.olivera": "rosangela.oliveira",
        "oscar.diniz": "oscar.william",
    }
    if username in mismatches:
        username = mismatches[username]
        
    # 1. Busca por e-mail exato
    if email:
        user = User.query.filter(func.lower(User.email) == email).first()
        if user:
            return user
            
    # 2. Busca por usuário/usuario exato
    if username:
        user = User.query.filter(func.lower(User.usuario) == username).first()
        if user:
            return user
            
    # 3. Busca por prefixo de e-mail (caso o domínio tenha mudado de sollusgroup.com para sollustecnologia.com)
    if email and "@" in email:
        prefix = email.split("@")[0]
        user = User.query.filter(func.lower(User.usuario) == prefix).first()
        if user:
            return user
        user = User.query.filter(func.lower(User.email).like(f"{prefix}@%")).first()
        if user:
            return user
            
    return None


def _import_team_members(cursor, prefix: str, stats: dict[str, int]) -> None:
    try:
        cursor.execute(
            f"""
            SELECT tm.team_id, s.email, s.username
            FROM {prefix}team_member tm
            JOIN {prefix}staff s ON s.staff_id = tm.staff_id
            """
        )
    except Exception:
        return
    for row in cursor.fetchall():
        team = SollusTicketTeam.query.filter_by(legacy_id=row.get("team_id")).first()
        if not team:
            continue
        user = _find_user_by_legacy(row.get("email"), row.get("username"))
        if not user:
            continue
        exists = SollusTicketTeamMember.query.filter_by(team_id=team.id, user_id=user.id).first()
        if exists:
            continue
        db.session.add(SollusTicketTeamMember(team_id=team.id, user_id=user.id))
        stats["team_members"] += 1
    db.session.flush()


def _import_department_access(cursor, prefix: str, stats: dict[str, int]) -> None:
    try:
        cursor.execute(
            f"""
            SELECT s.dept_id, s.email, s.username, s.isadmin
            FROM {prefix}staff s
            WHERE s.isactive = 1
            """
        )
    except Exception:
        return
    for row in cursor.fetchall():
        dept = SollusTicketDepartment.query.filter_by(legacy_id=row.get("dept_id")).first()
        user = _find_user_by_legacy(row.get("email"), row.get("username"))
        if not dept or not user:
            continue
        access = SollusTicketDepartmentAccess.query.filter_by(department_id=dept.id, user_id=user.id).first()
        if not access:
            access = SollusTicketDepartmentAccess(department_id=dept.id, user_id=user.id)
            db.session.add(access)
            stats["department_access"] += 1
        access.role = "manager" if row.get("isadmin") else "agent"
        access.is_manager = bool(row.get("isadmin"))
    db.session.flush()


def _import_canned_responses(cursor, prefix: str, stats: dict[str, int]) -> None:
    cursor.execute(
        f"""
        SELECT canned_id, dept_id, isenabled, title, response, created, updated
        FROM {prefix}canned_response
        """
    )
    for row in cursor.fetchall():
        title = row.get("title") or f"Resposta #{row.get('canned_id')}"
        slug = slugify(title)
        
        canned = SollusTicketCannedResponse.query.filter_by(title=title).first()
        if not canned:
            canned = SollusTicketCannedResponse(title=title, slug=slug, body="")
            db.session.add(canned)
            stats["canned_responses"] = stats.get("canned_responses", 0) + 1
            
        dept = SollusTicketDepartment.query.filter_by(legacy_id=row.get("dept_id")).first()
        canned.department_id = dept.id if dept else None
        canned.is_active = bool(row.get("isenabled"))
        canned.body = _html_to_text(row.get("response") or "")
        canned.created_at = row.get("created") or datetime.utcnow()
        canned.updated_at = row.get("updated") or canned.created_at
    db.session.flush()


def _import_filter_rules(cursor, prefix: str, stats: dict[str, int]) -> None:
    try:
        cursor.execute(
            f"""
            SELECT f.id AS filter_id, f.name, f.execorder, f.isactive, f.match_all_rules,
                   f.stop_onmatch, r.what, r.how, r.val, a.type AS action_type, a.configuration
            FROM {prefix}filter f
            LEFT JOIN {prefix}filter_rule r ON r.filter_id = f.id AND r.isactive = 1
            LEFT JOIN {prefix}filter_action a ON a.filter_id = f.id
            ORDER BY f.execorder, f.id
            """
        )
    except Exception:
        return
    grouped: dict[int, dict[str, Any]] = {}
    for row in cursor.fetchall():
        item = grouped.setdefault(row["filter_id"], {"row": row, "rules": [], "actions": []})
        if row.get("what") and row.get("val"):
            item["rules"].append((row.get("what"), row.get("how"), row.get("val")))
        if row.get("action_type"):
            item["actions"].append((row.get("action_type"), row.get("configuration")))
    for legacy_id, data in grouped.items():
        row = data["row"]
        name = row.get("name") or f"Filtro legado {legacy_id}"
        rule = SollusTicketFilterRule.query.filter_by(name=name).first()
        if not rule:
            rule = SollusTicketFilterRule(name=name)
            db.session.add(rule)
            stats["filter_rules"] += 1
        rule.is_active = bool(row.get("isactive"))
        rule.sort_order = int(row.get("execorder") or 0)
        rule.match_all = bool(row.get("match_all_rules"))
        rule.stop_processing = bool(row.get("stop_onmatch"))
        rule.reject_ticket = any(action == "reject" for action, _ in data["actions"])
        for what, how, value in data["rules"]:
            _apply_legacy_filter_condition(rule, what, how, value)
    db.session.flush()


def _apply_legacy_filter_condition(rule: SollusTicketFilterRule, what: str, how: str, value: str) -> None:
    what = (what or "").lower()
    how = (how or "").lower()
    value = (value or "").strip()
    if not value:
        return
        
    prefix = ""
    if "regex" in how or how == "match":
        prefix = "regex:"
    elif how == "equal":
        prefix = "equal:"
    elif how == "starts":
        prefix = "starts:"
    elif how == "ends":
        prefix = "ends:"
    
    final_value = f"{prefix}{value}"
    
    if what in {"email", "from", "sender"}:
        rule.sender_contains = final_value
    elif what in {"subject", "cdata__subject"}:
        rule.subject_contains = final_value
    elif what in {"body", "message", "thread"}:
        rule.body_contains = final_value
    else:
        rule.header_contains = final_value


def _import_email_templates(cursor, prefix: str, stats: dict[str, int]) -> None:
    try:
        cursor.execute(f"SELECT tpl_id, isactive, name, lang FROM {prefix}email_template_group")
    except Exception:
        return
    group_map: dict[int, SollusTicketEmailTemplateGroup] = {}
    for row in cursor.fetchall():
        slug = slugify(row.get("name") or f"template-{row.get('tpl_id')}")
        group = SollusTicketEmailTemplateGroup.query.filter_by(legacy_id=row.get("tpl_id")).first()
        if not group:
            group = SollusTicketEmailTemplateGroup.query.filter_by(slug=slug).first()
        if not group:
            group = SollusTicketEmailTemplateGroup(name=row.get("name") or slug, slug=slug)
            db.session.add(group)
            stats["template_groups"] += 1
        group.legacy_id = row.get("tpl_id")
        group.name = row.get("name") or group.name
        group.is_active = bool(row.get("isactive"))
        group_map[row.get("tpl_id")] = group
    db.session.flush()
    cursor.execute(f"SELECT id, tpl_id, code_name, subject, body FROM {prefix}email_template")
    for row in cursor.fetchall():
        group = group_map.get(row.get("tpl_id"))
        if not group:
            continue
        event_key = _legacy_template_event(row.get("code_name"))
        template = SollusTicketEmailTemplate.query.filter_by(group_id=group.id, event_key=event_key).first()
        if not template:
            template = SollusTicketEmailTemplate(group_id=group.id, event_key=event_key, subject="", body_html="")
            db.session.add(template)
            stats["templates"] += 1
        template.subject = _convert_legacy_template(row.get("subject") or "")
        template.body_html = _convert_legacy_template(row.get("body") or "")
        template.body_text = re.sub(r"<[^>]+>", "", template.body_html)
        template.is_active = True
    db.session.flush()


def _link_department_template_groups(cursor, prefix: str) -> None:
    try:
        cursor.execute(f"SELECT id, tpl_id FROM {prefix}department WHERE tpl_id IS NOT NULL AND tpl_id > 0")
    except Exception:
        return
    for row in cursor.fetchall():
        dept = SollusTicketDepartment.query.filter_by(legacy_id=row.get("id")).first()
        group = SollusTicketEmailTemplateGroup.query.filter_by(legacy_id=row.get("tpl_id")).first()
        if dept and group:
            dept.email_template_group_id = group.id
    db.session.flush()


def _legacy_template_event(code_name: str | None) -> str:
    code = (code_name or "").lower()
    if "autoresp" in code:
        return "created"
    if "alert" in code:
        return "created"
    if "assigned" in code or "assign" in code:
        return "assign"
    if "overdue" in code:
        return "overdue"
    if "closed" in code:
        return "closed"
    if "reply" in code or "message" in code:
        return "reply"
    return slugify(code or "legacy")


def _convert_legacy_template(value: str) -> str:
    replacements = {
        "%{ticket.number}": "{ticket_number}",
        "%{ticket.subject}": "{ticket_subject}",
        "%{ticket.name}": "{requester}",
        "%{recipient.name}": "{requester}",
        "%{ticket.dept.name}": "{department}",
        "%{message}": "{body}",
        "%{response}": "{body}",
        "%{ticket.staff_link}": "{ticket_url}",
    }
    for old, new in replacements.items():
        value = (value or "").replace(old, new)
    value = value.replace("%%7Bticket.staff_link%7D", "{ticket_url}")
    return value or ""


def _import_queue_customizations(cursor, prefix: str, stats: dict[str, int]) -> None:
    try:
        cursor.execute(f"SELECT id, title, sort, sort_id FROM {prefix}queue")
    except Exception:
        return
    queue_rows = cursor.fetchall()
    sort_ids = {row.get("sort_id") for row in queue_rows if row.get("sort_id")}
    imported_columns = set()
    for row in queue_rows:
        queue = SollusTicketQueue.query.filter_by(legacy_id=row.get("id")).first()
        if not queue:
            continue
        default_columns = [
            ("number", "Ticket"),
            ("subject", "Assunto"),
            ("requester", "Solicitante"),
            ("department", "Departamento"),
            ("priority", "Prioridade"),
            ("updated_at", "Atualizado"),
        ]
        for order, (field_key, label) in enumerate(default_columns, start=1):
            key = (queue.id, field_key)
            if key in imported_columns:
                continue
            imported_columns.add(key)
            column = SollusTicketCustomQueueColumn.query.filter_by(queue_id=queue.id, field_key=field_key).first()
            if not column:
                column = SollusTicketCustomQueueColumn(queue_id=queue.id, field_key=field_key, label=label)
                db.session.add(column)
                stats["queue_columns"] += 1
            column.label = label
            column.sort_order = order
            column.is_visible = True
    if sort_ids:
        cursor.execute(f"SELECT id, name, columns FROM {prefix}queue_sort")
        sort_rows = {row.get("id"): row for row in cursor.fetchall()}
        for row in queue_rows:
            queue = SollusTicketQueue.query.filter_by(legacy_id=row.get("id")).first()
            sort_row = sort_rows.get(row.get("sort_id"))
            if not queue or not sort_row:
                continue
            try:
                columns = json.loads(sort_row.get("columns") or "[]")
            except Exception:
                columns = []
            for order, column_name in enumerate(columns, start=1):
                direction = "desc" if str(column_name).startswith("-") else "asc"
                field_key = _legacy_sort_field(str(column_name).lstrip("-"))
                sort = SollusTicketCustomQueueSort.query.filter_by(queue_id=queue.id, field_key=field_key).first()
                if not sort:
                    sort = SollusTicketCustomQueueSort(queue_id=queue.id, field_key=field_key)
                    db.session.add(sort)
                    stats["queue_sorts"] += 1
                sort.direction = direction
                sort.sort_order = order
    db.session.flush()


def _legacy_sort_field(value: str) -> str:
    mapping = {
        "lastupdate": "updated_at",
        "created": "created_at",
        "closed": "closed_at",
        "est_duedate": "due_at",
        "cdata__priority": "priority_key",
    }
    return mapping.get(value, "updated_at")


def _import_tasks(cursor, prefix: str, stats: dict[str, int]) -> None:
    try:
        cursor.execute(
            f"""
            SELECT t.id, t.object_id, t.object_type, t.number, t.dept_id, t.staff_id, t.team_id,
                   t.duedate, t.closed, t.created, t.updated, c.title
            FROM {prefix}task t
            LEFT JOIN {prefix}task__cdata c ON c.task_id = t.id
            ORDER BY t.id ASC
            """
        )
    except Exception:
        return
    fallback_ticket = None
    for row in cursor.fetchall():
        if SollusTicketTask.query.filter_by(legacy_id=row.get("id")).first():
            continue
        ticket = None
        if row.get("object_type") == "T" and row.get("object_id"):
            ticket = SollusTicket.query.filter_by(legacy_ticket_id=row.get("object_id")).first()
        if not ticket:
            if not fallback_ticket:
                fallback_ticket = SollusTicket.query.filter_by(number="OST-TASKS").first()
                if not fallback_ticket:
                    fallback_ticket = SollusTicket(
                        number="OST-TASKS",
                        subject="Tarefas legadas sem ticket",
                        source="osticket",
                        status_key="open",
                        priority_key="normal",
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                    db.session.add(fallback_ticket)
                    db.session.flush()
            ticket = fallback_ticket
        if not ticket:
            continue
        dept = SollusTicketDepartment.query.filter_by(legacy_id=row.get("dept_id")).first()
        team = SollusTicketTeam.query.filter_by(legacy_id=row.get("team_id")).first() if row.get("team_id") else None
        assignee = _find_platform_staff(cursor, prefix, row.get("staff_id"))
        db.session.add(
            SollusTicketTask(
                legacy_id=row.get("id"),
                ticket_id=ticket.id,
                number=f"OST-TASK-{row.get('number') or row.get('id')}",
                title=row.get("title") or f"Tarefa legado #{row.get('number') or row.get('id')}",
                body="Importado do osTicket.",
                status_key="closed" if row.get("closed") else "open",
                department_id=dept.id if dept else ticket.department_id,
                team_id=team.id if team else ticket.team_id,
                assignee_id=assignee.id if assignee else None,
                due_at=row.get("duedate"),
                closed_at=row.get("closed"),
                created_at=row.get("created") or datetime.utcnow(),
                updated_at=row.get("updated") or row.get("created") or datetime.utcnow(),
            )
        )
        stats["tasks"] += 1
    db.session.flush()


def _import_attachments(cursor, prefix: str, stats: dict[str, int], *, limit: int | None = None) -> None:
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    cursor.execute(
        f"""
        SELECT a.id AS attachment_id, a.object_id, a.type AS attachment_type,
               a.file_id, a.inline, COALESCE(a.name, f.name) AS filename,
               f.type AS content_type, f.size, f.bk
        FROM {prefix}attachment a
        JOIN {prefix}file f ON f.id = a.file_id
        WHERE a.type = 'H'
        ORDER BY a.id
        {limit_sql}
        """
    )
    upload_root = Path(current_app.config.get("UPLOADS_DIR", "uploads"))
    for row in cursor.fetchall():
        if SollusTicketAttachment.query.filter_by(legacy_attachment_id=row.get("attachment_id")).first():
            stats["skipped_attachments"] += 1
            continue
        entry = SollusTicketThreadEntry.query.filter_by(legacy_entry_id=row.get("object_id")).first()
        if not entry or not entry.ticket_id:
            stats["skipped_attachments"] += 1
            continue
        filename = row.get("filename") or f"anexo-{row.get('file_id')}"
        stored_name = f"legacy-{row.get('attachment_id')}-{secure_filename(filename) or 'anexo'}"
        relative = f"sollus_tickets/{entry.ticket_id}/{stored_name}"
        target = upload_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = _legacy_file_bytes(cursor, prefix, row.get("file_id"))
        if data is None:
            stats["skipped_attachments"] += 1
            continue
        target.write_bytes(data)
        db.session.add(
            SollusTicketAttachment(
                legacy_attachment_id=row.get("attachment_id"),
                ticket_id=entry.ticket_id,
                entry_id=entry.id,
                original_name=filename,
                stored_name=stored_name,
                content_type=row.get("content_type"),
                size=row.get("size") or len(data),
                storage_path=relative,
            )
        )
        stats["attachments"] += 1
        if stats["attachments"] % 200 == 0:
            db.session.commit()


def _legacy_file_bytes(cursor, prefix: str, file_id: int | None) -> bytes | None:
    if not file_id:
        return None
    cursor.execute(
        f"""
        SELECT filedata
        FROM {prefix}file_chunk
        WHERE file_id = %s
        ORDER BY chunk_id
        """,
        (file_id,),
    )
    chunks = [row.get("filedata") for row in cursor.fetchall()]
    if not chunks:
        return None
    return b"".join(bytes(chunk) for chunk in chunks if chunk is not None)


def _import_contacts(cursor, prefix: str, stats: dict[str, int]) -> None:
    cursor.execute(
        f"""
        SELECT u.id, u.name, u.created, ue.address AS email
        FROM {prefix}user u
        LEFT JOIN {prefix}user_email ue ON ue.user_id = u.id AND ue.id = u.default_email_id
        """
    )
    for row in cursor.fetchall():
        contact = SollusTicketContact.query.filter_by(legacy_user_id=row.get("id")).first()
        if not contact:
            email = row.get("email")
            contact = SollusTicketContact(
                legacy_user_id=row.get("id"),
                name=row.get("name") or email or f"Cliente #{row.get('id')}",
                email=email,
            )
            db.session.add(contact)
            stats["contacts"] += 1
        email = row.get("email")
        platform_user = User.query.filter(User.email == email).first() if email else None
        contact.name = row.get("name") or email or f"Cliente #{row.get('id')}"
        contact.email = email
        contact.platform_user_id = platform_user.id if platform_user else None
        contact.created_at = row.get("created") or contact.created_at or datetime.utcnow()
    db.session.flush()


def _import_tickets(cursor, prefix: str, stats: dict[str, int], *, limit: int | None, batch_size: int, dry_run: bool) -> None:
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    cursor.execute(
        f"""
        SELECT
            t.ticket_id, t.number, t.user_id, t.dept_id, t.staff_id, t.team_id,
            t.topic_id, t.status_id, t.sla_id, t.source, t.isoverdue, t.isanswered,
            t.duedate, t.closed, t.created, t.updated,
            c.subject, c.priority
        FROM {prefix}ticket t
        LEFT JOIN {prefix}ticket__cdata c ON c.ticket_id = t.ticket_id
        ORDER BY t.ticket_id ASC
        {limit_sql}
        """
    )
    for row in cursor.fetchall():
        existing_ticket = SollusTicket.query.filter_by(legacy_ticket_id=row.get("ticket_id")).first()
        if existing_ticket:
            _import_thread_entries(cursor, prefix, existing_ticket, existing_ticket.contact, stats)
            stats["skipped_tickets"] += 1
            if not dry_run and stats["skipped_tickets"] % max(batch_size, 1) == 0:
                db.session.commit()
            continue

        dept = SollusTicketDepartment.query.filter_by(legacy_id=row.get("dept_id")).first()
        topic = SollusTicketTopic.query.filter_by(legacy_id=row.get("topic_id")).first()
        team = SollusTicketTeam.query.filter_by(legacy_id=row.get("team_id")).first()
        sla = SollusTicketSLA.query.filter_by(legacy_id=row.get("sla_id")).first()
        contact = SollusTicketContact.query.filter_by(legacy_user_id=row.get("user_id")).first()
        assignee = _find_platform_staff(cursor, prefix, row.get("staff_id"))
        status = SollusTicketStatus.query.filter_by(legacy_id=row.get("status_id")).first()

        legacy_number = row.get("number") or f"OST-{row.get('ticket_id')}"
        ticket_number = _unique_ticket_number(legacy_number, row.get("ticket_id"))
        ticket = SollusTicket(
            legacy_ticket_id=row.get("ticket_id"),
            legacy_number=row.get("number"),
            number=ticket_number,
            subject=row.get("subject") or f"Ticket #{row.get('number') or row.get('ticket_id')}",
            source=row.get("source") or "web",
            department_id=dept.id if dept else None,
            topic_id=topic.id if topic else None,
            team_id=team.id if team else None,
            sla_id=sla.id if sla else None,
            contact_id=contact.id if contact else None,
            requester_id=contact.platform_user_id if contact else None,
            assignee_id=assignee.id if assignee else None,
            status_key=status.key if status else normalize_osticket_status(None, bool(row.get("closed"))),
            priority_key=normalize_osticket_priority(row.get("priority")),
            due_at=row.get("duedate"),
            closed_at=row.get("closed"),
            created_at=row.get("created") or datetime.utcnow(),
            updated_at=row.get("updated") or row.get("created") or datetime.utcnow(),
        )
        db.session.add(ticket)
        db.session.flush()
        stats["tickets"] += 1

        entry_count = _import_thread_entries(cursor, prefix, ticket, contact, stats)
        if entry_count:
            last_entry = (
                SollusTicketThreadEntry.query.filter_by(ticket_id=ticket.id)
                .order_by(SollusTicketThreadEntry.created_at.desc())
                .first()
            )
            ticket.last_message_at = last_entry.created_at if last_entry else ticket.updated_at

        event_count = _import_thread_events(cursor, prefix, ticket)
        stats["events"] += event_count

        if not dry_run and stats["tickets"] % max(batch_size, 1) == 0:
            db.session.commit()

    db.session.flush()


def _import_thread_entries(cursor, prefix: str, ticket: SollusTicket, contact: SollusTicketContact | None, stats: dict[str, int]) -> int:
    cursor.execute(
        f"""
        SELECT e.id, e.type, e.poster, e.title, e.body, e.format, e.flags, e.created, th.object_id
        FROM {prefix}thread th
        JOIN {prefix}thread_entry e ON e.thread_id = th.id
        WHERE th.object_type = 'T' AND th.object_id = %s
        ORDER BY e.created ASC, e.id ASC
        """,
        (ticket.legacy_ticket_id,),
    )
    count = 0
    for row in cursor.fetchall():
        if row.get("id") and SollusTicketThreadEntry.query.filter_by(legacy_entry_id=row.get("id")).first():
            continue
        entry = SollusTicketThreadEntry(
            legacy_entry_id=row.get("id"),
            ticket_id=ticket.id,
            contact_id=contact.id if contact and (row.get("type") == "M") else None,
            type=_entry_type(row.get("type")),
            visibility="internal" if row.get("type") == "N" else "public",
            title=row.get("title"),
            body=_html_to_text(row.get("body") or ""),
            created_at=row.get("created") or ticket.created_at,
        )
        db.session.add(entry)
        count += 1
        stats["entries"] += 1
    return count


def _unique_ticket_number(number: str, legacy_ticket_id: int | None) -> str:
    base = str(number or f"OST-{legacy_ticket_id}").strip() or f"OST-{legacy_ticket_id}"
    existing = SollusTicket.query.filter_by(number=base).first()
    if not existing:
        return base
    if existing.legacy_ticket_id == legacy_ticket_id:
        return base
    suffix = f"OST-{legacy_ticket_id}"
    candidate = f"{base}-{suffix}"
    counter = 2
    while SollusTicket.query.filter_by(number=candidate).first():
        candidate = f"{base}-{suffix}-{counter}"
        counter += 1
    return candidate


def _import_thread_events(cursor, prefix: str, ticket: SollusTicket) -> int:
    cursor.execute(
        f"""
        SELECT ev.id, ev.event_id, ev.username, ev.annulled, ev.timestamp, th.object_id
        FROM {prefix}thread th
        JOIN {prefix}thread_event ev ON ev.thread_id = th.id
        WHERE th.object_type = 'T' AND th.object_id = %s
        ORDER BY ev.timestamp ASC, ev.id ASC
        """,
        (ticket.legacy_ticket_id,),
    )
    events = []
    for row in cursor.fetchall():
        label = row.get("event") or "event"
        username = row.get("username") or "sistema"
        events.append((label, f"{label} por {username}", row.get("timestamp")))
    bulk_add_events(ticket, events)
    return len(events)


def _find_platform_staff(cursor, prefix: str, staff_id: int | None) -> User | None:
    if not staff_id:
        return None
    cursor.execute(f"SELECT staff_id, firstname, lastname, email, username FROM {prefix}staff WHERE staff_id = %s", (staff_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return _find_user_by_legacy(row.get("email"), row.get("username"))


def _entry_type(value: Any) -> str:
    raw = (value or "").upper()
    if raw == "M":
        return "message"
    if raw == "R":
        return "reply"
    if raw == "N":
        return "note"
    return "event"


def _html_to_text(value: str) -> str:
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
