"""Models for the Sollus Tickets module.

The schema intentionally mirrors the main osTicket concepts while using the
current platform user table for authenticated staff/requesters.
"""
from __future__ import annotations

from datetime import datetime

from extensions import db


class SollusTicketDepartment(db.Model):
    __tablename__ = "sollus_ticket_departments"
    __table_args__ = (
        db.UniqueConstraint("slug", name="uq_sollus_ticket_departments_slug"),
        db.UniqueConstraint("legacy_id", name="uq_sollus_ticket_departments_legacy_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    legacy_id = db.Column(db.Integer)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255))
    email_template_group_id = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    auto_assign_enabled = db.Column(db.Boolean, nullable=False, default=False)
    last_assigned_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tickets = db.relationship("SollusTicket", back_populates="department", lazy="dynamic")


class SollusTicketTeam(db.Model):
    __tablename__ = "sollus_ticket_teams"
    __table_args__ = (
        db.UniqueConstraint("slug", name="uq_sollus_ticket_teams_slug"),
        db.UniqueConstraint("legacy_id", name="uq_sollus_ticket_teams_legacy_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    legacy_id = db.Column(db.Integer)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class SollusTicketTeamMember(db.Model):
    __tablename__ = "sollus_ticket_team_members"
    __table_args__ = (
        db.UniqueConstraint("team_id", "user_id", name="uq_sollus_ticket_team_members_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_teams.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = db.Column(db.String(40), nullable=False, default="member")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    team = db.relationship("SollusTicketTeam", backref=db.backref("members", cascade="all, delete-orphan"))
    user = db.relationship("User")


class SollusTicketQueue(db.Model):
    __tablename__ = "sollus_ticket_queues"
    __table_args__ = (
        db.UniqueConstraint("slug", name="uq_sollus_ticket_queues_slug"),
        db.UniqueConstraint("legacy_id", name="uq_sollus_ticket_queues_legacy_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    legacy_id = db.Column(db.Integer)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(120), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_departments.id", ondelete="SET NULL"))
    team_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_teams.id", ondelete="SET NULL"))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    department = db.relationship("SollusTicketDepartment")
    team = db.relationship("SollusTicketTeam")


class SollusTicketSLA(db.Model):
    __tablename__ = "sollus_ticket_slas"
    __table_args__ = (
        db.UniqueConstraint("slug", name="uq_sollus_ticket_slas_slug"),
        db.UniqueConstraint("legacy_id", name="uq_sollus_ticket_slas_legacy_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    legacy_id = db.Column(db.Integer)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(120), nullable=False)
    grace_period_hours = db.Column(db.Integer, nullable=False, default=48)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class SollusTicketStatus(db.Model):
    __tablename__ = "sollus_ticket_statuses"
    __table_args__ = (
        db.UniqueConstraint("key", name="uq_sollus_ticket_statuses_key"),
        db.UniqueConstraint("legacy_id", name="uq_sollus_ticket_statuses_legacy_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    legacy_id = db.Column(db.Integer)
    key = db.Column(db.String(40), nullable=False)
    label = db.Column(db.String(80), nullable=False)
    state = db.Column(db.String(30), nullable=False, default="open")
    is_closed = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)


class SollusTicketPriority(db.Model):
    __tablename__ = "sollus_ticket_priorities"
    __table_args__ = (
        db.UniqueConstraint("key", name="uq_sollus_ticket_priorities_key"),
        db.UniqueConstraint("legacy_id", name="uq_sollus_ticket_priorities_legacy_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    legacy_id = db.Column(db.Integer)
    key = db.Column(db.String(40), nullable=False)
    label = db.Column(db.String(80), nullable=False)
    level = db.Column(db.Integer, nullable=False, default=2)
    color = db.Column(db.String(20), nullable=False, default="#0F7BC8")


class SollusTicketTopic(db.Model):
    __tablename__ = "sollus_ticket_topics"
    __table_args__ = (
        db.UniqueConstraint("slug", name="uq_sollus_ticket_topics_slug"),
        db.UniqueConstraint("legacy_id", name="uq_sollus_ticket_topics_legacy_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    legacy_id = db.Column(db.Integer)
    department_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_departments.id", ondelete="SET NULL"))
    name = db.Column(db.String(180), nullable=False)
    slug = db.Column(db.String(140), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    department = db.relationship("SollusTicketDepartment")


class SollusTicketFormField(db.Model):
    __tablename__ = "sollus_ticket_form_fields"
    __table_args__ = (
        db.UniqueConstraint("key", name="uq_sollus_ticket_form_fields_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_topics.id", ondelete="CASCADE"))
    key = db.Column(db.String(80), nullable=False)
    label = db.Column(db.String(160), nullable=False)
    field_type = db.Column(db.String(30), nullable=False, default="text")
    options_json = db.Column(db.JSON)
    required = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    topic = db.relationship("SollusTicketTopic", backref=db.backref("form_fields", cascade="all, delete-orphan"))


class SollusTicketContact(db.Model):
    __tablename__ = "sollus_ticket_contacts"
    __table_args__ = (
        db.UniqueConstraint("legacy_user_id", name="uq_sollus_ticket_contacts_legacy_user_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    legacy_user_id = db.Column(db.Integer)
    platform_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    name = db.Column(db.String(180), nullable=False)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(80))
    organization = db.Column(db.String(180))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    platform_user = db.relationship("User")


class SollusTicket(db.Model):
    __tablename__ = "sollus_tickets"
    __table_args__ = (
        db.Index("ix_sollus_tickets_status_created", "status_key", "created_at"),
        db.Index("ix_sollus_tickets_department_status", "department_id", "status_key"),
        db.UniqueConstraint("legacy_ticket_id", name="uq_sollus_tickets_legacy_ticket_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(32), unique=True)
    legacy_ticket_id = db.Column(db.Integer)
    legacy_number = db.Column(db.String(32))
    subject = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(40), nullable=False, default="web")
    status_key = db.Column(db.String(40), nullable=False, default="open")
    priority_key = db.Column(db.String(40), nullable=False, default="normal")
    department_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_departments.id", ondelete="SET NULL"))
    topic_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_topics.id", ondelete="SET NULL"))
    queue_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_queues.id", ondelete="SET NULL"))
    team_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_teams.id", ondelete="SET NULL"))
    sla_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_slas.id", ondelete="SET NULL"))
    contact_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_contacts.id", ondelete="SET NULL"))
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    team_name = db.Column(db.String(120))
    due_at = db.Column(db.DateTime)
    overdue_at = db.Column(db.DateTime)
    resolved_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    reopened_at = db.Column(db.DateTime)
    reopen_count = db.Column(db.Integer, nullable=False, default=0)
    close_reason = db.Column(db.Text)
    last_message_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    department = db.relationship("SollusTicketDepartment", back_populates="tickets")
    topic = db.relationship("SollusTicketTopic")
    queue = db.relationship("SollusTicketQueue")
    team = db.relationship("SollusTicketTeam")
    sla = db.relationship("SollusTicketSLA")
    contact = db.relationship("SollusTicketContact")
    requester = db.relationship("User", foreign_keys=[requester_id])
    assignee = db.relationship("User", foreign_keys=[assignee_id])
    entries = db.relationship(
        "SollusTicketThreadEntry",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="SollusTicketThreadEntry.created_at",
        passive_deletes=True,
    )
    events = db.relationship(
        "SollusTicketEvent",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="SollusTicketEvent.created_at",
        passive_deletes=True,
    )
    collaborators = db.relationship(
        "SollusTicketCollaborator",
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    field_values = db.relationship(
        "SollusTicketFieldValue",
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attachments = db.relationship(
        "SollusTicketAttachment",
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def requester_label(self) -> str:
        if self.contact:
            return self.contact.name or self.contact.email or "-"
        if self.requester:
            return self.requester.name or self.requester.email
        return "-"

    @property
    def is_closed(self) -> bool:
        return self.status_key in {"closed", "resolved", "archived"}


class SollusTicketThreadEntry(db.Model):
    __tablename__ = "sollus_ticket_thread_entries"
    __table_args__ = (
        db.Index("ix_sollus_ticket_thread_entries_ticket_created", "ticket_id", "created_at"),
        db.UniqueConstraint("legacy_entry_id", name="uq_sollus_ticket_thread_entries_legacy_entry_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    legacy_entry_id = db.Column(db.Integer)
    ticket_id = db.Column(db.Integer, db.ForeignKey("sollus_tickets.id", ondelete="CASCADE"), nullable=False)
    author_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    contact_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_contacts.id", ondelete="SET NULL"))
    type = db.Column(db.String(30), nullable=False, default="message")
    visibility = db.Column(db.String(20), nullable=False, default="public")
    title = db.Column(db.String(255))
    body = db.Column(db.Text, nullable=False)
    email_message_id = db.Column(db.String(500))
    email_references = db.Column(db.Text)
    mail_flags_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    edited_at = db.Column(db.DateTime, nullable=True)
    edited_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    ticket = db.relationship("SollusTicket", back_populates="entries")
    author = db.relationship("User", foreign_keys="[SollusTicketThreadEntry.author_user_id]")
    editor = db.relationship("User", foreign_keys="[SollusTicketThreadEntry.edited_by_id]")
    contact = db.relationship("SollusTicketContact")
    attachments = db.relationship(
        "SollusTicketAttachment",
        back_populates="entry",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    edit_history = db.relationship(
        "SollusTicketThreadEntryHistory",
        back_populates="entry",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SollusTicketThreadEntryHistory.created_at",
    )


class SollusTicketThreadEntryHistory(db.Model):
    """Stores previous body text whenever a thread entry is edited."""
    __tablename__ = "sollus_ticket_thread_entry_history"

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(
        db.Integer,
        db.ForeignKey("sollus_ticket_thread_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body_before = db.Column(db.Text, nullable=False)
    edited_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    entry = db.relationship("SollusTicketThreadEntry", back_populates="edit_history")
    editor = db.relationship("User")


class SollusTicketAttachment(db.Model):
    __tablename__ = "sollus_ticket_attachments"
    __table_args__ = (
        db.UniqueConstraint("legacy_attachment_id", name="uq_sollus_ticket_attachments_legacy_attachment_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    legacy_attachment_id = db.Column(db.Integer)
    ticket_id = db.Column(db.Integer, db.ForeignKey("sollus_tickets.id", ondelete="CASCADE"), nullable=False)
    entry_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_thread_entries.id", ondelete="CASCADE"))
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255))
    content_type = db.Column(db.String(120))
    size = db.Column(db.Integer)
    storage_path = db.Column(db.String(500))
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ticket = db.relationship("SollusTicket", back_populates="attachments")
    entry = db.relationship("SollusTicketThreadEntry", back_populates="attachments")
    uploaded_by = db.relationship("User")


class SollusTicketFieldValue(db.Model):
    __tablename__ = "sollus_ticket_field_values"
    __table_args__ = (
        db.UniqueConstraint("ticket_id", "field_id", name="uq_sollus_ticket_field_values_ticket_field"),
    )

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("sollus_tickets.id", ondelete="CASCADE"), nullable=False)
    field_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_form_fields.id", ondelete="CASCADE"), nullable=False)
    value = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    ticket = db.relationship("SollusTicket", back_populates="field_values")
    field = db.relationship("SollusTicketFormField")


class SollusTicketCollaborator(db.Model):
    __tablename__ = "sollus_ticket_collaborators"
    __table_args__ = (
        db.UniqueConstraint("ticket_id", "contact_id", name="uq_sollus_ticket_collaborators_contact"),
    )

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("sollus_tickets.id", ondelete="CASCADE"), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_contacts.id", ondelete="CASCADE"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ticket = db.relationship("SollusTicket", back_populates="collaborators")
    contact = db.relationship("SollusTicketContact")


class SollusTicketEvent(db.Model):
    __tablename__ = "sollus_ticket_events"
    __table_args__ = (
        db.Index("ix_sollus_ticket_events_ticket_created", "ticket_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("sollus_tickets.id", ondelete="CASCADE"), nullable=False)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    action = db.Column(db.String(60), nullable=False)
    message = db.Column(db.Text)
    before_value = db.Column(db.Text)
    after_value = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ticket = db.relationship("SollusTicket", back_populates="events")
    actor = db.relationship("User")


class SollusTicketCannedResponse(db.Model):
    __tablename__ = "sollus_ticket_canned_responses"
    __table_args__ = (
        db.UniqueConstraint("slug", name="uq_sollus_ticket_canned_responses_slug"),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    slug = db.Column(db.String(140), nullable=False)
    body = db.Column(db.Text, nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_departments.id", ondelete="SET NULL"))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    department = db.relationship("SollusTicketDepartment")
    created_by = db.relationship("User")


class SollusTicketRolePermission(db.Model):
    __tablename__ = "sollus_ticket_role_permissions"
    __table_args__ = (
        db.UniqueConstraint("role_key", name="uq_sollus_ticket_role_permissions_role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    role_key = db.Column(db.String(40), nullable=False)
    can_view_all = db.Column(db.Boolean, nullable=False, default=False)
    can_assign = db.Column(db.Boolean, nullable=False, default=False)
    can_manage_admin = db.Column(db.Boolean, nullable=False, default=False)
    can_close = db.Column(db.Boolean, nullable=False, default=False)
    can_reopen = db.Column(db.Boolean, nullable=False, default=False)
    can_internal_note = db.Column(db.Boolean, nullable=False, default=False)
    can_transfer = db.Column(db.Boolean, nullable=False, default=False)
    can_delete = db.Column(db.Boolean, nullable=False, default=False)
    can_merge = db.Column(db.Boolean, nullable=False, default=False)
    can_link = db.Column(db.Boolean, nullable=False, default=False)
    can_manage_tasks = db.Column(db.Boolean, nullable=False, default=False)
    can_manage_queues = db.Column(db.Boolean, nullable=False, default=False)
    limit_access = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SollusTicketMailbox(db.Model):
    __tablename__ = "sollus_ticket_mailboxes"
    __table_args__ = (
        db.UniqueConstraint("email", name="uq_sollus_ticket_mailboxes_email"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    protocol = db.Column(db.String(20), nullable=False, default="imap")
    host = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=993)
    username = db.Column(db.String(255), nullable=False)
    password = db.Column(db.String(500), nullable=False)
    folder = db.Column(db.String(120), nullable=False, default="INBOX")
    fetch_frequency_minutes = db.Column(db.Integer, nullable=False, default=5)
    fetch_max = db.Column(db.Integer, nullable=False, default=30)
    postfetch = db.Column(db.String(20), nullable=False, default="nothing")
    archive_folder = db.Column(db.String(120))
    use_ssl = db.Column(db.Boolean, nullable=False, default=True)
    mark_seen = db.Column(db.Boolean, nullable=False, default=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    department_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_departments.id", ondelete="SET NULL"))
    topic_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_topics.id", ondelete="SET NULL"))
    queue_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_queues.id", ondelete="SET NULL"))
    team_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_teams.id", ondelete="SET NULL"))
    sla_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_slas.id", ondelete="SET NULL"))
    last_uid = db.Column(db.Integer, nullable=False, default=0)
    last_sync_at = db.Column(db.DateTime)
    last_error = db.Column(db.Text)
    num_errors = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    department = db.relationship("SollusTicketDepartment")
    topic = db.relationship("SollusTicketTopic")
    queue = db.relationship("SollusTicketQueue")
    team = db.relationship("SollusTicketTeam")
    sla = db.relationship("SollusTicketSLA")


class SollusTicketProcessedEmail(db.Model):
    __tablename__ = "sollus_ticket_processed_emails"
    __table_args__ = (
        db.UniqueConstraint("message_id", name="uq_sollus_ticket_processed_emails_message_id"),
        db.UniqueConstraint("mailbox_id", "uid", name="uq_sollus_ticket_processed_emails_mailbox_uid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    mailbox_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_mailboxes.id", ondelete="CASCADE"), nullable=False)
    ticket_id = db.Column(db.Integer, db.ForeignKey("sollus_tickets.id", ondelete="SET NULL"))
    entry_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_thread_entries.id", ondelete="SET NULL"))
    uid = db.Column(db.Integer, nullable=False)
    source_uid = db.Column(db.String(500))
    message_id = db.Column(db.String(500), nullable=False)
    in_reply_to = db.Column(db.String(500))
    sender = db.Column(db.String(255))
    subject = db.Column(db.String(500))
    received_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    mailbox = db.relationship("SollusTicketMailbox")
    ticket = db.relationship("SollusTicket")
    entry = db.relationship("SollusTicketThreadEntry")


class SollusTicketImportRun(db.Model):
    __tablename__ = "sollus_ticket_import_runs"

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(80), nullable=False, default="osticket")
    status = db.Column(db.String(30), nullable=False, default="running")
    summary = db.Column(db.Text)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)


class SollusTicketDepartmentAccess(db.Model):
    __tablename__ = "sollus_ticket_department_access"
    __table_args__ = (
        db.UniqueConstraint("department_id", "user_id", name="uq_sollus_ticket_dept_access_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_departments.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = db.Column(db.String(40), nullable=False, default="agent")
    is_manager = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    department = db.relationship("SollusTicketDepartment")
    user = db.relationship("User")


class SollusTicketBanlist(db.Model):
    __tablename__ = "sollus_ticket_banlist"
    __table_args__ = (
        db.UniqueConstraint("kind", "value", name="uq_sollus_ticket_banlist_value"),
    )

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(30), nullable=False, default="email")
    value = db.Column(db.String(255), nullable=False)
    reason = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    created_by = db.relationship("User")


class SollusTicketFilterRule(db.Model):
    __tablename__ = "sollus_ticket_filter_rules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    stop_processing = db.Column(db.Boolean, nullable=False, default=False)
    match_all = db.Column(db.Boolean, nullable=False, default=True)
    sender_contains = db.Column(db.String(255))
    subject_contains = db.Column(db.String(255))
    body_contains = db.Column(db.String(255))
    header_contains = db.Column(db.String(255))
    set_priority_key = db.Column(db.String(40))
    set_department_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_departments.id", ondelete="SET NULL"))
    set_topic_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_topics.id", ondelete="SET NULL"))
    set_queue_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_queues.id", ondelete="SET NULL"))
    set_team_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_teams.id", ondelete="SET NULL"))
    set_sla_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_slas.id", ondelete="SET NULL"))
    assign_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    reject_ticket = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    department = db.relationship("SollusTicketDepartment", foreign_keys=[set_department_id])
    topic = db.relationship("SollusTicketTopic")
    queue = db.relationship("SollusTicketQueue")
    team = db.relationship("SollusTicketTeam")
    sla = db.relationship("SollusTicketSLA")
    assignee = db.relationship("User")


class SollusTicketEmailTemplateGroup(db.Model):
    __tablename__ = "sollus_ticket_email_template_groups"
    __table_args__ = (
        db.UniqueConstraint("slug", name="uq_sollus_ticket_template_group_slug"),
    )

    id = db.Column(db.Integer, primary_key=True)
    legacy_id = db.Column(db.Integer)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class SollusTicketEmailTemplate(db.Model):
    __tablename__ = "sollus_ticket_email_templates"
    __table_args__ = (
        db.UniqueConstraint("group_id", "event_key", name="uq_sollus_ticket_template_event"),
    )

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_email_template_groups.id", ondelete="CASCADE"), nullable=False)
    event_key = db.Column(db.String(80), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body_html = db.Column(db.Text, nullable=False)
    body_text = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    suppress_autoreply = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    group = db.relationship("SollusTicketEmailTemplateGroup", backref=db.backref("templates", cascade="all, delete-orphan"))


class SollusTicketCustomQueueColumn(db.Model):
    __tablename__ = "sollus_ticket_queue_columns"

    id = db.Column(db.Integer, primary_key=True)
    queue_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_queues.id", ondelete="CASCADE"), nullable=False)
    field_key = db.Column(db.String(80), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_visible = db.Column(db.Boolean, nullable=False, default=True)

    queue = db.relationship("SollusTicketQueue", backref=db.backref("columns", cascade="all, delete-orphan"))


class SollusTicketCustomQueueSort(db.Model):
    __tablename__ = "sollus_ticket_queue_sorts"

    id = db.Column(db.Integer, primary_key=True)
    queue_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_queues.id", ondelete="CASCADE"), nullable=False)
    field_key = db.Column(db.String(80), nullable=False)
    direction = db.Column(db.String(4), nullable=False, default="desc")
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    queue = db.relationship("SollusTicketQueue", backref=db.backref("sorts", cascade="all, delete-orphan"))


class SollusTicketRelation(db.Model):
    __tablename__ = "sollus_ticket_relations"
    __table_args__ = (
        db.UniqueConstraint("source_ticket_id", "target_ticket_id", "relation_type", name="uq_sollus_ticket_relation"),
    )

    id = db.Column(db.Integer, primary_key=True)
    source_ticket_id = db.Column(db.Integer, db.ForeignKey("sollus_tickets.id", ondelete="CASCADE"), nullable=False)
    target_ticket_id = db.Column(db.Integer, db.ForeignKey("sollus_tickets.id", ondelete="CASCADE"), nullable=False)
    relation_type = db.Column(db.String(30), nullable=False, default="linked")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    source = db.relationship("SollusTicket", foreign_keys=[source_ticket_id], backref=db.backref("outgoing_relations", cascade="all, delete-orphan"))
    target = db.relationship("SollusTicket", foreign_keys=[target_ticket_id], backref=db.backref("incoming_relations", cascade="all, delete-orphan"))
    created_by = db.relationship("User")


class SollusTicketLock(db.Model):
    __tablename__ = "sollus_ticket_locks"
    __table_args__ = (
        db.UniqueConstraint("ticket_id", name="uq_sollus_ticket_lock_ticket"),
    )

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("sollus_tickets.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose = db.Column(db.String(40), nullable=False, default="edit")
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    ticket = db.relationship("SollusTicket", backref=db.backref("lock", uselist=False, cascade="all, delete-orphan"))
    user = db.relationship("User")


class SollusTicketTask(db.Model):
    __tablename__ = "sollus_ticket_tasks"

    id = db.Column(db.Integer, primary_key=True)
    legacy_id = db.Column(db.Integer)
    ticket_id = db.Column(db.Integer, db.ForeignKey("sollus_tickets.id", ondelete="CASCADE"), nullable=False)
    number = db.Column(db.String(32), unique=True)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text)
    status_key = db.Column(db.String(40), nullable=False, default="open")
    priority_key = db.Column(db.String(40), nullable=False, default="normal")
    department_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_departments.id", ondelete="SET NULL"))
    team_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_teams.id", ondelete="SET NULL"))
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    due_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    ticket = db.relationship("SollusTicket", backref=db.backref("tasks", cascade="all, delete-orphan"))
    department = db.relationship("SollusTicketDepartment")
    team = db.relationship("SollusTicketTeam")
    assignee = db.relationship("User", foreign_keys=[assignee_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])


class SollusTicketTaskEntry(db.Model):
    __tablename__ = "sollus_ticket_task_entries"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("sollus_ticket_tasks.id", ondelete="CASCADE"), nullable=False)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    type = db.Column(db.String(30), nullable=False, default="note")
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    task = db.relationship("SollusTicketTask", backref=db.backref("entries", cascade="all, delete-orphan"))
    actor = db.relationship("User")

class SollusTicketSystemLog(db.Model):
    __tablename__ = "sollus_ticket_system_logs"

    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(20), nullable=False, default="info")  # debug, info, warning, error, critical
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text)
    source = db.Column(db.String(100))  # cron, mailer, api, system
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<SollusTicketSystemLog {self.id}: {self.title}>"


class SollusEmailQueue(db.Model):
    __tablename__ = "sollus_email_queue"

    id = db.Column(db.Integer, primary_key=True)
    recipients = db.Column(db.Text, nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    html_body = db.Column(db.Text, nullable=False)
    text_body = db.Column(db.Text, nullable=True)
    reply_to = db.Column(db.String(255), nullable=True)
    extra_headers = db.Column(db.Text, nullable=True)
    attachment_ids = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default="pending")  # pending, sent, failed, skipped
    attempts = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

