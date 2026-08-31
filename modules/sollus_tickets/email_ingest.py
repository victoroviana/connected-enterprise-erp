"""IMAP ingestion for Sollus Tickets."""
from __future__ import annotations

import html
import imaplib
import poplib
import re
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage, Message
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from sqlalchemy import or_

from extensions import db

from .models import (
    SollusTicket,
    SollusTicketCollaborator,
    SollusTicketContact,
    SollusTicketMailbox,
    SollusTicketProcessedEmail,
)
from .services import (
    add_event,
    add_thread_entry,
    create_ticket,
    log_system_event,
    save_ticket_attachment_bytes,
    update_status,
)
from .advanced import (
    apply_filter_rules,
    decode_message_id,
    infer_priority_from_headers,
    mail_flags,
)


_TICKET_TOKEN_RE = re.compile(r"(?:Sollus Tickets\s*[:#-]*\s*|ST-\d{4}-|#)\s*([A-Za-z0-9-]+)", re.IGNORECASE)
_REPLY_PREFIX_RE = re.compile(r"^\s*((re|res|fw|fwd)\s*:\s*)+", re.IGNORECASE)


@dataclass
class AttachmentPayload:
    filename: str
    content_type: str | None
    data: bytes
    content_id: str | None = None


def sync_enabled_mailboxes(limit: int | None = None, force: bool = False) -> dict[str, int]:
    stats = {"mailboxes": 0, "created": 0, "replied": 0, "skipped": 0, "failed": 0}
    query = SollusTicketMailbox.query
    if not force:
        query = query.filter_by(enabled=True)
    for mailbox in query.order_by(SollusTicketMailbox.id).all():
        if not force and not _mailbox_due(mailbox):
            continue
        try:
            result = sync_mailbox(mailbox.id, limit=limit)
            stats["mailboxes"] += 1
            for key in ("created", "replied", "skipped", "failed"):
                stats[key] += result.get(key, 0)
        except Exception:
            # Exceptions are logged and committed inside sync_mailbox, so we just track the failed count
            stats["failed"] += 1
    return stats


def sync_mailbox(mailbox_id: int, limit: int | None = None) -> dict[str, int]:
    mailbox = SollusTicketMailbox.query.get(mailbox_id)
    if not mailbox:
        raise ValueError("Caixa de e-mail nao encontrada.")
    stats = {"created": 0, "replied": 0, "skipped": 0, "failed": 0}
    client = None
    try:
        if (mailbox.protocol or "imap").lower().startswith("pop"):
            return _sync_pop_mailbox(mailbox, limit=limit)
        client = _connect_imap(mailbox)
        client.select(mailbox.folder or "INBOX")
        max_fetch = limit or mailbox.fetch_max or 30
        uids = _search_uids(client, mailbox, max_fetch)
        processed_uids: list[int] = []
        for uid in uids[:max_fetch]:
            try:
                outcome = _process_uid(client, mailbox, uid)
                if outcome != "failed":
                    processed_uids.append(uid)
                stats[outcome] = stats.get(outcome, 0) + 1
            except Exception as exc:
                db.session.rollback()
                stats["failed"] += 1
                mailbox.last_error = f"UID {uid}: {exc}"
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
        if processed_uids:
            _postfetch(client, mailbox, processed_uids)
        mailbox.last_sync_at = datetime.utcnow()
        mailbox.last_error = None if not stats["failed"] else mailbox.last_error
        mailbox.num_errors = 0 if not stats["failed"] else int(mailbox.num_errors or 0) + stats["failed"]
        db.session.commit()
        
        if stats["created"] or stats["replied"]:
            log_system_event(
                f"Email Sync: {mailbox.email}",
                f"Sincronização concluída: {stats['created']} criados, {stats['replied']} respostas.",
                level="info",
                source="cron"
            )
    except Exception as exc:
        db.session.rollback()
        mailbox.last_error = str(exc)
        mailbox.num_errors = int(mailbox.num_errors or 0) + 1
        mailbox.last_sync_at = datetime.utcnow()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        log_system_event(
            f"Email Sync Error: {mailbox.email}",
            str(exc),
            level="error",
            source="cron"
        )
        raise
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass
    return stats


