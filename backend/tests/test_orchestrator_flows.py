"""End-to-end workflow behaviour through the orchestrator (mock provider)."""

from __future__ import annotations

from sqlalchemy.orm import Session
from tests.conftest import OPERATOR, REVIEWER, SENIOR

from app.agents.orchestrator import WorkflowOrchestrator
from app.models import ApprovalReason, ApprovalStatus
from app.policies.engine import PolicyConfig
from app.workflows.states import WorkflowState


def events_of(orchestrator: WorkflowOrchestrator, workflow_id: str) -> list[str]:
    return [e.event_type for e in orchestrator.audit.for_workflow(workflow_id)]


def test_auto_tier_completes_without_human(orchestrator: WorkflowOrchestrator, db: Session) -> None:
    workflow, created = orchestrator.submit(
        customer_id="CUST-1005",
        message="The laptop backpack from ORD-1009 has a broken zip. Please refund ₹1,999.",
        actor=OPERATOR,
    )
    assert created is True
    assert workflow.state == WorkflowState.COMPLETED
    assert workflow.order_id == "ORD-1009"
    assert workflow.verification["amount_paise"] == 199_900
    assert workflow.policy_decision["tier"] == "auto"
    assert workflow.execution is not None and workflow.execution.amount_paise == 199_900
    assert len(workflow.approvals) == 1
    approval = workflow.approvals[0]
    assert approval.auto is True and approval.status == ApprovalStatus.APPROVED
    assert approval.reason == ApprovalReason.AUTO_APPROVAL
    order = orchestrator.orders.get("ORD-1009")
    assert order.refunded_paise == 199_900
    names = events_of(orchestrator, workflow.id)
    for expected in (
        "workflow.started",
        "agent.interpretation_completed",
        "evaluation.verification_completed",
        "policy.evaluated",
        "approval.auto_granted",
        "execution.completed",
    ):
        assert expected in names
    transitions = [
        e.payload["to"]
        for e in orchestrator.audit.for_workflow(workflow.id)
        if e.event_type == "workflow.transition"
    ]
    assert transitions == [
        "ANALYZING",
        "VERIFYING",
        "POLICY_CHECK",
        "APPROVED",
        "EXECUTING",
        "COMPLETED",
    ]
    assert workflow.completed_at is not None and workflow.checkpoint["step"] == "execution_recorded"


def test_reviewer_tier_waits_for_approval(orchestrator: WorkflowOrchestrator) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1001",
        message="I purchased headphones worth ₹8,500 last week (order ORD-1001), but they "
        "arrived damaged. Please process a refund.",
        actor=OPERATOR,
    )
    assert workflow.state == WorkflowState.AWAITING_APPROVAL
    approval = workflow.approvals[0]
    assert approval.status == ApprovalStatus.PENDING
    assert approval.required_role == "reviewer"
    assert approval.reason == ApprovalReason.POLICY_TIER
    assert approval.amount_paise == 850_000
    assert approval.expires_at is not None
    assert workflow.execution is None
    assert orchestrator.orders.get("ORD-1001").refunded_paise == 0


def test_senior_tier(orchestrator: WorkflowOrchestrator) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1003",
        message="Order ORD-1005: the monitor arrived cracked. Full refund of ₹25,000 please.",
        actor=OPERATOR,
    )
    assert workflow.state == WorkflowState.AWAITING_APPROVAL
    assert workflow.approvals[0].required_role == "senior_reviewer"


def test_ineligible_requests_are_rejected_by_policy(orchestrator: WorkflowOrchestrator) -> None:
    outside, _ = orchestrator.submit(
        customer_id="CUST-1002",
        message="I want to return the phone case from ORD-1004, it never fit properly.",
        actor=OPERATOR,
    )
    assert outside.state == WorkflowState.REJECTED
    assert "outside_refund_window" in outside.rejection_reason
    not_delivered, _ = orchestrator.submit(
        customer_id="CUST-1003",
        message="Please refund ORD-1006, I changed my mind about the speaker.",
        actor=OPERATOR,
    )
    assert not_delivered.state == WorkflowState.REJECTED
    assert "order_status_not_eligible:SHIPPED" in not_delivered.rejection_reason
    refunded, _ = orchestrator.submit(
        customer_id="CUST-1006",
        message="Refund my tablet order ORD-1011, it is defective.",
        actor=OPERATOR,
    )
    assert refunded.state == WorkflowState.REJECTED
    assert "already_refunded" in refunded.rejection_reason
    for wf in (outside, not_delivered, refunded):
        assert wf.execution is None and wf.approvals == []


