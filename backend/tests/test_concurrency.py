"""Concurrency guarantees: processing leases, compare-and-swap state changes, racing requests.

Each test uses a *second, independent session* to play the part of another worker or
another HTTP request, which is how these races happen in a real deployment.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session
from tests.conftest import OPERATOR, REVIEWER, SENIOR

from app.agents.mock_provider import MockAIProvider
from app.agents.orchestrator import WorkflowOrchestrator
from app.database import utcnow
from app.errors import (
    ConcurrentUpdateError,
    ConflictError,
    SimulatedInterruption,
    WorkflowBusyError,
)
from app.models import ApprovalStatus, Workflow
from app.workflows.states import WorkflowState


def worker(app, session: Session) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        session,
        settings=app.state.settings,
        provider=MockAIProvider(),
        registry=app.state.registry,
        injector=app.state.injector,
    )


def interrupted_workflow(orchestrator: WorkflowOrchestrator, point: str = "APPROVED") -> str:
    with pytest.raises(SimulatedInterruption) as exc:
        orchestrator.submit(
            customer_id="CUST-1005",
            message="Backpack ORD-1009 broken zip, refund ₹1,999.",
            actor=OPERATOR,
            simulation={"interrupt_after": point},
        )
    return str(exc.value.details["workflow_id"])


# ------------------------------------------------------------------------ leases
def test_lease_is_exclusive_releasable_and_expires(orchestrator: WorkflowOrchestrator, db) -> None:
    workflow_id = interrupted_workflow(orchestrator)
    service = orchestrator.workflows
    assert service.claim(workflow_id, token="a", ttl_seconds=60) is True
    assert service.claim(workflow_id, token="b", ttl_seconds=60) is False
    service.release(workflow_id, token="b")  # not the owner: no effect
    assert service.claim(workflow_id, token="c", ttl_seconds=60) is False
    service.release(workflow_id, token="a")
    assert service.claim(workflow_id, token="d", ttl_seconds=60) is True
    # An expired lease (e.g. its worker crashed) can be taken over.
    db.execute(
        update(Workflow)
        .where(Workflow.id == workflow_id)
        .values(lease_expires_at=utcnow() - timedelta(seconds=1))
    )
    db.commit()
    assert service.claim(workflow_id, token="e", ttl_seconds=60) is True
    service.release(workflow_id, token="e")


def test_resume_while_another_worker_holds_the_lease(app, orchestrator, db) -> None:
    workflow_id = interrupted_workflow(orchestrator)
    other = app.state.session_factory()
    try:
        assert worker(app, other).workflows.claim(workflow_id, token="other", ttl_seconds=60)
        with pytest.raises(WorkflowBusyError):
            orchestrator.resume(workflow_id, actor=REVIEWER)
        # run() does not advance a leased workflow either; it reports and returns.
        assert orchestrator.run(workflow_id).state == WorkflowState.EXECUTING
        assert "workflow.claim_skipped" in [
            e.event_type for e in orchestrator.audit.for_workflow(workflow_id)
        ]
        worker(app, other).workflows.release(workflow_id, token="other")
    finally:
        other.close()
    assert orchestrator.resume(workflow_id, actor=REVIEWER).state == WorkflowState.COMPLETED


def test_resume_busy_is_http_409(
    client: TestClient, app, reviewer_headers, operator_headers
) -> None:
    created = client.post(
        "/api/workflows",
        json={
            "customer_id": "CUST-1004",
            "message": "Charger ORD-1018 stopped working. Refund ₹1,500.",
            "simulation": {"interrupt_after": "APPROVED"},
        },
        headers=operator_headers,
    ).json()
    session = app.state.session_factory()
    try:
        assert worker(app, session).workflows.claim(created["id"], token="x", ttl_seconds=60)
    finally:
        session.close()
    response = client.post(f"/api/workflows/{created['id']}/resume", headers=reviewer_headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "workflow_busy"


# ----------------------------------------------------------- compare-and-swap state
def test_stale_worker_cannot_overwrite_a_newer_state(app, orchestrator, db) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1001",
        message="Headphones ORD-1001 damaged. Refund ₹8,500.",
        actor=OPERATOR,
    )
    assert workflow.state == WorkflowState.AWAITING_APPROVAL
    # Another request cancels the workflow...
    other = app.state.session_factory()
    try:
        worker(app, other).cancel(workflow.id, actor=OPERATOR, reason="customer withdrew")
    finally:
        other.close()
    # ...while this session still holds a stale copy that says AWAITING_APPROVAL.
    assert workflow.state == WorkflowState.AWAITING_APPROVAL
    with pytest.raises(ConcurrentUpdateError):
        orchestrator.workflows.transition(workflow, WorkflowState.APPROVED, actor=REVIEWER)
    db.rollback()
    assert orchestrator.workflows.get(workflow.id).state == WorkflowState.CANCELLED


def test_two_reviewers_cannot_both_decide(app, orchestrator, db) -> None:
    workflow, _ = orchestrator.submit(
        customer_id="CUST-1001",
        message="Headphones ORD-1001 damaged. Refund ₹8,500.",
        actor=OPERATOR,
    )
    approval_id = workflow.approval_id
    first = app.state.session_factory()
    second = app.state.session_factory()
    try:
        # Both reviewers load the pending approval before either decides.
        a, b = worker(app, first), worker(app, second)
        assert a.approvals.get(approval_id).status == ApprovalStatus.PENDING
        assert b.approvals.get(approval_id).status == ApprovalStatus.PENDING
        assert b.workflows.get(workflow.id).state == WorkflowState.AWAITING_APPROVAL
        done = a.decide_approval(approval_id, decision="reject", reviewer=REVIEWER, comment="no")
        assert done.state == WorkflowState.REJECTED
        with pytest.raises(ConflictError):
            b.decide_approval(approval_id, decision="approve", reviewer=SENIOR, comment="yes")
    finally:
        first.close()
        second.close()
    db.expire_all()
    final = orchestrator.workflows.get(workflow.id)
    assert final.state == WorkflowState.REJECTED
    assert final.execution is None
    assert orchestrator.approvals.get(approval_id).decided_by == REVIEWER.id


def test_concurrent_duplicate_submissions_create_one_workflow(app) -> None:
    if app.state.settings.is_sqlite and ":memory:" in app.state.settings.database_url:
        pytest.skip("needs a shared on-disk database")

    def submit(_: int) -> tuple[str, bool]:
        session = app.state.session_factory()
        try:
            workflow, created = worker(app, session).submit(
                customer_id="CUST-1004",
                message="Charger ORD-1018 stopped working. Refund ₹1,500.",
                actor=OPERATOR,
                client_request_id="race-123",
            )
            return workflow.id, created
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(4)))
    assert len({workflow_id for workflow_id, _ in results}) == 1, results
    assert sum(1 for _, created in results if created) == 1, results
    session = app.state.session_factory()
    try:
        assert session.query(Workflow).filter_by(client_request_id="race-123").count() == 1
        orchestrator = worker(app, session)
        assert orchestrator.orders.get("ORD-1018").refunded_paise == 150_000
    finally:
        session.close()