def _connect_imap(mailbox: SollusTicketMailbox):
    client_cls = imaplib.IMAP4_SSL if mailbox.use_ssl else imaplib.IMAP4
    client = client_cls(mailbox.host, mailbox.port)
    client.login(mailbox.username, mailbox.password)
    return client


def _connect_pop(mailbox: SollusTicketMailbox):
    client_cls = poplib.POP3_SSL if mailbox.use_ssl else poplib.POP3
    client = client_cls(mailbox.host, mailbox.port, timeout=30)
    client.user(mailbox.username)
    client.pass_(mailbox.password)
    return client


def _sync_pop_mailbox(mailbox: SollusTicketMailbox, limit: int | None = None) -> dict[str, int]:
    stats = {"created": 0, "replied": 0, "skipped": 0, "failed": 0}
    client = None
    delete_numbers: list[int] = []
    try:
        client = _connect_pop(mailbox)
        count, _ = client.stat()
        max_fetch = limit or mailbox.fetch_max or 30
        numbers = list(range(max(1, count - max_fetch + 1), count + 1))
        uid_map = _pop_uid_map(client)
        for number in numbers:
            source_uid = uid_map.get(number) or str(number)
            uid = _uid_int(source_uid)
            try:
                outcome = _process_pop_message(client, mailbox, number, uid, source_uid)
                if outcome != "failed":
                    delete_numbers.append(number)
                stats[outcome] = stats.get(outcome, 0) + 1
            except Exception as exc:
                db.session.rollback()
                stats["failed"] += 1
                mailbox.last_error = f"POP {number}: {exc}"
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
        if (mailbox.postfetch or "nothing").lower() == "delete":
            for number in delete_numbers:
                client.dele(number)
        client.quit()
        client = None
        mailbox.last_sync_at = datetime.utcnow()
        mailbox.last_error = None if not stats["failed"] else mailbox.last_error
        mailbox.num_errors = 0 if not stats["failed"] else int(mailbox.num_errors or 0) + stats["failed"]
        db.session.commit()
        
        if stats["created"] or stats["replied"]:
            log_system_event(
                f"Email Sync (POP): {mailbox.email}",
                f"Sincronização concluída: {stats['created']} criados, {stats['replied']} respostas.",
                level="info",
                source="cron"
            )
    except Exception as exc:
        db.session.rollback()
        mailbox.last_error = str(exc)
        mailbox.num_errors = int(mailbox.num_errors or 0) + 1
        mailbox.last_sync_at = datetime.utcnow()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        log_system_event(
            f"Email Sync Error (POP): {mailbox.email}",
            str(exc),
            level="error",
            source="cron"
        )
        raise
    finally:
        if client:
            try:
                client.quit()
            except Exception:
                pass
    return stats


def _pop_uid_map(client) -> dict[int, str]:
    try:
        _, lines, _ = client.uidl()
    except Exception:
        return {}
    mapping = {}
    for line in lines:
        text = line.decode("utf-8", errors="ignore") if isinstance(line, bytes) else str(line)
        parts = text.split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit():
            mapping[int(parts[0])] = parts[1].strip()
    return mapping


def _uid_int(source_uid: str) -> int:
    return zlib.crc32((source_uid or "").encode("utf-8")) & 0x7FFFFFFF


def _process_pop_message(client, mailbox, number: int, uid: int, source_uid: str) -> str:
    from .models import SollusTicketProcessedEmail  # lazy import to avoid scheduler context issues
    existing = SollusTicketProcessedEmail.query.filter_by(mailbox_id=mailbox.id, source_uid=source_uid).first()
    if existing:
        _remember_uid(mailbox, uid)
        return "skipped"
    _, lines, _ = client.retr(number)
    raw = b"\r\n".join(lines)
    return _process_raw_message(mailbox, uid, source_uid, raw)


def _mailbox_due(mailbox: SollusTicketMailbox) -> bool:
    if not mailbox.last_sync_at:
        return True
    max_errors = 5
    delay_minutes = 10 if int(mailbox.num_errors or 0) >= max_errors else int(mailbox.fetch_frequency_minutes or 5)
    return mailbox.last_sync_at <= datetime.utcnow() - timedelta(minutes=delay_minutes)


