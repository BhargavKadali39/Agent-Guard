"""ORM -> API model conversion helpers (enrich with display names where useful)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApprovalRequest, Customer, Order, User, Workflow
from app.schemas.api import ApprovalOut, ExecutionOut, OrderOut, WorkflowOut


def _display_names(db: Session, user_ids: set[str]) -> dict[str, str]:
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    rows = db.execute(select(User.id, User.display_name).where(User.id.in_(ids))).all()
    names = {uid: name for uid, name in rows}
    names.setdefault("system", "System")
    return names


def serialize_approval(
    db: Session,
    approval: ApprovalRequest,
    *,
    names: dict[str, str] | None = None,
    customers: dict[str, str] | None = None,
) -> ApprovalOut:
    names = names if names is not None else _display_names(db, {approval.decided_by or ""})
    out = ApprovalOut.model_validate(approval)
    out.decided_by_name = (
        names.get(approval.decided_by or "", approval.decided_by) if approval.decided_by else None
    )
    workflow = approval.workflow
    if workflow is not None:
        out.customer_id = workflow.customer_id
        if customers is not None:
            out.customer_name = customers.get(workflow.customer_id)
        else:
            customer = db.get(Customer, workflow.customer_id)
            out.customer_name = customer.name if customer else None
    return out


def serialize_approvals(db: Session, approvals: list[ApprovalRequest]) -> list[ApprovalOut]:
    names = _display_names(db, {a.decided_by or "" for a in approvals})
    customer_ids = {a.workflow.customer_id for a in approvals if a.workflow is not None}
    customers: dict[str, str] = {}
    if customer_ids:
        customers = dict(
            db.execute(
                select(Customer.id, Customer.name).where(Customer.id.in_(customer_ids))
            ).all()
        )
    return [serialize_approval(db, a, names=names, customers=customers) for a in approvals]


def serialize_workflow(
    db: Session, workflow: Workflow, *, interrupted: bool = False
) -> WorkflowOut:
    out = WorkflowOut.model_validate(workflow)
    customer = db.get(Customer, workflow.customer_id)
    out.customer_name = customer.name if customer else None
    names = _display_names(db, {a.decided_by or "" for a in workflow.approvals})
    out.approvals = [
        serialize_approval(
            db, a, names=names, customers={workflow.customer_id: out.customer_name or ""}
        )
        for a in workflow.approvals
    ]
    out.execution = ExecutionOut.model_validate(workflow.execution) if workflow.execution else None
    out.interrupted = interrupted
    return out


def serialize_workflows(db: Session, workflows: list[Workflow]) -> list[WorkflowOut]:
    customer_ids = {w.customer_id for w in workflows}
    customers: dict[str, str] = {}
    if customer_ids:
        customers = dict(
            db.execute(
                select(Customer.id, Customer.name).where(Customer.id.in_(customer_ids))
            ).all()
        )
    names = _display_names(db, {a.decided_by or "" for w in workflows for a in w.approvals})
    items: list[WorkflowOut] = []
    for workflow in workflows:
        out = WorkflowOut.model_validate(workflow)
        out.customer_name = customers.get(workflow.customer_id)
        out.approvals = [
            serialize_approval(db, a, names=names, customers=customers) for a in workflow.approvals
        ]
        out.execution = (
            ExecutionOut.model_validate(workflow.execution) if workflow.execution else None
        )
        items.append(out)
    return items


def serialize_order(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        customer_id=order.customer_id,
        product_id=order.product_id,
        product_name=order.product.name,
        quantity=order.quantity,
        total_paise=order.total_paise,
        refunded_paise=order.refunded_paise,
        refundable_paise=order.refundable_paise,
        status=order.status,
        placed_at=order.placed_at,
        delivered_at=order.delivered_at,
    )
