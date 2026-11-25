"""Human-in-the-loop approvals.

An approval is bound to one workflow, one action, one order and one amount via a
fingerprint. It expires, it can be invalidated when the underlying request changes, and
only a reviewer whose role satisfies ``required_role`` can decide it. Every decision is
recorded with the authenticated reviewer's identity.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.auth.permissions import (
    SYSTEM_PRINCIPAL,
    Principal,
    Role,
    decision_permission_for,
)
from app.database import utcnow
from app.errors import ConflictError, NotFoundError, PermissionDenied, ValidationFailed
from app.models import (
    ApprovalReason,
    ApprovalRequest,
    ApprovalStatus,
    AuthorizationOutcome,
    EventCategory,
    Severity,
    Workflow,
)
from app.observability.audit import AuditLogger
from app.workflows.states import WorkflowState

REFUND_ACTION = "execute_refund"


def approval_fingerprint(
    *, workflow_id: str, action: str, order_id: str | None, amount_paise: int
) -> str:
    raw = f"{workflow_id}|{action}|{order_id}|{amount_paise}"
    return hashlib.sha256(raw.encode()).hexdigest()


class ApprovalService:
    def __init__(self, db: Session, audit: AuditLogger, *, expiry_hours: int = 72) -> None:
        self.db = db
        self.audit = audit
        self.expiry_hours = expiry_hours

    # ----------------------------------------------------------------- queries
    def get(self, approval_id: str) -> ApprovalRequest:
        approval = self.db.get(ApprovalRequest, approval_id)
        if approval is None:
            raise NotFoundError(f"approval {approval_id} not found")
        return approval

    def list(self, *, status: str | None = None, limit: int = 100) -> list[ApprovalRequest]:
        stmt = select(ApprovalRequest).order_by(ApprovalRequest.requested_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(ApprovalRequest.status == status)
        return list(self.db.scalars(stmt))

    def pending_for_workflow(self, workflow_id: str) -> ApprovalRequest | None:
        return self.db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.workflow_id == workflow_id,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
        ).first()

    # ---------------------------------------------------------------- creation
    def create(
        self,
        *,
        workflow: Workflow,
        amount_paise: int,
        required_role: Role,
        reason: ApprovalReason,
        details: dict | None,
        actor: Principal,
    ) -> ApprovalRequest:
        if workflow.order_id is None:
            raise ValidationFailed("cannot request approval without a verified order")
        if required_role not in (Role.REVIEWER, Role.SENIOR_REVIEWER):
            raise ValidationFailed(f"approvals cannot require role {required_role}")
        existing = self.pending_for_workflow(workflow.id)
        if existing is not None:
            return existing
        now = utcnow()
        approval = ApprovalRequest(
            workflow_id=workflow.id,
            action=REFUND_ACTION,
            order_id=workflow.order_id,
            amount_paise=amount_paise,
            currency="INR",
            required_role=required_role.value,
            reason=reason.value,
            details=details,
            status=ApprovalStatus.PENDING.value,
            fingerprint=approval_fingerprint(
                workflow_id=workflow.id,
                action=REFUND_ACTION,
                order_id=workflow.order_id,
                amount_paise=amount_paise,
            ),
            workflow_state_at_request=workflow.state,
            auto=False,
            requested_at=now,
            expires_at=now + timedelta(hours=self.expiry_hours),
        )
        self.db.add(approval)
        self.db.flush()
        self.audit.record(
            category=EventCategory.APPROVAL,
            event_type="approval.requested",
            message=f"Approval requested from {required_role.value} for "
            f"₹{amount_paise / 100:,.2f} ({reason.value})",
            actor=actor,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            payload={
                "approval_id": approval.id,
                "amount_paise": amount_paise,
                "required_role": required_role.value,
                "reason": reason.value,
                "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
            },
        )
        return approval

    def auto_approve(self, *, workflow: Workflow, amount_paise: int) -> ApprovalRequest:
        """System approval for the auto tier, recorded like any other approval."""
        if workflow.order_id is None:
            raise ValidationFailed("cannot auto-approve without a verified order")
        now = utcnow()
        approval = ApprovalRequest(
            workflow_id=workflow.id,
            action=REFUND_ACTION,
            order_id=workflow.order_id,
            amount_paise=amount_paise,
            currency="INR",
            required_role=Role.SUPPORT_OPERATOR.value,
            reason=ApprovalReason.AUTO_APPROVAL.value,
            details={"note": "within auto-approval tier of the active policy"},
            status=ApprovalStatus.APPROVED.value,
            fingerprint=approval_fingerprint(
                workflow_id=workflow.id,
                action=REFUND_ACTION,
                order_id=workflow.order_id,
                amount_paise=amount_paise,
            ),
            workflow_state_at_request=workflow.state,
            auto=True,
            requested_at=now,
            expires_at=None,
            decided_by=SYSTEM_PRINCIPAL.id,
            decided_by_role=SYSTEM_PRINCIPAL.role.value,
            decided_at=now,
            comment="auto-approved by policy engine",
        )
        self.db.add(approval)
        self.db.flush()
        self.audit.record(
            category=EventCategory.APPROVAL,
            event_type="approval.auto_granted",
            message=f"Auto-approved ₹{amount_paise / 100:,.2f} (within policy auto tier)",
            actor=SYSTEM_PRINCIPAL,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            payload={"approval_id": approval.id, "amount_paise": amount_paise},
        )
        return approval

    # ---------------------------------------------------------------- decision
    def decide(
        self,
        approval_id: str,
        *,
        decision: str,
        reviewer: Principal,
        comment: str | None = None,
    ) -> ApprovalRequest:
        if decision not in ("approve", "reject"):
            raise ValidationFailed("decision must be 'approve' or 'reject'")
        approval = self.get(approval_id)
        workflow = self.db.get(Workflow, approval.workflow_id)
        if workflow is None:  # pragma: no cover - FK guarantees this
            raise NotFoundError("workflow for approval not found")

        # 1. Authorization: enforced here, in backend code, regardless of the caller.
        required = Role(approval.required_role)
        permission = decision_permission_for(required)
        if reviewer.type != "user" or not reviewer.can(permission):
            self.audit.record(
                category=EventCategory.SECURITY,
                event_type="approval.decision_denied",
                severity=Severity.WARNING,
                message=f"{reviewer.display_name} ({reviewer.role.value}) is not allowed to "
                f"decide an approval requiring {required.value}",
                actor=reviewer,
                workflow_id=workflow.id,
                workflow_state=workflow.state,
                authorization_outcome=AuthorizationOutcome.DENIED,
                payload={"approval_id": approval.id, "required_role": required.value},
            )
            self.db.commit()  # the denial must be auditable even though the request fails
            raise PermissionDenied(
                f"role {reviewer.role.value} cannot decide approvals requiring {required.value}",
                details={"required_role": required.value},
            )

        # 2. The approval must still be decidable.
        if approval.status != ApprovalStatus.PENDING:
            raise ConflictError(
                f"approval is already {approval.status}", details={"status": approval.status}
            )
        now = utcnow()
        if approval.expires_at is not None and now > approval.expires_at:
            approval.status = ApprovalStatus.EXPIRED.value
            self.db.add(approval)
            self.audit.record(
                category=EventCategory.APPROVAL,
                event_type="approval.expired",
                severity=Severity.WARNING,
                message="Approval expired before a decision was made",
                actor=reviewer,
                workflow_id=workflow.id,
                workflow_state=workflow.state,
                payload={"approval_id": approval.id},
            )
            self.db.commit()
            raise ConflictError("approval has expired", details={"status": "expired"})

        # 3. Binding: the operation must be unchanged since the approval was raised.
        expected = approval_fingerprint(
            workflow_id=workflow.id,
            action=approval.action,
            order_id=workflow.order_id,
            amount_paise=approval.amount_paise,
        )
        if expected != approval.fingerprint or workflow.state != WorkflowState.AWAITING_APPROVAL:
            approval.status = ApprovalStatus.INVALIDATED.value
            self.db.add(approval)
            self.audit.record(
                category=EventCategory.SECURITY,
                event_type="approval.invalidated",
                severity=Severity.WARNING,
                message="Approval invalidated: the underlying request or workflow state changed",
                actor=reviewer,
                workflow_id=workflow.id,
                workflow_state=workflow.state,
                authorization_outcome=AuthorizationOutcome.DENIED,
                payload={"approval_id": approval.id, "workflow_state": workflow.state},
            )
            self.db.commit()
            raise ConflictError(
                "approval no longer matches the request", details={"status": "invalidated"}
            )

        # 4. Record the decision with the reviewer's identity. Compare-and-swap on the
        #    status so two concurrent decisions cannot both succeed.
        values = {
            "status": ApprovalStatus.APPROVED.value
            if decision == "approve"
            else ApprovalStatus.REJECTED.value,
            "decided_by": reviewer.id,
            "decided_by_role": reviewer.role.value,
            "decided_at": now,
            "comment": comment,
        }
        self.db.flush()
        result = self.db.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.id == approval.id,
                ApprovalRequest.status == ApprovalStatus.PENDING.value,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self.db.rollback()
            raise ConflictError(
                "approval was decided by someone else at the same time",
                details={"status": "conflict"},
            )
        for key, value in values.items():
            set_committed_value(approval, key, value)
        self.audit.record(
            category=EventCategory.APPROVAL,
            event_type=f"approval.{approval.status}",
            message=f"{reviewer.display_name} {approval.status} the refund of "
            f"₹{approval.amount_paise / 100:,.2f}",
            actor=reviewer,
            workflow_id=workflow.id,
            workflow_state=workflow.state,
            authorization_outcome=AuthorizationOutcome.ALLOWED,
            payload={
                "approval_id": approval.id,
                "decision": decision,
                "comment": comment,
                "reviewer_role": reviewer.role.value,
            },
        )
        return approval

    def invalidate_pending(self, workflow: Workflow, *, reason: str, actor: Principal) -> int:
        count = 0
        for approval in workflow.approvals:
            if approval.status == ApprovalStatus.PENDING:
                approval.status = ApprovalStatus.INVALIDATED.value
                approval.comment = reason
                self.db.add(approval)
                count += 1
        if count:
            self.audit.record(
                category=EventCategory.APPROVAL,
                event_type="approval.invalidated",
                severity=Severity.WARNING,
                message=f"{count} pending approval(s) invalidated: {reason}",
                actor=actor,
                workflow_id=workflow.id,
                workflow_state=workflow.state,
            )
        return count
