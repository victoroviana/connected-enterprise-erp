"""SQLAlchemy models for the chamados module."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default="medium")
    status = db.Column(db.String(20), default="open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    user = db.relationship("User", foreign_keys=[user_id], back_populates="tickets")
    assignee = db.relationship("User", foreign_keys=[assignee_id], back_populates="assigned_tickets")
    attachments = db.relationship(
        "Attachment",
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    messages = db.relationship(
        "TicketMessage",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketMessage.created_at",
        passive_deletes=True,
    )


class TicketMessage(db.Model):
    __tablename__ = "ticket_messages"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    public = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ticket = db.relationship("Ticket", back_populates="messages")
    author = db.relationship("User", back_populates="messages", foreign_keys=[author_id])


class Attachment(db.Model):
    __tablename__ = "attachments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    original_name = db.Column(db.String(255))
    filename = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(120))
    size = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploader_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    ticket = db.relationship("Ticket", back_populates="attachments")


try:  # Prefer canonical audit model when available
    from modules.audit.models import AuditLog  # type: ignore
except Exception:  # pragma: no cover - legacy fallback
    class AuditLog(db.Model):
        __tablename__ = "audit_logs"
        __audit_exclude__ = True

        id = db.Column(db.Integer, primary_key=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        actor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
        actor_email = db.Column(db.String(255))
        actor_name = db.Column(db.String(255))
        ip = db.Column(db.String(64))
        ua = db.Column(db.String(255))
        entity_type = db.Column(db.String(80), nullable=False)
        entity_id = db.Column(db.Integer)
        action = db.Column(db.String(40), nullable=False)
        message = db.Column(db.Text)
        before = db.Column(db.Text)
        after = db.Column(db.Text)



class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="todo")
    position = db.Column(db.Integer, nullable=False, default=0)
    due_date = db.Column(db.Date)
    scope_key = db.Column(db.String(64), nullable=False, default="chamados")
    visibility = db.Column(db.String(16), nullable=False, default="public")
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    column_id = db.Column(db.Integer, db.ForeignKey("central_conhecimento_columns.id"))
    completed_at = db.Column(db.DateTime)
    archived_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assignee = db.relationship("User", foreign_keys=[assignee_id], back_populates="tasks")
    author = db.relationship("User", foreign_keys=[author_id])
    column = db.relationship("CentralConhecimentoColumn", back_populates="tasks")
    logs = db.relationship(
        "TaskLog",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskLog.log_date",
    )
    comments = db.relationship(
        "TaskComment",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskComment.created_at",
        passive_deletes=True,
    )

    def as_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "position": self.position,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "scope_key": self.scope_key,
            "visibility": self.visibility,
            "assignee_id": self.assignee_id,
            "assignee_name": (self.assignee.name if self.assignee and self.assignee.name else (self.assignee.email if self.assignee else None)),
            "author_id": self.author_id,
            "column_id": self.column_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
        }


class CentralConhecimentoColumn(db.Model):
    __tablename__ = "central_conhecimento_columns"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    scope_key = db.Column(db.String(64), nullable=False, default="chamados")
    position = db.Column(db.Integer, nullable=False, default=0)
    visibility = db.Column(db.String(16), nullable=False, default="public")
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tasks = db.relationship("Task", back_populates="column")

    def as_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "scope_key": self.scope_key,
            "position": self.position,
            "visibility": self.visibility,
            "author_id": self.author_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TaskLog(db.Model):
    __tablename__ = "task_logs"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False)
    log_date = db.Column(db.Date, nullable=False)
    note = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    task = db.relationship("Task", back_populates="logs")


class TaskComment(db.Model):
    __tablename__ = "task_comments"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    task = db.relationship("Task", back_populates="comments")
    author = db.relationship("User")
    attachments = db.relationship(
        "TaskCommentAttachment",
        back_populates="comment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TaskCommentAttachment(db.Model):
    __tablename__ = "task_comment_attachments"

    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("task_comments.id", ondelete="CASCADE"), nullable=False)
    original_name = db.Column(db.String(255))
    stored_name = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(120))
    size = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    uploader_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    comment = db.relationship("TaskComment", back_populates="attachments")


class Subtask(db.Model):
    __tablename__ = "subtasks"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    work_date = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default="open")
    position = db.Column(db.Integer, nullable=False, default=0)
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    assignee = db.relationship("User")
    flow_nodes = db.relationship(
        "SubtaskFlowNode",
        back_populates="subtask",
        cascade="all, delete-orphan",
    )
    flow_edges = db.relationship(
        "SubtaskFlowEdge",
        back_populates="subtask",
        cascade="all, delete-orphan",
    )

    def as_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "position": self.position,
            "work_date": self.work_date.isoformat() if self.work_date else None,
            "assignee_id": self.assignee_id,
            "assignee_name": (self.assignee.name if self.assignee and getattr(self.assignee, "name", None) else (self.assignee.email if self.assignee else None)),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SubtaskFlowNode(db.Model):
    __tablename__ = "subtask_flow_nodes"

    id = db.Column(db.Integer, primary_key=True)
    subtask_id = db.Column(db.Integer, db.ForeignKey("subtasks.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    shape = db.Column(db.String(20), nullable=False, default="rect")
    color = db.Column(db.String(16), nullable=False, default="#e5e7eb")
    x = db.Column(db.Integer, nullable=False, default=40)
    y = db.Column(db.Integer, nullable=False, default=40)
    w = db.Column(db.Integer, nullable=False, default=180)
    h = db.Column(db.Integer, nullable=False, default=60)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    subtask = db.relationship("Subtask", back_populates="flow_nodes")

    def as_dict(self):
        return {
            "id": self.id,
            "subtask_id": self.subtask_id,
            "title": self.title,
            "body": self.body,
            "shape": self.shape,
            "color": self.color,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SubtaskFlowEdge(db.Model):
    __tablename__ = "subtask_flow_edges"

    id = db.Column(db.Integer, primary_key=True)
    subtask_id = db.Column(db.Integer, db.ForeignKey("subtasks.id", ondelete="CASCADE"), nullable=False)
    from_id = db.Column(db.Integer, db.ForeignKey("subtask_flow_nodes.id", ondelete="CASCADE"), nullable=False)
    to_id = db.Column(db.Integer, db.ForeignKey("subtask_flow_nodes.id", ondelete="CASCADE"), nullable=False)
    label = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    subtask = db.relationship("Subtask", back_populates="flow_edges")
    from_node = db.relationship(
        "SubtaskFlowNode",
        foreign_keys=[from_id],
        backref=db.backref("outgoing_edges", cascade="all, delete-orphan"),
    )
    to_node = db.relationship(
        "SubtaskFlowNode",
        foreign_keys=[to_id],
        backref=db.backref("incoming_edges", cascade="all, delete-orphan"),
    )

    def as_dict(self):
        return {
            "id": self.id,
            "subtask_id": self.subtask_id,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "label": self.label,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