def test_missing_order_details(orchestrator: WorkflowOrchestrator) -> None:
    # CUST-1007 has two refundable delivered orders and names neither.
    ambiguous, _ = orchestrator.submit(
        customer_id="CUST-1007",
        message="The thing I ordered last week stopped working. I want my money back.",
        actor=OPERATOR,
    )
    assert ambiguous.state == WorkflowState.REJECTED
    assert ambiguous.rejection_reason.startswith("order_not_identified")
    assert "order_ambiguous" in ambiguous.verification["discrepancies"]
    assert "evaluation.verification_failed" in events_of(orchestrator, ambiguous.id)

    # CUST-1006 has exactly one refundable order left, so it is inferred.
    inferred, _ = orchestrator.submit(
        customer_id="CUST-1006",
        message="It stopped working after a week, I want a refund.",
        actor=OPERATOR,
    )
    assert inferred.order_id == "ORD-1012"
    assert "order_inferred_from_customer_history" in inferred.verification["flags"]
    assert "amount_defaulted_to_refundable_balance" in inferred.verification["flags"]
    assert inferred.state == WorkflowState.COMPLETED  # ₹1,500 auto tier

    # An order that belongs to another customer is never used.
    foreign, _ = orchestrator.submit(
        customer_id="CUST-1008",
        message="Refund ORD-1001 please, the headphones are damaged.",
        actor=OPERATOR,
    )
    assert foreign.state == WorkflowState.REJECTED
    assert "order_not_found_or_not_owned:ORD-1001" in foreign.verification["discrepancies"]


def test_conflicting_statements_require_human_review(orchestrator: WorkflowOrchestrator) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1005",
        message="I paid Rs. 1,200 for the backpack (ORD-1009), actually it was ₹1,500. The zip "
        "broke, I want my money back.",
        actor=OPERATOR,
    )
    assert workflow.verification["amount_paise"] == 150_000
    assert "conflicting_statements" in workflow.verification["discrepancies"]
    assert workflow.verification["review_reason"] == ApprovalReason.AGENT_DISCREPANCY
    assert workflow.state == WorkflowState.AWAITING_APPROVAL
    approval = workflow.approvals[0]
    assert approval.required_role == "reviewer"
    assert approval.reason == ApprovalReason.AGENT_DISCREPANCY
    assert approval.details["discrepancies"] == ["conflicting_statements"]


def test_low_confidence_forces_review(orchestrator: WorkflowOrchestrator) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1005",
        message="Refund ORD-1009, ₹1,999 please.",
        actor=OPERATOR,
        simulation={"provider_fault": "low_confidence"},
    )
    assert "low_confidence" in workflow.verification["flags"]
    assert workflow.state == WorkflowState.AWAITING_APPROVAL
    assert workflow.approvals[0].reason == ApprovalReason.LOW_CONFIDENCE


def test_non_refund_intent_is_flagged_as_discrepancy(orchestrator: WorkflowOrchestrator) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1005",
        message="Where is my order ORD-1009? When will it arrive?",
        actor=OPERATOR,
    )
    assert workflow.interpretation["intent"] == "order_status_inquiry"
    assert "intent_not_refund:order_status_inquiry" in workflow.verification["discrepancies"]
    # A human decides; nothing is executed automatically.
    assert workflow.state == WorkflowState.AWAITING_APPROVAL
    assert workflow.execution is None


def test_exception_override_routes_ineligible_requests_to_senior(
    orchestrator: WorkflowOrchestrator, db: Session
) -> None:
    orchestrator.policies.publish(PolicyConfig(allow_exception_override=True), created_by="test")
    db.commit()
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1002",
        message="I want to return the phone case from ORD-1004, it never fit properly.",
        actor=OPERATOR,
    )
    assert workflow.state == WorkflowState.AWAITING_APPROVAL
    approval = workflow.approvals[0]
    assert approval.required_role == "senior_reviewer"
    assert approval.reason == ApprovalReason.POLICY_EXCEPTION
    assert workflow.policy_decision["eligible"] is False
    assert workflow.policy_decision["policy_version"] == 2
    # Only a senior reviewer may grant the exception.
    import pytest

    from app.errors import PermissionDenied

    with pytest.raises(PermissionDenied):
        orchestrator.decide_approval(
            approval.id, decision="approve", reviewer=REVIEWER, comment=None
        )
    done = orchestrator.decide_approval(
        approval.id, decision="approve", reviewer=SENIOR, comment="goodwill"
    )
    assert done.state == WorkflowState.COMPLETED
    assert done.execution.amount_paise == 49_900


def test_client_request_id_is_idempotent(orchestrator: WorkflowOrchestrator) -> None:
    first, created1 = orchestrator.submit(
        customer_id="CUST-1004",
        message="Charger ORD-1018 dead. Refund ₹1,500.",
        actor=OPERATOR,
        client_request_id="req-123",
    )
    second, created2 = orchestrator.submit(
        customer_id="CUST-1004",
        message="Charger ORD-1018 dead. Refund ₹1,500.",
        actor=OPERATOR,
        client_request_id="req-123",
    )
    assert created1 is True and created2 is False
    assert first.id == second.id
    assert "workflow.duplicate_submission_ignored" in events_of(orchestrator, first.id)
    assert orchestrator.orders.get("ORD-1018").refunded_paise == 150_000
