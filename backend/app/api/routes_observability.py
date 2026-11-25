"""Audit timeline, security monitor, metrics, architecture and health."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.api.deps import DbDep, SettingsDep, require
from app.architecture import describe
from app.auth.permissions import Permission, Principal
from app.models import AuditEvent
from app.observability.metrics import compute_overview
from app.schemas.api import EventListResponse, EventOut, HealthOut, MetricsOverview

router = APIRouter(prefix="/api", tags=["observability"])

SECURITY_EVENT_TYPES = (
    "security.injection_suspected",
    "tool.authorization_denied",
    "tool.unknown_requested",
    "approval.decision_denied",
    "approval.invalidated",
    "workflow.invalid_transition_blocked",
)


def _query_events(
    db,
    *,
    category: str | None,
    event_type: str | None,
    workflow_id: str | None,
    severity: str | None,
    security_only: bool,
    limit: int,
    offset: int,
) -> EventListResponse:
    stmt = select(AuditEvent)
    count_stmt = select(func.count()).select_from(AuditEvent)
    conditions = []
    if category:
        conditions.append(AuditEvent.category == category)
    if event_type:
        conditions.append(AuditEvent.event_type == event_type)
    if workflow_id:
        conditions.append(AuditEvent.workflow_id == workflow_id)
    if severity:
        conditions.append(AuditEvent.severity == severity)
    if security_only:
        conditions.append(
            (AuditEvent.category == "security")
            | (AuditEvent.authorization_outcome == "denied")
            | (AuditEvent.event_type.in_(SECURITY_EVENT_TYPES))
        )
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(
        stmt.order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).limit(limit).offset(offset)
    )
    return EventListResponse(items=[EventOut.model_validate(e) for e in rows], total=total)


@router.get("/events", response_model=EventListResponse)
def list_events(
    db: DbDep,
    category: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require(Permission.AUDIT_READ)),
) -> EventListResponse:
    return _query_events(
        db,
        category=category,
        event_type=event_type,
        workflow_id=workflow_id,
        severity=severity,
        security_only=False,
        limit=limit,
        offset=offset,
    )


@router.get("/security/events", response_model=EventListResponse)
def security_events(
    db: DbDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require(Permission.SECURITY_READ)),
) -> EventListResponse:
    return _query_events(
        db,
        category=None,
        event_type=None,
        workflow_id=None,
        severity=None,
        security_only=True,
        limit=limit,
        offset=offset,
    )


@router.get("/security/summary")
def security_summary(db: DbDep, _: Principal = Depends(require(Permission.SECURITY_READ))) -> dict:
    rows = db.execute(
        select(AuditEvent.event_type, func.count())
        .where(AuditEvent.event_type.in_(SECURITY_EVENT_TYPES))
        .group_by(AuditEvent.event_type)
    ).all()
    counts = {event_type: 0 for event_type in SECURITY_EVENT_TYPES}
    for event_type, count in rows:
        counts[str(event_type)] = int(count)
    denied_tools = db.execute(
        select(AuditEvent.tool_name, func.count())
        .where(AuditEvent.event_type == "tool.authorization_denied")
        .group_by(AuditEvent.tool_name)
    ).all()
    return {
        "counts": counts,
        "denied_tools": {str(tool): int(count) for tool, count in denied_tools if tool},
        "total_denied": int(
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.authorization_outcome == "denied")
            )
            or 0
        ),
    }


@router.get("/metrics/overview", response_model=MetricsOverview)
def metrics_overview(
    db: DbDep, _: Principal = Depends(require(Permission.METRICS_READ))
) -> MetricsOverview:
    return compute_overview(db)


@router.get("/architecture")
def architecture(
    request: Request, _: Principal = Depends(require(Permission.WORKFLOW_READ))
) -> dict:
    state = request.app.state
    return describe(state.registry, state.provider.describe())


@router.get("/health", response_model=HealthOut)
def health(request: Request, db: DbDep, settings: SettingsDep) -> HealthOut:
    db.execute(select(1))
    return HealthOut(
        status="ok",
        environment=settings.environment,
        database="sqlite" if settings.is_sqlite else "postgresql",
        ai_provider=request.app.state.provider.describe(),
        demo_mode=settings.seed_demo_data and settings.environment != "production",
        version=request.app.version,
    )