def _search_uids(client, mailbox: SollusTicketMailbox, max_fetch: int) -> list[int]:
    if mailbox.last_uid:
        criteria = f"UID {int(mailbox.last_uid) + 1}:*"
    else:
        criteria = "ALL"
    status, data = client.uid("search", None, criteria)
    if status != "OK" or not data:
        return []
    uids = [int(uid) for uid in data[0].split() if uid.isdigit()]
    if len(uids) > max_fetch:
        return uids[-max_fetch:]
    return uids


def _process_uid(client, mailbox: SollusTicketMailbox, uid: int) -> str:
    if SollusTicketProcessedEmail.query.filter_by(mailbox_id=mailbox.id, uid=uid).first():
        _remember_uid(mailbox, uid)
        return "skipped"

    status, data = client.uid("fetch", str(uid), "(RFC822)")
    if status != "OK" or not data:
        raise RuntimeError("Nao foi possivel baixar a mensagem.")
    raw = next((part[1] for part in data if isinstance(part, tuple) and part[1]), None)
    if not raw:
        raise RuntimeError("Mensagem vazia.")

    return _process_raw_message(mailbox, uid, str(uid), raw, client=client)


def _process_raw_message(mailbox: SollusTicketMailbox, uid: int, source_uid: str, raw: bytes, client=None) -> str:
    msg = message_from_bytes(raw, policy=policy.default)
    message_id = _normalize_message_id(msg.get("Message-ID")) or f"{mailbox.id}:{uid}"
    if SollusTicketProcessedEmail.query.filter_by(message_id=message_id).first():
        _remember_uid(mailbox, uid)
        return "skipped"

    sender_name, sender_email = parseaddr(str(msg.get("From") or ""))
    sender_email = (sender_email or "").strip().lower()
    flags = mail_flags(msg)
    if not sender_email or sender_email == (mailbox.email or "").strip().lower():
        _record_processed(mailbox, uid, source_uid, message_id, msg, sender_email, None, None)
        _remember_uid(mailbox, uid)
        return "skipped"
    if flags.get("bounce") or flags.get("auto_reply") or flags.get("spam") or flags.get("viral"):
        _record_processed(mailbox, uid, source_uid, message_id, msg, sender_email, None, None)
        _remember_uid(mailbox, uid)
        return "skipped"

    from modules.propostas.models import User
    system_user = User.query.filter_by(email=sender_email).first() if sender_email else None

    if system_user:
        contact = None
    else:
        contact = _get_or_create_contact(sender_name, sender_email)

    subject = str(msg.get("Subject") or "(sem assunto)").strip()
    is_forwarded = _is_forwarded(msg, subject)
    ticket = _find_existing_ticket(msg, subject)
    body = _extract_body(msg)
    # Só remove o histórico citado em respostas de tickets existentes
    # Para novos tickets, mantém o histórico completo para não perder o contexto original
    if ticket and not is_forwarded:
        body = _strip_quoted_reply(body)
    body = _clean_mangled_bullets(body)
    attachments = _extract_attachments(msg)

    # Se for resposta a um ticket existente, filtra anexos inline que pertencem ao histórico citado
    if ticket and not is_forwarded:
        html_body = _get_html_body(msg)
        if html_body:
            unquoted_html = _strip_quoted_html(html_body).lower()
            filtered_attachments = []
            for att in attachments:
                if att.content_type and ";inline" in att.content_type:
                    # Só mantém se o cid estiver presente no HTML não citado
                    if att.content_id and att.content_id.lower() in unquoted_html:
                        filtered_attachments.append(att)
                else:
                    filtered_attachments.append(att)
            attachments = filtered_attachments
    created = False
    headers = "\n".join(f"{key}: {value}" for key, value in msg.items())
    priority_key = infer_priority_from_headers(msg) or "normal"

    if ticket:
        if ticket.is_closed:
            update_status(ticket, "open", None, "Reaberto por resposta recebida por e-mail.")
        entry = add_thread_entry(ticket, body=body, actor_id=system_user.id if system_user else None, contact_id=None if system_user else contact.id, entry_type="reply", visibility="public", notify=False)
        if not entry.email_message_id:
            entry.email_message_id = message_id
        entry.email_references = str(msg.get("References") or "")
        entry.mail_flags_json = flags
    else:
        rule = apply_filter_rules(
            sender=sender_email,
            subject=subject,
            body=body,
            headers=headers,
            defaults={
                "department_id": mailbox.department_id,
                "topic_id": mailbox.topic_id,
                "queue_id": mailbox.queue_id,
                "team_id": mailbox.team_id,
                "sla_id": mailbox.sla_id,
                "priority_key": priority_key,
            },
        )
        if rule.rejected:
            _record_processed(mailbox, uid, source_uid, message_id, msg, sender_email, None, None)
            _remember_uid(mailbox, uid)
            return "skipped"
        ticket = create_ticket(
            subject=_clean_subject(subject),
            body=body,
            requester_id=system_user.id if system_user else None,
            contact_id=None if system_user else contact.id,
            department_id=rule.department_id,
            topic_id=rule.topic_id,
            queue_id=rule.queue_id,
            team_id=rule.team_id,
            sla_id=rule.sla_id,
            priority_key=rule.priority_key or "normal",
            source="email",
            notify=False,
        )
        if rule.assignee_id:
            ticket.assignee_id = rule.assignee_id
        if rule.matched_rules:
            add_event(ticket, "filter", f"Regras aplicadas: {', '.join(rule.matched_rules)}", None)
        entry = ticket.entries[0] if ticket.entries else None
        if entry:
            if not entry.email_message_id:
                entry.email_message_id = message_id
            entry.email_references = str(msg.get("References") or "")
            entry.mail_flags_json = flags
        created = True

    _sync_cc_collaborators(ticket, msg, mailbox, sender_email)
    for payload in attachments:
        try:
            save_ticket_attachment_bytes(
                ticket,
                filename=payload.filename,
                data=payload.data,
                content_type=payload.content_type,
                entry=entry,
            )
        except ValueError as exc:
            add_event(ticket, "attachment_rejected", str(exc), None)

    # Dispara as notificações por e-mail após salvar todos os anexos
    from modules.sollus_tickets.services import notify_ticket
    notify_ticket(ticket, "created" if created else "reply", body, entry)

    _record_processed(mailbox, uid, source_uid, message_id, msg, sender_email, ticket, entry)
    if client and mailbox.mark_seen:
        client.uid("store", str(uid), "+FLAGS", r"(\Seen)")
    _remember_uid(mailbox, uid)
    db.session.commit()
    return "created" if created else "replied"


