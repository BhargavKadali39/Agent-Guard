"""Operational metrics computed from stored records (never invented)."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models import ApprovalRequest, ApprovalStatus, AuditEvent, RefundExecution, Workflow
from app.schemas.api import MetricsOverview
from app.workflows.states import WorkflowState


def compute_overview(db: Session, *, days: int = 14) -> MetricsOverview:
    now = utcnow()

    state_rows = db.execute(select(Workflow.state, func.count()).group_by(Workflow.state)).all()
    by_state = {state.value: 0 for state in WorkflowState}
    for state, count in state_rows:
        by_state[str(state)] = int(count)
    total = sum(by_state.values())

    pending_approvals = int(
        db.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(ApprovalRequest.status == ApprovalStatus.PENDING.value)
        )
        or 0
    )
    blocked = int(
        db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.authorization_outcome == "denied")
        )
        or 0
    )
    injections = int(
        db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "security.injection_suspected")
        )
        or 0
    )
    refunded = int(db.scalar(select(func.coalesce(func.sum(RefundExecution.amount_paise), 0))) or 0)

    durations = db.execute(
        select(Workflow.created_at, Workflow.completed_at).where(
            Workflow.state == WorkflowState.COMPLETED.value, Workflow.completed_at.is_not(None)
        )
    ).all()
    avg_duration_ms: float | None = None
    if durations:
        total_ms = sum((done - created).total_seconds() * 1000 for created, done in durations)
        avg_duration_ms = round(total_ms / len(durations), 1)

    since = now - timedelta(days=days - 1)
    recent = db.execute(
        select(Workflow.created_at, Workflow.state).where(Workflow.created_at >= since)
    ).all()
    buckets: dict[str, Counter[str]] = {}
    for offset in range(days):
        day = (since + timedelta(days=offset)).date().isoformat()
        buckets[day] = Counter()
    for created_at, state in recent:
        day = created_at.date().isoformat()
        if day in buckets:
            buckets[day][str(state)] += 1
            buckets[day]["total"] += 1
    per_day = [
        {
            "date": day,
            "total": counts.get("total", 0),
            "completed": counts.get(WorkflowState.COMPLETED.value, 0),
            "rejected": counts.get(WorkflowState.REJECTED.value, 0),
            "failed": counts.get(WorkflowState.FAILED.value, 0),
            "awaiting_approval": counts.get(WorkflowState.AWAITING_APPROVAL.value, 0),
        }
        for day, counts in buckets.items()
    ]

    tiers: Counter[str] = Counter()
    for (decision,) in db.execute(
        select(Workflow.policy_decision).where(Workflow.policy_decision.is_not(None))
    ).all():
        if isinstance(decision, dict):
            tiers[str(decision.get("tier", "unknown"))] += 1

    return MetricsOverview(
        total_workflows=total,
        completed_workflows=by_state[WorkflowState.COMPLETED.value],
        pending_approvals=pending_approvals,
        failed_workflows=by_state[WorkflowState.FAILED.value],
        rejected_workflows=by_state[WorkflowState.REJECTED.value],
        awaiting_approval_workflows=by_state[WorkflowState.AWAITING_APPROVAL.value],
        blocked_unauthorized_actions=blocked,
        injection_attempts_detected=injections,
        average_workflow_duration_ms=avg_duration_ms,
        total_refunded_paise=refunded,
        workflows_by_state=by_state,
        workflows_per_day=per_day,
        policy_outcomes=dict(tiers),
        generated_at=now,
    )
