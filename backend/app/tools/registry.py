"""Tool registry: the only way the agent touches business systems.

Every tool declares its purpose, validated input/output schemas, the permission it needs,
the workflow states in which it may run, whether it has side effects and how failures are
handled. ``ToolRegistry.execute`` enforces all of that *before* a handler runs and writes
an audit event for every outcome (allowed, denied, failed, retried).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.approvals.service import ApprovalService
from app.auth.permissions import Permission, Principal
from app.config import Settings
from app.errors import (
    AgentGuardError,
    NotFoundError,
    ToolAuthorizationError,
    ToolExecutionError,
    ValidationFailed,
)
from app.evaluations.failure_injection import FailureInjector
from app.models import AuthorizationOutcome, EventCategory, Severity, Workflow
from app.observability.audit import AuditLogger
from app.policies.engine import PolicyEngine
from app.services.business import RefundService
from app.workflows.states import WorkflowState

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    db: Session
    principal: Principal
    audit: AuditLogger
    injector: FailureInjector
    settings: Settings
    policy_engine: PolicyEngine
    approval_service: ApprovalService
    refund_service: RefundService
    workflow: Workflow | None = None

    @property
    def workflow_state(self) -> str | None:
        return self.workflow.state if self.workflow is not None else None


ToolHandler = Callable[[ToolContext, Any], BaseModel]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    permission: Permission
    handler: ToolHandler
    # None means the tool may run outside/in any workflow state.
    allowed_states: frozenset[WorkflowState] | None = None
    side_effect: bool = False
    idempotent: bool = True
    max_attempts: int = 3
    failure_behavior: str = "retry transient errors, then surface the failure to the workflow"

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission.value,
            "allowed_states": sorted(s.value for s in self.allowed_states)
            if self.allowed_states is not None
            else None,
            "side_effect": self.side_effect,
            "idempotent": self.idempotent,
            "max_attempts": self.max_attempts,
            "failure_behavior": self.failure_behavior,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
        }


@dataclass
class ToolResult:
    tool: str
    output: dict[str, Any]
    duration_ms: int
    attempts: int
    extra: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name} already registered")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def descriptors(self) -> list[dict[str, Any]]:
        return [self._tools[name].descriptor() for name in self.names()]

    # ----------------------------------------------------------------- gate
    def authorize(self, spec: ToolSpec, ctx: ToolContext) -> None:
        """Permission + workflow-state gate. Raises ``ToolAuthorizationError`` on denial."""
        if not ctx.principal.can(spec.permission):
            raise ToolAuthorizationError(
                f"{ctx.principal.display_name} ({ctx.principal.role.value}) lacks permission "
                f"{spec.permission.value} required by tool {spec.name}",
                details={"permission": spec.permission.value, "role": ctx.principal.role.value},
            )
        if spec.allowed_states is not None:
            state = ctx.workflow_state
            if ctx.workflow is None or WorkflowState(state) not in spec.allowed_states:
                raise ToolAuthorizationError(
                    f"tool {spec.name} is not permitted in workflow state {state}",
                    details={
                        "workflow_state": state,
                        "allowed_states": sorted(s.value for s in spec.allowed_states),
                    },
                )

    # -------------------------------------------------------------- execute
    def execute(self, name: str, arguments: dict[str, Any] | None, ctx: ToolContext) -> ToolResult:
        arguments = arguments or {}
        workflow_id = ctx.workflow.id if ctx.workflow is not None else None
        spec = self.get(name)
        if spec is None:
            ctx.audit.record(
                category=EventCategory.SECURITY,
                event_type="tool.unknown_requested",
                severity=Severity.WARNING,
                message=f"Unknown tool requested: {name}",
                actor=ctx.principal,
                workflow_id=workflow_id,
                workflow_state=ctx.workflow_state,
                tool_name=name,
                authorization_outcome=AuthorizationOutcome.DENIED,
                payload={"arguments": _preview(arguments)},
            )
            raise ToolAuthorizationError(f"unknown tool {name}", details={"tool": name})

        # 1. Authorization (permission + state) comes before anything else.
        try:
            self.authorize(spec, ctx)
        except ToolAuthorizationError as exc:
            ctx.audit.record(
                category=EventCategory.SECURITY,
                event_type="tool.authorization_denied",
                severity=Severity.WARNING,
                message=f"Denied tool call {name}: {exc.message}",
                actor=ctx.principal,
                workflow_id=workflow_id,
                workflow_state=ctx.workflow_state,
                tool_name=name,
                authorization_outcome=AuthorizationOutcome.DENIED,
                payload={"arguments": _preview(arguments), **exc.details},
            )
            raise

        # 2. Input validation against the declared schema.
        try:
            parsed = spec.input_model.model_validate(arguments)
        except ValidationError as exc:
            errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()[:5]]
            ctx.audit.record(
                category=EventCategory.TOOL,
                event_type="tool.invalid_arguments",
                severity=Severity.WARNING,
                message=f"Rejected tool call {name}: invalid arguments",
                actor=ctx.principal,
                workflow_id=workflow_id,
                workflow_state=ctx.workflow_state,
                tool_name=name,
                authorization_outcome=AuthorizationOutcome.ALLOWED,
                payload={"arguments": _preview(arguments), "errors": errors},
            )
            raise ValidationFailed(
                f"invalid arguments for tool {name}", details={"errors": errors}
            ) from exc

        # 3. Execute with bounded retries for transient failures.
        attempts = 0
        started = time.perf_counter()
        # Retries only for idempotent tools, capped globally by TOOL_MAX_ATTEMPTS.
        max_attempts = (
            max(1, min(spec.max_attempts, ctx.settings.tool_max_attempts)) if spec.idempotent else 1
        )
        while True:
            attempts += 1
            try:
                ctx.injector.before_tool(ctx.db, ctx.workflow, name)
                output = spec.handler(ctx, parsed)
                duration_ms = int((time.perf_counter() - started) * 1000)
                result = ToolResult(
                    tool=name,
                    output=output.model_dump(mode="json"),
                    duration_ms=duration_ms,
                    attempts=attempts,
                )
                ctx.audit.record(
                    category=EventCategory.TOOL,
                    event_type="tool.executed",
                    message=f"Tool {name} succeeded"
                    + (f" after {attempts} attempts" if attempts > 1 else ""),
                    actor=ctx.principal,
                    workflow_id=workflow_id,
                    workflow_state=ctx.workflow_state,
                    tool_name=name,
                    duration_ms=duration_ms,
                    authorization_outcome=AuthorizationOutcome.ALLOWED,
                    payload={
                        "arguments": _preview(arguments),
                        "attempts": attempts,
                        "output": _preview(result.output),
                    },
                )
                return result
            except ToolAuthorizationError as exc:
                # Data-scoping denials raised inside handlers (e.g. another customer's order).
                ctx.audit.record(
                    category=EventCategory.SECURITY,
                    event_type="tool.authorization_denied",
                    severity=Severity.WARNING,
                    message=f"Denied tool call {name}: {exc.message}",
                    actor=ctx.principal,
                    workflow_id=workflow_id,
                    workflow_state=ctx.workflow_state,
                    tool_name=name,
                    authorization_outcome=AuthorizationOutcome.DENIED,
                    payload={"arguments": _preview(arguments), **exc.details},
                )
                raise
            except ToolExecutionError as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                if exc.retryable and attempts < max_attempts:
                    ctx.audit.record(
                        category=EventCategory.TOOL,
                        event_type="tool.retrying",
                        severity=Severity.WARNING,
                        message=f"Tool {name} failed transiently (attempt "
                        f"{attempts}/{max_attempts}): "
                        f"{exc.message}",
                        actor=ctx.principal,
                        workflow_id=workflow_id,
                        workflow_state=ctx.workflow_state,
                        tool_name=name,
                        duration_ms=duration_ms,
                        authorization_outcome=AuthorizationOutcome.ALLOWED,
                        payload={"attempt": attempts, "error": exc.message, **exc.details},
                    )
                    ctx.db.commit()  # keep the retry record even if a later attempt fails
                    backoff = ctx.settings.tool_retry_backoff_seconds * attempts
                    if backoff:
                        time.sleep(backoff)
                    continue
                ctx.audit.record(
                    category=EventCategory.TOOL,
                    event_type="tool.failed",
                    severity=Severity.ERROR,
                    message=f"Tool {name} failed after {attempts} attempt(s): {exc.message}",
                    actor=ctx.principal,
                    workflow_id=workflow_id,
                    workflow_state=ctx.workflow_state,
                    tool_name=name,
                    duration_ms=duration_ms,
                    authorization_outcome=AuthorizationOutcome.ALLOWED,
                    payload={
                        "attempts": attempts,
                        "retryable": exc.retryable,
                        "error": exc.message,
                        **exc.details,
                    },
                )
                raise
            except (NotFoundError, ValidationFailed) as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                ctx.audit.record(
                    category=EventCategory.TOOL,
                    event_type="tool.failed",
                    severity=Severity.WARNING,
                    message=f"Tool {name} rejected the request: {exc.message}",
                    actor=ctx.principal,
                    workflow_id=workflow_id,
                    workflow_state=ctx.workflow_state,
                    tool_name=name,
                    duration_ms=duration_ms,
                    authorization_outcome=AuthorizationOutcome.ALLOWED,
                    payload={"error": exc.message, **exc.details},
                )
                raise
            except AgentGuardError:
                raise
            except Exception as exc:  # unexpected bug inside a handler
                duration_ms = int((time.perf_counter() - started) * 1000)
                logger.exception("tool %s crashed", name)
                ctx.audit.record(
                    category=EventCategory.TOOL,
                    event_type="tool.failed",
                    severity=Severity.ERROR,
                    message=f"Tool {name} crashed: {type(exc).__name__}",
                    actor=ctx.principal,
                    workflow_id=workflow_id,
                    workflow_state=ctx.workflow_state,
                    tool_name=name,
                    duration_ms=duration_ms,
                    authorization_outcome=AuthorizationOutcome.ALLOWED,
                    payload={"error": str(exc)[:300]},
                )
                raise ToolExecutionError(
                    f"tool {name} crashed: {type(exc).__name__}", retryable=False
                ) from exc


def _preview(value: Any, limit: int = 600) -> Any:
    """Keep audit payloads compact."""
    if isinstance(value, dict):
        text = str(value)
        if len(text) <= limit:
            return value
        return {"_truncated": text[:limit]}
    return value