def _postfetch(client, mailbox: SollusTicketMailbox, uids: list[int]) -> None:
    postfetch = (mailbox.postfetch or "nothing").lower()
    if postfetch not in {"archive", "delete"}:
        return
    uid_set = ",".join(str(uid) for uid in sorted(set(uids)))
    if postfetch == "archive" and mailbox.archive_folder:
        status, _ = client.uid("COPY", uid_set, mailbox.archive_folder)
        if status == "OK":
            client.uid("STORE", uid_set, "+FLAGS", r"(\Deleted)")
            client.expunge()
        return
    if postfetch == "delete":
        client.uid("STORE", uid_set, "+FLAGS", r"(\Deleted)")
        client.expunge()


def _find_existing_ticket(msg: Message, subject: str) -> SollusTicket | None:
    for message_id in _referenced_message_ids(msg):
        decoded = decode_message_id(message_id)
        if decoded:
            ticket = SollusTicket.query.get(decoded["ticket_id"])
            if ticket:
                return ticket
        processed = SollusTicketProcessedEmail.query.filter_by(message_id=message_id).first()
        if processed and processed.ticket:
            return processed.ticket
        entry = None
        try:
            from .models import SollusTicketThreadEntry
            entry = SollusTicketThreadEntry.query.filter_by(email_message_id=message_id).first()
        except Exception:
            db.session.rollback()
            entry = None
        if entry and entry.ticket:
            return entry.ticket

    for token in _subject_tokens(subject):
        ticket = SollusTicket.query.filter(
            or_(
                SollusTicket.number == token,
                SollusTicket.number == token.zfill(6),  # support matching padded numeric ticket numbers
                SollusTicket.legacy_number == token,
                SollusTicket.number == f"ST-{datetime.utcnow().year}-{token.zfill(5)}",
            )
        ).first()
        if ticket:
            return ticket
        if token.isdigit():
            ticket = SollusTicket.query.get(int(token))
            if ticket:
                return ticket
    return None


