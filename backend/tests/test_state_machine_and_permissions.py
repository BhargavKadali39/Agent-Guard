"""Workflow state machine rules and the permission matrix."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session
from tests.conftest import OPERATOR

from app.agents.orchestrator import WorkflowOrchestrator
from app.auth.permissions import (
    AGENT_PRINCIPAL,
    PERMISSION_MATRIX,
    Permission,
    Role,
    decision_permission_for,
    has_permission,
    permission_matrix_table,
    role_rank,
)
from app.errors import InvalidTransition
from app.models import AuditEvent
from app.workflows.states import (
    CANCELLABLE_STATES,
    IN_FLIGHT_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    WorkflowState,
    can_transition,
    transition_table,
)


def test_transition_table_shape() -> None:
    assert set(TRANSITIONS) == set(WorkflowState)
    for state in TERMINAL_STATES:
        assert TRANSITIONS[state] == frozenset()
    assert can_transition(WorkflowState.CREATED, WorkflowState.ANALYZING)
    assert can_transition(WorkflowState.POLICY_CHECK, WorkflowState.APPROVED)
    assert can_transition(WorkflowState.AWAITING_APPROVAL, WorkflowState.REJECTED)
    assert not can_transition(WorkflowState.CREATED, WorkflowState.COMPLETED)
    assert not can_transition(WorkflowState.AWAITING_APPROVAL, WorkflowState.EXECUTING)
    assert not can_transition(WorkflowState.REJECTED, WorkflowState.APPROVED)
    assert not can_transition(WorkflowState.COMPLETED, WorkflowState.FAILED)
    # EXECUTING can only complete or fail; never skip back to approval.
    assert TRANSITIONS[WorkflowState.EXECUTING] == {WorkflowState.COMPLETED, WorkflowState.FAILED}
    assert WorkflowState.AWAITING_APPROVAL not in IN_FLIGHT_STATES
    assert WorkflowState.AWAITING_APPROVAL in CANCELLABLE_STATES
    assert WorkflowState.COMPLETED not in CANCELLABLE_STATES
    rows = transition_table()
    assert {r["from"] for r in rows} == {s.value for s in WorkflowState}


def test_service_blocks_illegal_transition_and_audits_it(
    orchestrator: WorkflowOrchestrator, db: Session
) -> None:
    workflow = orchestrator.workflows.create(
        customer_id="CUST-1001", message="test", actor=OPERATOR
    )
    db.commit()
    with pytest.raises(InvalidTransition):
        orchestrator.workflows.transition(workflow, WorkflowState.COMPLETED, actor=OPERATOR)
    db.commit()
    blocked = [
        e
        for e in orchestrator.audit.for_workflow(workflow.id)
        if e.event_type == "workflow.invalid_transition_blocked"
    ]
    assert len(blocked) == 1
    assert blocked[0].authorization_outcome == "denied"
    assert blocked[0].payload == {"from": "CREATED", "to": "COMPLETED", "reason": None}
    assert workflow.state == WorkflowState.CREATED


def test_cancel_only_from_cancellable_states(
    orchestrator: WorkflowOrchestrator, db: Session
) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1005",
        message="Backpack ORD-1009 broken zip, refund ₹1,999.",
        actor=OPERATOR,
    )
    assert workflow.state == WorkflowState.COMPLETED
    with pytest.raises(InvalidTransition):
        orchestrator.cancel(workflow.id, actor=OPERATOR, reason="too late")

    waiting, _ = orchestrator.submit(
        customer_id="CUST-1001",
        message="Headphones ORD-1001 damaged, refund ₹8,500.",
        actor=OPERATOR,
    )
    assert waiting.state == WorkflowState.AWAITING_APPROVAL
    cancelled = orchestrator.cancel(waiting.id, actor=OPERATOR, reason="customer withdrew")
    assert cancelled.state == WorkflowState.CANCELLED
    assert all(a.status == "invalidated" for a in cancelled.approvals)


# ------------------------------------------------------------------- permissions
def test_permission_matrix_least_privilege() -> None:
    agent = PERMISSION_MATRIX[Role.AGENT]
    assert Permission.CUSTOMER_UPDATE not in agent
    assert Permission.APPROVAL_DECIDE_STANDARD not in agent
    assert Permission.APPROVAL_DECIDE_SENIOR not in agent
    assert Permission.POLICY_MANAGE not in agent
    assert Permission.WORKFLOW_CREATE not in agent
    assert Permission.REFUND_EXECUTE in agent  # only through the state-gated tool
    assert not AGENT_PRINCIPAL.can(Permission.CUSTOMER_UPDATE)

    operator = PERMISSION_MATRIX[Role.SUPPORT_OPERATOR]
    assert Permission.APPROVAL_DECIDE_STANDARD not in operator
    assert Permission.SECURITY_READ not in operator
    assert Permission.REFUND_EXECUTE not in operator
    assert Permission.WORKFLOW_CREATE in operator

    reviewer = PERMISSION_MATRIX[Role.REVIEWER]
    assert Permission.APPROVAL_DECIDE_STANDARD in reviewer
    assert Permission.APPROVAL_DECIDE_SENIOR not in reviewer

    senior = PERMISSION_MATRIX[Role.SENIOR_REVIEWER]
    assert Permission.APPROVAL_DECIDE_SENIOR in senior
    assert Permission.ADMIN_FAILURE_INJECTION not in senior

    admin = PERMISSION_MATRIX[Role.ADMINISTRATOR]
    assert Permission.ADMIN_FAILURE_INJECTION in admin
    assert Permission.CUSTOMER_UPDATE in admin
    # No human role may execute refunds directly; only the agent via the gated tool.
    for role in (Role.SUPPORT_OPERATOR, Role.REVIEWER, Role.SENIOR_REVIEWER, Role.ADMINISTRATOR):
        assert Permission.REFUND_EXECUTE not in PERMISSION_MATRIX[role]


def test_permission_helpers() -> None:
    assert has_permission("reviewer", "approval:decide:standard")
    assert not has_permission("reviewer", "approval:decide:senior")
    assert not has_permission("nope", "approval:decide:senior")
    assert not has_permission("reviewer", "not:a:permission")
    assert decision_permission_for(Role.REVIEWER) == Permission.APPROVAL_DECIDE_STANDARD
    assert decision_permission_for(Role.SENIOR_REVIEWER) == Permission.APPROVAL_DECIDE_SENIOR
    assert (
        role_rank(Role.ADMINISTRATOR) > role_rank(Role.SENIOR_REVIEWER) > role_rank(Role.REVIEWER)
    )
    table = permission_matrix_table()
    assert len(table) == len(Permission)
    row = next(r for r in table if r["permission"] == "customer:update")
    assert row["roles"]["agent"] is False and row["roles"]["administrator"] is True


def test_audit_events_are_never_lost_on_blocked_transition(db: Session, orchestrator) -> None:
    before = db.query(AuditEvent).count()
    workflow = orchestrator.workflows.create(customer_id="CUST-1002", message="x", actor=OPERATOR)
    db.commit()
    with pytest.raises(InvalidTransition):
        orchestrator.workflows.transition(workflow, WorkflowState.EXECUTING, actor=OPERATOR)
    db.commit()
    assert db.query(AuditEvent).count() == before + 2  # started + blocked
