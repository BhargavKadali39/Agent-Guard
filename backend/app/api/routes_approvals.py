"""Approval Center endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbDep, OrchestratorDep, require
from app.api.serializers import serialize_approval, serialize_approvals, serialize_workflow
from app.auth.permissions import Permission, Principal
from app.schemas.api import ApprovalDecision, ApprovalOut, WorkflowOut

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalOut])
def list_approvals(
    db: DbDep,
    orchestrator: OrchestratorDep,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require(Permission.APPROVAL_READ)),
) -> list[ApprovalOut]:
    return serialize_approvals(db, orchestrator.approvals.list(status=status, limit=limit))


@router.get("/{approval_id}", response_model=ApprovalOut)
def get_approval(
    approval_id: str,
    db: DbDep,
    orchestrator: OrchestratorDep,
    _: Principal = Depends(require(Permission.APPROVAL_READ)),
) -> ApprovalOut:
    return serialize_approval(db, orchestrator.approvals.get(approval_id))


@router.post("/{approval_id}/decide", response_model=WorkflowOut)
def decide_approval(
    approval_id: str,
    body: ApprovalDecision,
    db: DbDep,
    orchestrator: OrchestratorDep,
    # Any authenticated staff user may *attempt* a decision; the approval service checks
    # whether their role satisfies the approval's required role and records denials.
    principal: Principal = Depends(require(Permission.APPROVAL_READ)),
) -> WorkflowOut:
    workflow = orchestrator.decide_approval(
        approval_id, decision=body.decision, reviewer=principal, comment=body.comment
    )
    return serialize_workflow(db, workflow)
