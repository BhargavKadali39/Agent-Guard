"""Human-in-the-loop approvals: authorization, binding, expiry and finality."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session
from tests.conftest import ADMIN, OPERATOR, REVIEWER, SENIOR

from app.agents.orchestrator import WorkflowOrchestrator
from app.approvals.service import approval_fingerprint
from app.database import utcnow
from app.errors import ConflictError, PermissionDenied, ValidationFailed
from app.models import ApprovalStatus, AuditEvent
from app.workflows.states import WorkflowState


@pytest.fixture
def waiting(orchestrator: WorkflowOrchestrator):
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1001",
        message="Headphones ORD-1001 arrived damaged. Refund ₹8,500 please.",
        actor=OPERATOR,
    )
    assert workflow.state == WorkflowState.AWAITING_APPROVAL
    return workflow


def test_operator_cannot_approve_and_denial_is_audited(orchestrator, waiting, db: Session) -> None:
    approval = waiting.approvals[0]
    with pytest.raises(PermissionDenied):
        orchestrator.decide_approval(
            approval.id, decision="approve", reviewer=OPERATOR, comment=None
        )
    denied = db.query(AuditEvent).filter_by(event_type="approval.decision_denied").all()
    assert len(denied) == 1 and denied[0].actor_id == OPERATOR.id
    assert denied[0].authorization_outcome == "denied"
    db.refresh(approval)
    assert approval.status == ApprovalStatus.PENDING
    assert orchestrator.workflows.get(waiting.id).state == WorkflowState.AWAITING_APPROVAL


def test_agent_principal_cannot_approve(orchestrator, waiting) -> None:
    from app.auth.permissions import AGENT_PRINCIPAL

    with pytest.raises(PermissionDenied):
        orchestrator.decide_approval(
            waiting.approvals[0].id, decision="approve", reviewer=AGENT_PRINCIPAL, comment=None
        )


def test_reviewer_approval_executes_refund_with_identity(orchestrator, waiting) -> None:
    approval = waiting.approvals[0]
    done = orchestrator.decide_approval(
        approval.id, decision="approve", reviewer=REVIEWER, comment="Photos verified."
    )
    assert done.state == WorkflowState.COMPLETED
    assert done.execution is not None and done.execution.approval_id == approval.id
    approval = orchestrator.approvals.get(approval.id)
    assert approval.status == ApprovalStatus.APPROVED
    assert approval.decided_by == REVIEWER.id and approval.decided_by_role == "reviewer"
    assert approval.comment == "Photos verified."
    assert orchestrator.orders.get("ORD-1001").refunded_paise == 850_000


def test_reviewer_cannot_decide_senior_tier(orchestrator) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1004",
        message="Smartwatch ORD-1007 cracked. Refund ₹12,500.",
        actor=OPERATOR,
    )
    approval = workflow.approvals[0]
    assert approval.required_role == "senior_reviewer"
    with pytest.raises(PermissionDenied):
        orchestrator.decide_approval(
            approval.id, decision="approve", reviewer=REVIEWER, comment=None
        )
    done = orchestrator.decide_approval(
        approval.id, decision="approve", reviewer=SENIOR, comment=None
    )
    assert done.state == WorkflowState.COMPLETED
    # Administrators may decide any tier too.
    other, _ = orchestrator.submit(
        customer_id="CUST-1003",
        message="Monitor ORD-1005 cracked. Refund ₹25,000.",
        actor=OPERATOR,
    )
    assert (
        orchestrator.decide_approval(
            other.approvals[0].id, decision="reject", reviewer=ADMIN, comment="no"
        ).state
        == WorkflowState.REJECTED
    )


def test_rejection_is_final(orchestrator, waiting) -> None:
    approval = waiting.approvals[0]
    rejected = orchestrator.decide_approval(
        approval.id, decision="reject", reviewer=REVIEWER, comment="Replacement offered."
    )
    assert rejected.state == WorkflowState.REJECTED
    assert rejected.rejection_reason == "rejected_by_reviewer: Replacement offered."
    assert rejected.execution is None
    with pytest.raises(ConflictError):
        orchestrator.decide_approval(approval.id, decision="approve", reviewer=SENIOR, comment=None)
    # Resume on a terminal workflow is a harmless no-op.
    assert orchestrator.resume(waiting.id, actor=SENIOR).state == WorkflowState.REJECTED
    assert orchestrator.orders.get("ORD-1001").refunded_paise == 0


def test_invalid_decision_value(orchestrator, waiting) -> None:
    with pytest.raises(ValidationFailed):
        orchestrator.decide_approval(
            waiting.approvals[0].id, decision="maybe", reviewer=REVIEWER, comment=None
        )


def test_expired_approval_cannot_be_decided(orchestrator, waiting, db: Session) -> None:
    approval = waiting.approvals[0]
    approval.expires_at = utcnow() - timedelta(minutes=1)
    db.add(approval)
    db.commit()
    with pytest.raises(ConflictError) as exc:
        orchestrator.decide_approval(
            approval.id, decision="approve", reviewer=REVIEWER, comment=None
        )
    assert exc.value.details == {"status": "expired"}
    db.refresh(approval)
    assert approval.status == ApprovalStatus.EXPIRED
    assert db.query(AuditEvent).filter_by(event_type="approval.expired").count() == 1


def test_approval_bound_to_amount_and_order(orchestrator, waiting, db: Session) -> None:
    approval = waiting.approvals[0]
    expected = approval_fingerprint(
        workflow_id=waiting.id, action="execute_refund", order_id="ORD-1001", amount_paise=850_000
    )
    assert approval.fingerprint == expected
    # Tamper with the amount after the approval was raised: the binding breaks.
    approval.amount_paise = 1
    db.add(approval)
    db.commit()
    with pytest.raises(ConflictError) as exc:
        orchestrator.decide_approval(
            approval.id, decision="approve", reviewer=REVIEWER, comment=None
        )
    assert exc.value.details == {"status": "invalidated"}
    db.refresh(approval)
    assert approval.status == ApprovalStatus.INVALIDATED
    assert db.query(AuditEvent).filter_by(event_type="approval.invalidated").count() == 1


def test_refund_service_verifies_binding_independently(orchestrator, waiting, db: Session) -> None:
    """Even with an approved approval, execution re-checks the binding itself."""
    approval = waiting.approvals[0]
    other, _ = orchestrator.submit(
        customer_id="CUST-1005",
        message="Backpack ORD-1009 broken, refund ₹1,999.",
        actor=OPERATOR,
    )
    assert other.state == WorkflowState.COMPLETED
    other_approval = other.approvals[0]  # approved (auto) but for another workflow
    with pytest.raises(ValidationFailed):
        orchestrator.refunds.execute(
            workflow=waiting, approval=other_approval, amount_paise=850_000, actor=OPERATOR
        )
    with pytest.raises(ValidationFailed):  # pending approval
        orchestrator.refunds.execute(
            workflow=waiting, approval=approval, amount_paise=850_000, actor=OPERATOR
        )
    orchestrator.approvals.decide(approval.id, decision="approve", reviewer=REVIEWER)
    with pytest.raises(ValidationFailed):  # wrong amount
        orchestrator.refunds.execute(
            workflow=waiting, approval=approval, amount_paise=100, actor=OPERATOR
        )


def test_cancel_invalidates_pending_approvals(orchestrator, waiting, db: Session) -> None:
    cancelled = orchestrator.cancel(waiting.id, actor=OPERATOR, reason="customer withdrew")
    assert cancelled.state == WorkflowState.CANCELLED
    approval = orchestrator.approvals.get(waiting.approvals[0].id)
    assert approval.status == ApprovalStatus.INVALIDATED
    with pytest.raises(ConflictError):
        orchestrator.decide_approval(
            approval.id, decision="approve", reviewer=REVIEWER, comment=None
        )


def test_pending_approval_is_reused_not_duplicated(orchestrator, waiting) -> None:
    from app.auth.permissions import Role
    from app.models import ApprovalReason

    again = orchestrator.approvals.create(
        workflow=waiting,
        amount_paise=850_000,
        required_role=Role.REVIEWER,
        reason=ApprovalReason.POLICY_TIER,
        details=None,
        actor=OPERATOR,
    )
    assert again.id == waiting.approvals[0].id
    assert (
        orchestrator.approvals.list(status="pending")
        and len([a for a in orchestrator.approvals.list() if a.workflow_id == waiting.id]) == 1
    )