def _referenced_message_ids(msg: Message) -> list[str]:
    values = [str(msg.get("In-Reply-To") or ""), str(msg.get("References") or "")]
    ids: list[str] = []
    for value in values:
        ids.extend(_normalize_message_id(item) for item in re.findall(r"<[^>]+>", value))
    return [item for item in ids if item]


def _subject_tokens(subject: str) -> list[str]:
    tokens = []
    for match in _TICKET_TOKEN_RE.finditer(subject or ""):
        value = (match.group(1) or "").strip()
        if value and value not in tokens:
            tokens.append(value)
    return tokens


def _extract_body(msg: Message) -> str:
    plain = []
    html_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                plain.append(part.get_content())
            elif content_type == "text/html":
                html_parts.append(part.get_content())
    else:
        if msg.get_content_type() == "text/html":
            html_parts.append(msg.get_content())
        else:
            plain.append(msg.get_content())
    body = "\n\n".join(str(part).strip() for part in plain if str(part).strip())
    if body:
        return body
    return _html_to_text("\n\n".join(str(part) for part in html_parts)).strip() or "(sem conteudo)"


def _extract_attachments(msg: Message) -> list[AttachmentPayload]:
    attachments = []
    for part in msg.walk() if msg.is_multipart() else []:
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        content_id = str(part.get("Content-ID") or "").strip()
        
        is_inline = False
        if disposition == "inline" or content_id:
            is_inline = True
            
        if not filename and disposition != "attachment" and not content_id:
            continue
            
        data = part.get_payload(decode=True) or b""
        if not data:
            continue
            
        content_type = part.get_content_type() or "application/octet-stream"
        if is_inline:
            content_type = f"{content_type};inline"
            
        fallback_filename = filename or (f"imagem_assinatura" if "image" in content_type else "anexo_inline")
        if filename:
            display_filename = filename
        else:
            ext = ".png" if "png" in content_type else (".jpg" if "jpeg" in content_type or "jpg" in content_type else ".bin")
            display_filename = f"{fallback_filename}{ext}"
            
        clean_cid = content_id
        if clean_cid.startswith("<") and clean_cid.endswith(">"):
            clean_cid = clean_cid[1:-1]
        clean_cid = clean_cid.strip().lower()
            
        attachments.append(AttachmentPayload(
            filename=display_filename, 
            content_type=content_type, 
            data=data,
            content_id=clean_cid or None
        ))
    return attachments


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", value or "")
    # Remove atributos src="cid:..." de imagens embutidas antes de extrair o texto
    text = re.sub(r'\ssrc=["\']cid:[^"\']*["\']', "", text, flags=re.I)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    # Remove referências cid: residuais que possam ter ficado no texto
    text = re.sub(r"\[cid:[^\]]*\]", "", text)
    text = re.sub(r"cid:[^\s<>\"']+", "", text)
    return html.unescape(text)


def _sync_cc_collaborators(ticket: SollusTicket, msg: Message, mailbox: SollusTicketMailbox, sender_email: str) -> None:
    ignored = {(mailbox.email or "").strip().lower(), sender_email}
    header_values = []
    for name in ("Cc", "Delivered-To", "X-Original-To", "Reply-To", "Bcc"):
        value = msg.get(name)
        if value:
            header_values.append(str(value))
    for _, email_addr in getaddresses(header_values):
        email_addr = (email_addr or "").strip().lower()
        if not email_addr or email_addr in ignored:
            continue
        contact = _get_or_create_contact("", email_addr)
        exists = SollusTicketCollaborator.query.filter_by(ticket_id=ticket.id, contact_id=contact.id).first()
        if not exists:
            db.session.add(SollusTicketCollaborator(ticket_id=ticket.id, contact_id=contact.id))


def _get_or_create_contact(name: str, email_addr: str) -> SollusTicketContact:
    contact = SollusTicketContact.query.filter_by(email=email_addr).first()
    if contact:
        if name and (not contact.name or contact.name == contact.email):
            contact.name = name
        return contact
    contact = SollusTicketContact(name=(name or email_addr).strip(), email=email_addr)
    db.session.add(contact)
    db.session.flush()
    return contact


