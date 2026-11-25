"""Workflow persistence and controlled state transitions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.auth.permissions import Principal
from app.database import utcnow
from app.errors import ConcurrentUpdateError, InvalidTransition, NotFoundError, ValidationFailed
from app.models import Customer, EventCategory, Severity, Workflow
from app.observability.audit import AuditLogger
from app.workflows.states import (
    CANCELLABLE_STATES,
    IN_FLIGHT_STATES,
    TERMINAL_STATES,
    WorkflowState,
    can_transition,
)


class WorkflowService:
    def __init__(self, db: Session, audit: AuditLogger) -> None:
        self.db = db
        self.audit = audit

    # ----------------------------------------------------------------- queries
    def get(self, workflow_id: str) -> Workflow:
        # populate_existing refreshes an already-loaded instance (and its approvals /
        # execution collections) so callers always see the latest committed state.
        workflow = self.db.scalars(
            select(Workflow)
            .where(Workflow.id == workflow_id)
            .options(selectinload(Workflow.approvals), selectinload(Workflow.execution))
            .execution_options(populate_existing=True)
        ).first()
        if workflow is None:
            raise NotFoundError(f"workflow {workflow_id} not found")
        return workflow

    def find_by_client_request_id(self, client_request_id: str) -> Workflow | None:
        return self.db.scalars(
            select(Workflow).where(Workflow.client_request_id == client_request_id)
        ).first()

    def list(
        self,
        *,
        state: str | None = None,
        customer_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Workflow], int]:
        stmt = select(Workflow)
        count_stmt = select(func.count()).select_from(Workflow)
        if state:
            stmt = stmt.where(Workflow.state == state)
            count_stmt = count_stmt.where(Workflow.state == state)
        if customer_id:
            stmt = stmt.where(Workflow.customer_id == customer_id)
            count_stmt = count_stmt.where(Workflow.customer_id == customer_id)
        stmt = (
            stmt.order_by(Workflow.created_at.desc())
            .limit(limit)
            .offset(offset)
            .options(selectinload(Workflow.approvals), selectinload(Workflow.execution))
        )
        total = self.db.scalar(count_stmt) or 0
        return list(self.db.scalars(stmt)), int(total)

    def in_flight(self) -> list[Workflow]:
        return list(
            self.db.scalars(
                select(Workflow).where(Workflow.state.in_([s.value for s in IN_FLIGHT_STATES]))
            )
        )

    # ---------------------------------------------------------------- creation
    def create(
        self,
        *,
        customer_id: str,
        message: str,
        actor: Principal,
        client_request_id: str | None = None,
        simulation: dict[str, Any] | None = None,
        provider_name: str = "mock",
    ) -> Workflow:
        message = message.strip()
        if not message:
            raise ValidationFailed("message must not be empty")
        if len(message) > 4000:
            raise ValidationFailed("message is too long (max 4000 characters)")
        if self.db.get(Customer, customer_id) is None:
            raise NotFoundError(f"customer {customer_id} not found")
        workflow = Workflow(
            customer_id=customer_id,
            message=message,
            state=WorkflowState.CREATED.value,
            created_by=actor.id,
            client_request_id=client_request_id,
            simulation=simulation,
            provider_name=provider_name,
            checkpoint={"step": "created", "context": {}},
        )
        self.db.add(workflow)
        self.db.flush()
        self.audit.record(
            category=EventCategory.WORKFLOW,
            event_type="workflow.started",
            message=f"Refund workflow created for customer {customer_id}",
            actor=actor,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            payload={
                "customer_id": customer_id,
                "client_request_id": client_request_id,
                "message_length": len(message),
                "simulation": simulation,
                "provider": provider_name,
            },
        )
        return workflow

    # ------------------------------------------------------------- transitions
    def transition(
        self,
        workflow: Workflow,
        target: WorkflowState,
        *,
        actor: Principal,
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Workflow:
        current = WorkflowState(workflow.state)
        if not can_transition(current, target):
            self.audit.record(
                category=EventCategory.SECURITY,
                event_type="workflow.invalid_transition_blocked",
                severity=Severity.WARNING,
                message=f"Blocked illegal transition {current.value} -> {target.value}",
                actor=actor,
                workflow_id=workflow.id,
                workflow_state=workflow.state,
                authorization_outcome="denied",
                payload={"from": current.value, "to": target.value, "reason": reason},
            )
            raise InvalidTransition(
                f"cannot transition workflow from {current.value} to {target.value}",
                details={"from": current.value, "to": target.value},
            )
        now = utcnow()
        values: dict[str, Any] = {"state": target.value, "updated_at": now}
        if target in TERMINAL_STATES:
            values["completed_at"] = now
        if target == WorkflowState.REJECTED and reason:
            values["rejection_reason"] = reason
        if target == WorkflowState.FAILED and reason:
            values["failure_reason"] = reason
        if target != WorkflowState.FAILED:
            values["resumable"] = False
        # Flush pending attribute changes first, then perform a compare-and-swap: the row
        # only changes if it is still in the state this process believes it is in. A stale
        # worker therefore can never overwrite a newer state.
        self.db.flush()
        result = self.db.execute(
            update(Workflow)
            .where(Workflow.id == workflow.id, Workflow.state == current.value)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise ConcurrentUpdateError(
                f"workflow changed concurrently; expected state {current.value}",
                details={"expected_state": current.value, "target": target.value},
            )
        for key, value in values.items():
            set_committed_value(workflow, key, value)
        self.audit.record(
            category=EventCategory.WORKFLOW,
            event_type="workflow.transition",
            severity=Severity.ERROR if target == WorkflowState.FAILED else Severity.INFO,
            message=f"{current.value} -> {target.value}" + (f" ({reason})" if reason else ""),
            actor=actor,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            payload={
                "from": current.value,
                "to": target.value,
                "reason": reason,
                **(payload or {}),
            },
        )
        return workflow

    # ------------------------------------------------------------------- lease
    def claim(self, workflow_id: str, *, token: str, ttl_seconds: int) -> bool:
        """Atomically take the processing lease if it is free or expired. Commits."""
        now = utcnow()
        result = self.db.execute(
            update(Workflow)
            .where(
                Workflow.id == workflow_id,
                or_(Workflow.lease_token.is_(None), Workflow.lease_expires_at < now),
            )
            .values(lease_token=token, lease_expires_at=now + timedelta(seconds=ttl_seconds))
            .execution_options(synchronize_session=False)
        )
        self.db.commit()
        return result.rowcount == 1

    def release(self, workflow_id: str, *, token: str) -> None:
        """Release the lease, but only if this token still owns it. Commits."""
        self.db.execute(
            update(Workflow)
            .where(Workflow.id == workflow_id, Workflow.lease_token == token)
            .values(lease_token=None, lease_expires_at=None)
            .execution_options(synchronize_session=False)
        )
        self.db.commit()

    def checkpoint(self, workflow: Workflow, step: str, **context: Any) -> None:
        """Persist progress so an interrupted workflow can resume from here."""
        existing = dict(workflow.checkpoint or {})
        merged_context = dict(existing.get("context") or {})
        merged_context.update(context)
        workflow.checkpoint = {
            "step": step,
            "context": merged_context,
            "saved_at": utcnow().isoformat(),
        }
        self.db.add(workflow)
        self.db.flush()

    def mark_failed(
        self, workflow: Workflow, *, reason: str, resumable: bool, actor: Principal
    ) -> Workflow:
        resume_target = workflow.state
        self.transition(
            workflow,
            WorkflowState.FAILED,
            actor=actor,
            reason=reason,
            payload={"resumable": resumable, "resume_target": resume_target},
        )
        workflow.resumable = resumable
        checkpoint = dict(workflow.checkpoint or {})
        checkpoint["resume_target"] = resume_target
        workflow.checkpoint = checkpoint
        self.db.add(workflow)
        self.db.flush()
        return workflow

    def cancel(self, workflow: Workflow, *, actor: Principal, reason: str) -> Workflow:
        current = WorkflowState(workflow.state)
        if current not in CANCELLABLE_STATES:
            raise InvalidTransition(
                f"workflow in state {current.value} cannot be cancelled",
                details={"state": current.value},
            )
        return self.transition(workflow, WorkflowState.CANCELLED, actor=actor, reason=reason)
