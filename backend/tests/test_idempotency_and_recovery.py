"""Idempotent execution, retries, interruption and restart recovery."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.conftest import OPERATOR, REVIEWER, SENIOR, make_settings

from app.agents.mock_provider import MockAIProvider
from app.agents.orchestrator import WorkflowOrchestrator
from app.auth.permissions import AGENT_PRINCIPAL
from app.errors import InvalidTransition, SimulatedInterruption
from app.main import create_app
from app.models import RefundExecution, Workflow
from app.workflows.states import WorkflowState


def execution_count(db: Session, workflow_id: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(RefundExecution)
            .where(RefundExecution.workflow_id == workflow_id)
        )
        or 0
    )


def event_types(orchestrator: WorkflowOrchestrator, workflow_id: str) -> list[str]:
    return [e.event_type for e in orchestrator.audit.for_workflow(workflow_id)]


# ----------------------------------------------------------------- idempotency
def test_replaying_execution_has_no_side_effects(orchestrator, db: Session) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1005",
        message="Backpack ORD-1009 broken zip, refund ₹1,999.",
        actor=OPERATOR,
    )
    approval = orchestrator.approvals.get(workflow.approval_id)
    first = orchestrator.refunds.existing_execution(workflow.id)
    for _ in range(3):
        execution, created = orchestrator.refunds.execute(
            workflow=workflow,
            approval=approval,
            amount_paise=approval.amount_paise,
            actor=AGENT_PRINCIPAL,
        )
        assert created is False and execution.id == first.id
    db.commit()
    assert execution_count(db, workflow.id) == 1
    assert orchestrator.orders.get("ORD-1009").refunded_paise == 199_900


def test_database_unique_constraint_blocks_second_execution(orchestrator, db: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    workflow, _ = orchestrator.submit(
        customer_id="CUST-1005",
        message="Backpack ORD-1009 broken zip, refund ₹1,999.",
        actor=OPERATOR,
    )
    existing = orchestrator.refunds.existing_execution(workflow.id)
    duplicate = RefundExecution(
        workflow_id=workflow.id,
        order_id=existing.order_id,
        approval_id=existing.approval_id,
        amount_paise=existing.amount_paise,
        idempotency_key="refund:other-key",
        gateway_reference="SIM-DUP",
        executed_by="test",
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert execution_count(db, workflow.id) == 1


def test_concurrent_resumes_execute_exactly_once(app, db: Session) -> None:
    if app.state.settings.is_sqlite and ":memory:" in app.state.settings.database_url:
        pytest.skip("concurrency needs a shared on-disk database")
    setup = WorkflowOrchestrator(
        db,
        settings=app.state.settings,
        provider=MockAIProvider(),
        registry=app.state.registry,
        injector=app.state.injector,
    )
    with pytest.raises(SimulatedInterruption) as exc:
        setup.submit(
            customer_id="CUST-1005",
            message="Backpack ORD-1009 broken zip, refund ₹1,999.",
            actor=OPERATOR,
            simulation={"interrupt_after": "APPROVED"},
        )
    workflow_id = exc.value.details["workflow_id"]
    assert setup.workflows.get(workflow_id).state == WorkflowState.EXECUTING
    db.commit()

    def resume(_: int) -> str:
        session = app.state.session_factory()
        try:
            worker = WorkflowOrchestrator(
                session,
                settings=app.state.settings,
                provider=MockAIProvider(),
                registry=app.state.registry,
                injector=app.state.injector,
            )
            try:
                return worker.resume(workflow_id, actor=SENIOR).state
            except Exception as error:  # noqa: BLE001 - report instead of hiding
                session.rollback()
                return f"error:{type(error).__name__}"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=5) as pool:
        outcomes = list(pool.map(resume, range(5)))
    db.expire_all()
    final = setup.workflows.get(workflow_id)
    assert final.state == WorkflowState.COMPLETED, outcomes
    assert execution_count(db, workflow_id) == 1
    assert setup.orders.get("ORD-1009").refunded_paise == 199_900
    # Exactly one worker processed it; the others were told it was busy or already done.
    assert final.failure_reason is None, final.failure_reason
    assert set(outcomes) <= {"COMPLETED", "error:WorkflowBusyError"}, outcomes
    assert outcomes.count("COMPLETED") >= 1
    types = event_types(setup, workflow_id)
    assert "workflow.failure_encountered" not in types
    assert types.count("execution.completed") == 1


def test_second_workflow_for_refunded_order_is_rejected(orchestrator) -> None:
    first, _ = orchestrator.submit(
        customer_id="CUST-1005",
        message="Backpack ORD-1009 broken zip, refund ₹1,999.",
        actor=OPERATOR,
    )
    assert first.state == WorkflowState.COMPLETED
    second, _ = orchestrator.submit(
        customer_id="CUST-1005",
        message="Backpack ORD-1009 broken zip, refund ₹1,999.",
        actor=OPERATOR,
    )
    assert second.state == WorkflowState.REJECTED
    assert "already_refunded" in second.rejection_reason


# ------------------------------------------------------------------- retries
def test_transient_gateway_failure_is_retried(orchestrator, db: Session) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1004",
        message="Charger ORD-1018 stopped working. Refund ₹1,500.",
        actor=OPERATOR,
        simulation={"gateway_fail_times": 1},
    )
    assert workflow.state == WorkflowState.COMPLETED
    assert execution_count(db, workflow.id) == 1
    assert "tool.retrying" in event_types(orchestrator, workflow.id)


def test_exhausted_retries_fail_resumably_then_recover(orchestrator, db: Session) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1004",
        message="Charger ORD-1018 stopped working. Refund ₹1,500.",
        actor=OPERATOR,
        simulation={"fail_tool": "execute_simulated_refund", "fail_times": 5},
    )
    assert workflow.state == WorkflowState.FAILED
    assert workflow.resumable is True
    assert workflow.checkpoint["resume_target"] == "EXECUTING"
    assert execution_count(db, workflow.id) == 0
    assert workflow.simulation["fail_times"] == 2  # three attempts consumed and persisted
    resumed = orchestrator.resume(workflow.id, actor=REVIEWER)
    assert resumed.state == WorkflowState.COMPLETED
    assert resumed.resume_count == 1
    assert execution_count(db, workflow.id) == 1
    assert orchestrator.orders.get("ORD-1018").refunded_paise == 150_000


def test_database_failure_before_commit_leaves_no_partial_refund(orchestrator, db: Session) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1004",
        message="Charger ORD-1018 stopped working. Refund ₹1,500.",
        actor=OPERATOR,
        simulation={"db_fail_times": 5},
    )
    assert workflow.state == WorkflowState.FAILED and workflow.resumable
    assert execution_count(db, workflow.id) == 0
    assert orchestrator.orders.get("ORD-1018").refunded_paise == 0
    resumed = orchestrator.resume(workflow.id, actor=REVIEWER)
    assert resumed.state == WorkflowState.COMPLETED
    assert execution_count(db, workflow.id) == 1
    assert orchestrator.orders.get("ORD-1018").refunded_paise == 150_000


def test_permanent_tool_failure_is_recorded(orchestrator, db: Session) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1004",
        message="Charger ORD-1018 stopped working. Refund ₹1,500.",
        actor=OPERATOR,
        # get_customer_details is only called by the pipeline (never proposed by the mock).
        simulation={
            "fail_tool": "get_customer_details",
            "fail_times": 1,
            "fail_mode": "permanent",
        },
    )
    assert workflow.state == WorkflowState.FAILED
    assert "injected failure" in workflow.failure_reason
    assert "workflow.failure_encountered" in event_types(orchestrator, workflow.id)
    assert orchestrator.resume(workflow.id, actor=REVIEWER).state == WorkflowState.COMPLETED


# -------------------------------------------------------------- interruption
@pytest.mark.parametrize(
    ("point", "state_after"),
    [
        ("ANALYZING", WorkflowState.VERIFYING),
        ("VERIFYING", WorkflowState.POLICY_CHECK),
        ("POLICY_CHECK", WorkflowState.APPROVED),
        ("APPROVED", WorkflowState.EXECUTING),
        ("EXECUTION_COMMIT", WorkflowState.EXECUTING),
    ],
)
def test_interruption_then_resume_from_every_point(
    orchestrator, db: Session, point, state_after
) -> None:
    with pytest.raises(SimulatedInterruption) as exc:
        orchestrator.submit(
            customer_id="CUST-1004",
            message="Charger ORD-1018 stopped working. Refund ₹1,500.",
            actor=OPERATOR,
            simulation={"interrupt_after": point},
        )
    workflow_id = exc.value.details["workflow_id"]
    workflow = orchestrator.workflows.get(workflow_id)
    assert workflow.state == state_after
    assert "workflow.interrupted" in event_types(orchestrator, workflow_id)
    expected_before = 1 if point == "EXECUTION_COMMIT" else 0
    assert execution_count(db, workflow_id) == expected_before
    resumed = orchestrator.resume(workflow_id, actor=REVIEWER)
    assert resumed.state == WorkflowState.COMPLETED
    assert execution_count(db, workflow_id) == 1
    assert orchestrator.orders.get("ORD-1018").refunded_paise == 150_000
    if point == "EXECUTION_COMMIT":
        assert "execution.replayed" in event_types(orchestrator, workflow_id)
    assert "workflow.resumed" in event_types(orchestrator, workflow_id)


def test_waiting_workflow_cannot_be_resumed(orchestrator) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1001",
        message="Headphones ORD-1001 damaged. Refund ₹8,500.",
        actor=OPERATOR,
    )
    with pytest.raises(InvalidTransition):
        orchestrator.resume(workflow.id, actor=REVIEWER)


def test_restart_recovers_in_flight_workflows(tmp_path) -> None:
    """Simulate a crash and a process restart against the same database file."""
    settings = make_settings(tmp_path)
    first = create_app(settings, create_schema=True)
    with TestClient(first):
        session = first.state.session_factory()
        orchestrator = WorkflowOrchestrator(
            session,
            settings=settings,
            provider=MockAIProvider(),
            registry=first.state.registry,
            injector=first.state.injector,
        )
        with pytest.raises(SimulatedInterruption) as exc:
            orchestrator.submit(
                customer_id="CUST-1004",
                message="Charger ORD-1018 stopped working. Refund ₹1,500.",
                actor=OPERATOR,
                simulation={"interrupt_after": "APPROVED"},
            )
        workflow_id = exc.value.details["workflow_id"]
        session.close()
    first.state.engine.dispose()

    restarted = create_app(
        make_settings(tmp_path, auto_recover_on_startup=True), create_schema=True
    )
    with TestClient(restarted):
        session = restarted.state.session_factory()
        workflow = session.get(Workflow, workflow_id)
        assert workflow.state == WorkflowState.COMPLETED
        assert execution_count(session, workflow_id) == 1
        types = [
            e.event_type
            for e in WorkflowOrchestrator(
                session,
                settings=settings,
                provider=MockAIProvider(),
                registry=restarted.state.registry,
                injector=restarted.state.injector,
            ).audit.for_workflow(workflow_id)
        ]
        assert "workflow.recovered" in types
        session.close()
    restarted.state.engine.dispose()
