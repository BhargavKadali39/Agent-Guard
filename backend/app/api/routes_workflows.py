"""Workflow lifecycle endpoints: submit, inspect, resume, cancel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DbDep, OrchestratorDep, require
from app.api.serializers import serialize_workflow, serialize_workflows
from app.auth.permissions import Permission, Principal
from app.errors import SimulatedInterruption
from app.schemas.api import (
    CancelRequest,
    EventListResponse,
    EventOut,
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowOut,
)
from app.workflows.states import WorkflowState

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
def submit_workflow(
    body: WorkflowCreate,
    response: Response,
    db: DbDep,
    orchestrator: OrchestratorDep,
    principal: Principal = Depends(require(Permission.WORKFLOW_CREATE)),
) -> WorkflowOut:
    """Create a refund workflow and run it until it waits, completes, is rejected or fails.

    Repeating a request with the same ``client_request_id`` returns the existing workflow
    with HTTP 200 instead of creating a duplicate. A simulated interruption returns the
    persisted in-flight workflow with HTTP 202 and ``interrupted=true``.
    """
    simulation = body.simulation.model_dump() if body.simulation else None
    try:
        workflow, created = orchestrator.submit(
            customer_id=body.customer_id,
            message=body.message,
            actor=principal,
            client_request_id=body.client_request_id,
            simulation=simulation,
        )
    except SimulatedInterruption as exc:
        workflow_id = str(exc.details["workflow_id"])
        response.status_code = status.HTTP_202_ACCEPTED
        return serialize_workflow(db, orchestrator.workflows.get(workflow_id), interrupted=True)
    if not created:
        response.status_code = status.HTTP_200_OK
    return serialize_workflow(db, workflow)


@router.get("", response_model=WorkflowListResponse)
def list_workflows(
    db: DbDep,
    orchestrator: OrchestratorDep,
    state: str | None = Query(default=None),
    customer_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require(Permission.WORKFLOW_READ)),
) -> WorkflowListResponse:
    if state is not None:
        WorkflowState(state)  # 422 via ValueError handler if invalid
    items, total = orchestrator.workflows.list(
        state=state, customer_id=customer_id, limit=limit, offset=offset
    )
    return WorkflowListResponse(items=serialize_workflows(db, items), total=total)


@router.get("/{workflow_id}", response_model=WorkflowOut)
def get_workflow(
    workflow_id: str,
    db: DbDep,
    orchestrator: OrchestratorDep,
    _: Principal = Depends(require(Permission.WORKFLOW_READ)),
) -> WorkflowOut:
    return serialize_workflow(db, orchestrator.workflows.get(workflow_id))


@router.get("/{workflow_id}/events", response_model=EventListResponse)
def workflow_events(
    workflow_id: str,
    orchestrator: OrchestratorDep,
    _: Principal = Depends(require(Permission.AUDIT_READ)),
) -> EventListResponse:
    orchestrator.workflows.get(workflow_id)
    events = orchestrator.audit.for_workflow(workflow_id)
    return EventListResponse(items=[EventOut.model_validate(e) for e in events], total=len(events))


@router.post("/{workflow_id}/resume", response_model=WorkflowOut)
def resume_workflow(
    workflow_id: str,
    response: Response,
    db: DbDep,
    orchestrator: OrchestratorDep,
    principal: Principal = Depends(require(Permission.WORKFLOW_RESUME)),
) -> WorkflowOut:
    try:
        workflow = orchestrator.resume(workflow_id, actor=principal)
    except SimulatedInterruption:
        response.status_code = status.HTTP_202_ACCEPTED
        return serialize_workflow(db, orchestrator.workflows.get(workflow_id), interrupted=True)
    return serialize_workflow(db, workflow)


@router.post("/{workflow_id}/cancel", response_model=WorkflowOut)
def cancel_workflow(
    workflow_id: str,
    body: CancelRequest,
    db: DbDep,
    orchestrator: OrchestratorDep,
    principal: Principal = Depends(require(Permission.WORKFLOW_CANCEL)),
) -> WorkflowOut:
    return serialize_workflow(
        db, orchestrator.cancel(workflow_id, actor=principal, reason=body.reason)
    )