def _record_processed(
    mailbox: SollusTicketMailbox,
    uid: int,
    source_uid: str,
    message_id: str,
    msg: Message,
    sender_email: str,
    ticket: SollusTicket | None,
    entry,
) -> None:
    db.session.add(
        SollusTicketProcessedEmail(
            mailbox_id=mailbox.id,
            uid=uid,
            source_uid=source_uid,
            message_id=message_id,
            in_reply_to=_normalize_message_id(msg.get("In-Reply-To")),
            sender=sender_email,
            subject=str(msg.get("Subject") or ""),
            received_at=_message_date(msg),
            ticket_id=ticket.id if ticket else None,
            entry_id=entry.id if entry else None,
        )
    )


def _remember_uid(mailbox: SollusTicketMailbox, uid: int) -> None:
    mailbox.last_uid = max(int(mailbox.last_uid or 0), int(uid))


def _message_date(msg: Message) -> datetime | None:
    try:
        from datetime import timezone
        value = parsedate_to_datetime(str(msg.get("Date") or ""))
        if value:
            # Converte para UTC e remove tzinfo para salvar no banco como naive UTC
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return None
    except Exception:
        return None


def _normalize_message_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1]
    return text.strip().lower()


def _clean_subject(subject: str) -> str:
    subject = _REPLY_PREFIX_RE.sub("", subject or "").strip()
    return subject or "(sem assunto)"


def _is_forwarded(msg: Message, subject: str) -> bool:
    """Detecta se o e-mail é um encaminhamento (forward)."""
    # Detecta pelo prefixo do assunto
    if re.match(r"^\s*((fw|fwd|encaminhado|enc)\s*:\s*)+", subject or "", re.IGNORECASE):
        return True
    # Detecta pelo header de flags do Exchange/Outlook
    ms_flags = str(msg.get("X-MS-Exchange-Message-Flags") or "").lower()
    if "forwarded" in ms_flags:
        return True
    # Detecta por header padrão de forward
    references = str(msg.get("References") or "")
    in_reply_to = str(msg.get("In-Reply-To") or "")
    # Forwarded messages often don't have In-Reply-To but have Resent- headers
    resent = str(msg.get("Resent-From") or msg.get("Resent-To") or "").strip()
    if resent:
        return True
    return False


def _strip_quoted_reply(body: str) -> str:
    separators = [
        r"(?im)^On .+ wrote:$",
        r"(?im)^Em .+ escreveu:$",
        r"(?im)^-----Original Message-----$",
        r"(?im)^De:\s.+$",
    ]
    cut = len(body or "")
    for pattern in separators:
        match = re.search(pattern, body or "")
        if match:
            cut = min(cut, match.start())
    cleaned = (body or "")[:cut].strip()
    return cleaned or (body or "(sem conteudo)")


def _clean_mangled_bullets(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"(?m)^\s*\?\s+", "• ", text)


def _get_html_body(msg: Message) -> str:
    html_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html_parts.append(part.get_content())
                except Exception:
                    pass
    else:
        if msg.get_content_type() == "text/html":
            try:
                html_parts.append(msg.get_content())
            except Exception:
                pass
    return "\n\n".join(html_parts)


def _strip_quoted_html(html_content: str) -> str:
    if not html_content:
        return ""
    patterns = [
        r"(?i)<div[^>]*class=[\"']gmail_quote[\"']",
        r"(?i)<div[^>]*id=[\"']divRplyFwdMsg[\"']",
        r"(?i)<blockquote",
        r"(?i)<hr[^>]*>\s*(?:<b>)?\s*(?:De|From):",
        r"(?i)<div[^>]*style=[\"'][^\"']*border-top:\s*solid\s*#B5C4DF",
        r"(?i)<div[^>]*style=[\"'][^\"']*border-top:\s*solid\s*#E1E1E1",
        r"(?i)Em\s+.*,\s+\d+\s+de\s+.*\s+escreveu:",
        r"(?i)On\s+.*,\s+.*wrote:",
    ]
    cut = len(html_content)
    for pattern in patterns:
        match = re.search(pattern, html_content)
        if match:
            cut = min(cut, match.start())
    return html_content[:cut]
