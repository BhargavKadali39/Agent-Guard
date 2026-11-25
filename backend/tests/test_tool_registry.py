"""Tool registry: authorization gate, validation, scoping, retries and auditing."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import Session
from tests.conftest import ADMIN, OPERATOR

from app.agents.orchestrator import WorkflowOrchestrator
from app.auth.permissions import AGENT_PRINCIPAL, Permission
from app.errors import (
    ToolAuthorizationError,
    ToolExecutionError,
    TransientToolError,
    ValidationFailed,
)
from app.tools.registry import ToolRegistry, ToolSpec
from app.workflows.states import WorkflowState


def _events(orchestrator: WorkflowOrchestrator, workflow_id: str, event_type: str):
    return [e for e in orchestrator.audit.for_workflow(workflow_id) if e.event_type == event_type]


@pytest.fixture
def workflow(orchestrator: WorkflowOrchestrator, db: Session):
    wf = orchestrator.workflows.create(
        customer_id="CUST-1001", message="Headphones ORD-1001 damaged", actor=OPERATOR
    )
    orchestrator.workflows.transition(wf, WorkflowState.ANALYZING, actor=OPERATOR)
    db.commit()
    return wf


def test_unknown_tool_is_denied_and_audited(orchestrator, workflow, db) -> None:
    ctx = orchestrator._ctx(workflow)
    with pytest.raises(ToolAuthorizationError):
        orchestrator.registry.execute("drop_database", {}, ctx)
    db.commit()
    assert len(_events(orchestrator, workflow.id, "tool.unknown_requested")) == 1


def test_permission_gate_blocks_agent_from_admin_tool(orchestrator, workflow, db) -> None:
    ctx = orchestrator._ctx(workflow, AGENT_PRINCIPAL)
    with pytest.raises(ToolAuthorizationError) as exc:
        orchestrator.registry.execute(
            "update_customer_record", {"customer_id": "CUST-1001", "changes": {"tier": "vip"}}, ctx
        )
    assert exc.value.details["permission"] == Permission.CUSTOMER_UPDATE.value
    db.commit()
    denied = _events(orchestrator, workflow.id, "tool.authorization_denied")
    assert len(denied) == 1 and denied[0].tool_name == "update_customer_record"
    assert denied[0].authorization_outcome == "denied"
    customer = orchestrator.customers.get("CUST-1001")
    assert customer.tier == "premium"

    # The same tool works for an administrator.
    admin_ctx = orchestrator._ctx(workflow, ADMIN)
    result = orchestrator.registry.execute(
        "update_customer_record",
        {"customer_id": "CUST-1001", "changes": {"tier": "vip"}},
        admin_ctx,
    )
    assert result.output["updated_fields"] == ["tier"]


def test_state_gate_blocks_execution_outside_executing(orchestrator, workflow, db) -> None:
    ctx = orchestrator._ctx(workflow)
    with pytest.raises(ToolAuthorizationError) as exc:
        orchestrator.registry.execute(
            "execute_simulated_refund",
            {"order_id": "ORD-1001", "amount_paise": 100, "approval_id": "x" * 36},
            ctx,
        )
    assert exc.value.details["workflow_state"] == WorkflowState.ANALYZING
    assert exc.value.details["allowed_states"] == ["EXECUTING"]
    with pytest.raises(ToolAuthorizationError):
        orchestrator.registry.execute(
            "create_approval_request",
            {"amount_paise": 100, "required_role": "reviewer", "reason": "policy_tier"},
            ctx,
        )


def test_invalid_arguments_are_rejected_before_execution(orchestrator, workflow, db) -> None:
    ctx = orchestrator._ctx(workflow)
    with pytest.raises(ValidationFailed) as exc:
        orchestrator.registry.execute(
            "get_order_information", {"order_id": "ORD-1001", "bypass_policy": True}, ctx
        )
    assert exc.value.details["errors"][0]["loc"] == ["bypass_policy"]
    db.commit()
    assert len(_events(orchestrator, workflow.id, "tool.invalid_arguments")) == 1
    with pytest.raises(ValidationFailed):
        orchestrator.registry.execute("get_order_information", {}, ctx)


def test_data_scoping_denies_other_customers_orders(orchestrator, workflow, db) -> None:
    ctx = orchestrator._ctx(workflow)
    # ORD-1003 belongs to CUST-1002, the workflow is for CUST-1001.
    with pytest.raises(ToolAuthorizationError):
        orchestrator.registry.execute("get_order_information", {"order_id": "ORD-1003"}, ctx)
    with pytest.raises(ToolAuthorizationError):
        orchestrator.registry.execute(
            "evaluate_refund_eligibility", {"order_id": "ORD-1003", "amount_paise": 100}, ctx
        )
    with pytest.raises(ToolAuthorizationError):
        orchestrator.registry.execute("get_customer_details", {"customer_id": "CUST-1002"}, ctx)
    ok = orchestrator.registry.execute("get_order_information", {"order_id": "ORD-1001"}, ctx)
    assert ok.output["customer_id"] == "CUST-1001" and ok.output["refundable_paise"] == 850_000


def test_transient_failures_are_retried_then_succeed(orchestrator, workflow, db) -> None:
    workflow.simulation = {"fail_tool": "retrieve_refund_policy", "fail_times": 2}
    db.add(workflow)
    db.commit()
    ctx = orchestrator._ctx(workflow)
    result = orchestrator.registry.execute("retrieve_refund_policy", {}, ctx)
    assert result.attempts == 3
    db.commit()
    assert len(_events(orchestrator, workflow.id, "tool.retrying")) == 2
    executed = _events(orchestrator, workflow.id, "tool.executed")
    assert executed[-1].payload["attempts"] == 3


def test_retries_are_bounded(orchestrator, workflow, db) -> None:
    workflow.simulation = {"fail_tool": "retrieve_refund_policy", "fail_times": 10}
    db.add(workflow)
    db.commit()
    ctx = orchestrator._ctx(workflow)
    with pytest.raises(TransientToolError):
        orchestrator.registry.execute("retrieve_refund_policy", {}, ctx)
    db.commit()
    assert len(_events(orchestrator, workflow.id, "tool.retrying")) == 2
    assert len(_events(orchestrator, workflow.id, "tool.failed")) == 1
    # Counter was consumed (3 attempts) and persisted.
    db.refresh(workflow)
    assert workflow.simulation["fail_times"] == 7


def test_permanent_failures_are_not_retried(orchestrator, workflow, db) -> None:
    workflow.simulation = {
        "fail_tool": "retrieve_refund_policy",
        "fail_times": 1,
        "fail_mode": "permanent",
    }
    db.add(workflow)
    db.commit()
    ctx = orchestrator._ctx(workflow)
    with pytest.raises(ToolExecutionError) as exc:
        orchestrator.registry.execute("retrieve_refund_policy", {}, ctx)
    assert exc.value.retryable is False
    db.commit()
    assert _events(orchestrator, workflow.id, "tool.retrying") == []


def test_handler_crash_is_contained(orchestrator, workflow, db) -> None:
    class Empty(BaseModel):
        pass

    def boom(_ctx, _args):
        raise RuntimeError("kaboom")

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="explode",
            description="test",
            input_model=Empty,
            output_model=Empty,
            permission=Permission.WORKFLOW_READ,
            handler=boom,
        )
    )
    with pytest.raises(ToolExecutionError) as exc:
        registry.execute("explode", {}, orchestrator._ctx(workflow))
    assert exc.value.retryable is False
    with pytest.raises(ValueError):
        registry.register(registry.get("explode"))  # duplicates refused


def test_registry_descriptors_expose_security_metadata(orchestrator) -> None:
    descriptors = {d["name"]: d for d in orchestrator.registry.descriptors()}
    assert set(descriptors) == {
        "get_customer_details",
        "get_order_information",
        "retrieve_refund_policy",
        "evaluate_refund_eligibility",
        "create_approval_request",
        "check_approval_status",
        "execute_simulated_refund",
        "get_workflow_status",
        "update_customer_record",
    }
    execute = descriptors["execute_simulated_refund"]
    assert execute["permission"] == "refund:execute"
    assert execute["allowed_states"] == ["EXECUTING"]
    assert execute["side_effect"] is True and execute["idempotent"] is True
    assert "approval_id" in execute["input_schema"]["properties"]
    assert execute["input_schema"]["additionalProperties"] is False
    assert descriptors["update_customer_record"]["max_attempts"] == 1


def test_global_retry_cap_applies(app, db: Session) -> None:
    from app.agents.mock_provider import MockAIProvider

    settings = app.state.settings.model_copy(update={"tool_max_attempts": 1})
    capped = WorkflowOrchestrator(
        db,
        settings=settings,
        provider=MockAIProvider(),
        registry=app.state.registry,
        injector=app.state.injector,
    )
    wf = capped.workflows.create(customer_id="CUST-1001", message="x", actor=OPERATOR)
    capped.workflows.transition(wf, WorkflowState.ANALYZING, actor=OPERATOR)
    wf.simulation = {"fail_tool": "retrieve_refund_policy", "fail_times": 1}
    db.add(wf)
    db.commit()
    with pytest.raises(TransientToolError):
        capped.registry.execute("retrieve_refund_policy", {}, capped._ctx(wf))
    db.commit()
    assert _events(capped, wf.id, "tool.retrying") == []
