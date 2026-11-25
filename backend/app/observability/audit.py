"""Audit trail: structured, queryable events for every meaningful action.

Events are written in the *same* database session as the business change they describe,
so a committed state change always has its audit record and a rolled-back one never does.
Payloads are kept free of unnecessary personal data: identifiers and amounts, not emails.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.permissions import Principal
from app.database import utcnow
from app.models import AuditEvent, AuthorizationOutcome, EventCategory, Severity

logger = logging.getLogger("agentguard.audit")

_SENSITIVE_KEYS = {"email", "phone", "address", "password", "password_hash", "token", "api_key"}


def sanitize(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop keys that should never land in audit logs."""
    if payload is None:
        return None
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in _SENSITIVE_KEYS:
            clean[key] = "[redacted]"
        elif isinstance(value, dict):
            clean[key] = sanitize(value)
        else:
            clean[key] = value
    return clean


class AuditLogger:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        category: EventCategory | str,
        event_type: str,
        message: str,
        actor: Principal,
        workflow_id: str | None = None,
        workflow_state: str | None = None,
        severity: Severity | str = Severity.INFO,
        tool_name: str | None = None,
        duration_ms: int | None = None,
        authorization_outcome: AuthorizationOutcome | str = AuthorizationOutcome.NOT_APPLICABLE,
        payload: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            workflow_id=workflow_id,
            timestamp=timestamp or utcnow(),
            category=str(category),
            event_type=event_type,
            severity=str(severity),
            actor_type=actor.type,
            actor_id=actor.id,
            tool_name=tool_name,
            duration_ms=duration_ms,
            authorization_outcome=str(authorization_outcome),
            workflow_state=workflow_state,
            message=message,
            payload=sanitize(payload),
        )
        self.db.add(event)
        self.db.flush()
        logger.info(
            message,
            extra={
                "event_type": event_type,
                "category": str(category),
                "workflow_id": workflow_id,
                "actor": actor.id,
                "authorization": str(authorization_outcome),
                "tool": tool_name,
            },
        )
        return event

    def for_workflow(self, workflow_id: str) -> list[AuditEvent]:
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.workflow_id == workflow_id)
            .order_by(AuditEvent.timestamp.asc(), AuditEvent.id.asc())
        )
        return list(self.db.scalars(stmt))
