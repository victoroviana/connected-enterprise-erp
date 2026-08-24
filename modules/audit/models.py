"""Persistence layer for audit trails."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class AuditLog(db.Model):
    """Single table storing every tracked change/event."""

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
