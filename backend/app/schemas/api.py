"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.evaluations.failure_injection import SimulationConfig
from app.policies.engine import PolicyConfig


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(ORMModel):
    id: str
    username: str
    display_name: str
    role: str
    permissions: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


# ------------------------------------------------------------------------- commerce
class CustomerOut(ORMModel):
    id: str
    name: str
    email: str
    city: str
    tier: str


class OrderOut(ORMModel):
    id: str
    customer_id: str
    product_id: str
    product_name: str
    quantity: int
    total_paise: int
    refunded_paise: int
    refundable_paise: int
    status: str
    placed_at: datetime
    delivered_at: datetime | None


class PolicyOut(BaseModel):
    id: str
    name: str
    version: int
    is_active: bool
    config: PolicyConfig
    created_at: datetime
    created_by: str | None


# ------------------------------------------------------------------------ workflows
class WorkflowCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1, max_length=4000)
    client_request_id: str | None = Field(default=None, max_length=128)
    simulation: SimulationConfig | None = None


class ApprovalOut(ORMModel):
    id: str
    workflow_id: str
    action: str
    order_id: str | None
    amount_paise: int
    currency: str
    required_role: str
    reason: str
    details: dict[str, Any] | None
    status: str
    auto: bool
    workflow_state_at_request: str
    requested_at: datetime
    expires_at: datetime | None
    decided_by: str | None
    decided_by_name: str | None = None
    decided_by_role: str | None
    decided_at: datetime | None
    comment: str | None
    customer_id: str | None = None
    customer_name: str | None = None


class ExecutionOut(ORMModel):
    id: str
    workflow_id: str
    order_id: str
    approval_id: str
    amount_paise: int
    currency: str
    idempotency_key: str
    status: str
    gateway_reference: str
    executed_by: str
    executed_at: datetime


class WorkflowOut(ORMModel):
    id: str
    customer_id: str
    customer_name: str | None = None
    order_id: str | None
    message: str
    state: str
    created_by: str | None
    client_request_id: str | None
    provider_name: str
    approval_id: str | None
    failure_reason: str | None
    rejection_reason: str | None
    resumable: bool
    resume_count: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    interpretation: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    policy_decision: dict[str, Any] | None = None
    checkpoint: dict[str, Any] | None = None
    simulation: dict[str, Any] | None = None
    approvals: list[ApprovalOut] = Field(default_factory=list)
    execution: ExecutionOut | None = None
    interrupted: bool = False


class WorkflowListResponse(BaseModel):
    items: list[WorkflowOut]
    total: int


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    comment: str | None = Field(default=None, max_length=1000)


class CancelRequest(BaseModel):
    reason: str = Field(default="cancelled by operator", max_length=500)


# --------------------------------------------------------------------------- events
class EventOut(ORMModel):
    id: int
    workflow_id: str | None
    timestamp: datetime
    category: str
    event_type: str
    severity: str
    actor_type: str
    actor_id: str
    tool_name: str | None
    duration_ms: int | None
    authorization_outcome: str
    workflow_state: str | None
    message: str
    payload: dict[str, Any] | None


class EventListResponse(BaseModel):
    items: list[EventOut]
    total: int


# -------------------------------------------------------------------------- metrics
class MetricsOverview(BaseModel):
    total_workflows: int
    completed_workflows: int
    pending_approvals: int
    failed_workflows: int
    rejected_workflows: int
    awaiting_approval_workflows: int
    blocked_unauthorized_actions: int
    injection_attempts_detected: int
    average_workflow_duration_ms: float | None
    total_refunded_paise: int
    workflows_by_state: dict[str, int]
    workflows_per_day: list[dict[str, Any]]
    policy_outcomes: dict[str, int]
    generated_at: datetime


# ---------------------------------------------------------------------- failure lab
class AssertionOut(BaseModel):
    name: str
    passed: bool
    detail: str


class ScenarioOut(BaseModel):
    key: str
    title: str
    category: str
    description: str
    initial_request: str
    expected_behavior: str
    explanation: str


class ScenarioResult(BaseModel):
    scenario: ScenarioOut
    run_id: str
    passed: bool
    started_at: datetime
    duration_ms: int
    observed_behavior: str
    assertions: list[AssertionOut]
    workflow_ids: list[str]
    events: list[EventOut]


class LabRunOut(ORMModel):
    id: str
    scenario_key: str
    passed: bool
    run_by: str | None
    started_at: datetime
    duration_ms: int
    result: dict[str, Any]


# ---------------------------------------------------------------------------- admin
class InjectionCreate(BaseModel):
    point: str = Field(min_length=1, max_length=64)
    mode: str = Field(default="transient", pattern="^(transient|permanent)$")
    times: int | None = Field(default=None, ge=1, le=100)
    description: str = Field(default="", max_length=200)


class ExampleRequest(BaseModel):
    key: str
    title: str
    customer_id: str
    message: str
    expected: str
    simulation: SimulationConfig | None = None


class HealthOut(BaseModel):
    status: str
    environment: str
    database: str
    ai_provider: dict[str, str]
    demo_mode: bool
    version: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
