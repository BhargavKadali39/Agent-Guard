"""The refund agent's tools.

Each tool is a thin, typed adapter over a business service. Handlers enforce *data
scoping* (a workflow may only touch its own customer's records); the registry enforces
permissions, workflow-state gating, argument validation, retries and auditing.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.auth.permissions import Permission, Role
from app.database import utcnow
from app.errors import NotFoundError, ToolAuthorizationError, ValidationFailed
from app.models import ApprovalReason, Workflow
from app.services.business import CustomerService, OrderService
from app.tools.registry import ToolContext, ToolRegistry, ToolSpec
from app.workflows.states import WorkflowState


class StrictModel(BaseModel):
    """Tool inputs reject unknown fields, so an agent cannot smuggle extra flags in."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- schemas
class CustomerDetailsInput(StrictModel):
    customer_id: str = Field(min_length=1, max_length=32)


class CustomerDetailsOutput(BaseModel):
    customer_id: str
    name: str
    tier: str
    city: str
    order_count: int


class OrderInfoInput(StrictModel):
    order_id: str = Field(min_length=1, max_length=32)


class OrderInfoOutput(BaseModel):
    order_id: str
    customer_id: str
    product_name: str
    quantity: int
    total_paise: int
    refunded_paise: int
    refundable_paise: int
    status: str
    placed_at: str
    delivered_at: str | None


class EmptyInput(StrictModel):
    pass


class PolicyOutput(BaseModel):
    name: str
    version: int
    currency: str
    eligible_statuses: list[str]
    refund_window_days: int
    auto_approve_max_paise: int
    reviewer_max_paise: int
    allow_partial_refunds: bool
    allow_exception_override: bool


class EligibilityInput(StrictModel):
    order_id: str = Field(min_length=1, max_length=32)
    amount_paise: int = Field(ge=0, le=10_000_000_000)


class EligibilityOutput(BaseModel):
    eligible: bool
    tier: str
    required_role: str | None
    amount_paise: int
    refundable_paise: int
    reasons: list[str]
    rules: list[dict[str, Any]]
    policy_name: str
    policy_version: int
    exception_override_available: bool


class CreateApprovalInput(StrictModel):
    amount_paise: int = Field(gt=0, le=10_000_000_000)
    required_role: Role
    reason: ApprovalReason
    details: dict[str, Any] | None = None


class ApprovalOutput(BaseModel):
    approval_id: str
    status: str
    required_role: str
    reason: str
    amount_paise: int
    expires_at: str | None
    decided_by: str | None


class CheckApprovalInput(StrictModel):
    approval_id: str = Field(min_length=1, max_length=36)


class ExecuteRefundInput(StrictModel):
    order_id: str = Field(min_length=1, max_length=32)
    amount_paise: int = Field(gt=0, le=10_000_000_000)
    approval_id: str = Field(min_length=1, max_length=36)


class ExecuteRefundOutput(BaseModel):
    execution_id: str
    workflow_id: str
    order_id: str
    amount_paise: int
    gateway_reference: str
    status: str
    created: bool
    executed_at: str


class WorkflowStatusInput(StrictModel):
    workflow_id: str = Field(min_length=1, max_length=36)


class WorkflowStatusOutput(BaseModel):
    workflow_id: str
    state: str
    checkpoint_step: str | None
    resumable: bool


class UpdateCustomerInput(StrictModel):
    customer_id: str = Field(min_length=1, max_length=32)
    changes: dict[str, Any]


class UpdateCustomerOutput(BaseModel):
    customer_id: str
    updated_fields: list[str]


# --------------------------------------------------------------------------- helpers
def _scoped_order(ctx: ToolContext, order_id: str):
    orders = OrderService(ctx.db)
    if ctx.workflow is not None:
        order = orders.get_for_customer(order_id, ctx.workflow.customer_id)
        if order is None:
            raise ToolAuthorizationError(
                f"order {order_id} does not belong to customer {ctx.workflow.customer_id}",
                details={"order_id": order_id, "customer_id": ctx.workflow.customer_id},
            )
        return order
    return orders.get(order_id)


# --------------------------------------------------------------------------- handlers
def get_customer_details(ctx: ToolContext, args: CustomerDetailsInput) -> CustomerDetailsOutput:
    if ctx.workflow is not None and args.customer_id != ctx.workflow.customer_id:
        raise ToolAuthorizationError(
            "customer lookup outside the workflow's customer scope",
            details={"requested": args.customer_id, "scope": ctx.workflow.customer_id},
        )
    customer = CustomerService(ctx.db).get(args.customer_id)
    return CustomerDetailsOutput(
        customer_id=customer.id,
        name=customer.name,
        tier=customer.tier,
        city=customer.city,
        order_count=len(OrderService(ctx.db).list_for_customer(customer.id)),
    )


def get_order_information(ctx: ToolContext, args: OrderInfoInput) -> OrderInfoOutput:
    order = _scoped_order(ctx, args.order_id)
    return OrderInfoOutput(
        order_id=order.id,
        customer_id=order.customer_id,
        product_name=order.product.name,
        quantity=order.quantity,
        total_paise=order.total_paise,
        refunded_paise=order.refunded_paise,
        refundable_paise=order.refundable_paise,
        status=order.status,
        placed_at=order.placed_at.isoformat(),
        delivered_at=order.delivered_at.isoformat() if order.delivered_at else None,
    )


def retrieve_refund_policy(ctx: ToolContext, _args: EmptyInput) -> PolicyOutput:
    return PolicyOutput(**ctx.policy_engine.describe())


def evaluate_refund_eligibility(ctx: ToolContext, args: EligibilityInput) -> EligibilityOutput:
    order = _scoped_order(ctx, args.order_id)
    decision = ctx.policy_engine.evaluate(OrderService.facts(order), args.amount_paise, utcnow())
    return EligibilityOutput(
        eligible=decision.eligible,
        tier=decision.tier.value,
        required_role=decision.required_role.value if decision.required_role else None,
        amount_paise=decision.amount_paise,
        refundable_paise=decision.refundable_paise,
        reasons=decision.reasons,
        rules=[r.model_dump() for r in decision.rules],
        policy_name=decision.policy_name,
        policy_version=decision.policy_version,
        exception_override_available=decision.exception_override_available,
    )


def _approval_output(approval) -> ApprovalOutput:
    return ApprovalOutput(
        approval_id=approval.id,
        status=approval.status,
        required_role=approval.required_role,
        reason=approval.reason,
        amount_paise=approval.amount_paise,
        expires_at=approval.expires_at.isoformat() if approval.expires_at else None,
        decided_by=approval.decided_by,
    )


def create_approval_request(ctx: ToolContext, args: CreateApprovalInput) -> ApprovalOutput:
    if ctx.workflow is None:
        raise ValidationFailed("approval requests require a workflow")
    approval = ctx.approval_service.create(
        workflow=ctx.workflow,
        amount_paise=args.amount_paise,
        required_role=args.required_role,
        reason=args.reason,
        details=args.details,
        actor=ctx.principal,
    )
    return _approval_output(approval)


def check_approval_status(ctx: ToolContext, args: CheckApprovalInput) -> ApprovalOutput:
    approval = ctx.approval_service.get(args.approval_id)
    if ctx.workflow is not None and approval.workflow_id != ctx.workflow.id:
        raise ToolAuthorizationError(
            "approval belongs to a different workflow",
            details={"approval_id": args.approval_id},
        )
    return _approval_output(approval)


def execute_simulated_refund(ctx: ToolContext, args: ExecuteRefundInput) -> ExecuteRefundOutput:
    if ctx.workflow is None:
        raise ValidationFailed("refund execution requires a workflow")
    if ctx.workflow.order_id != args.order_id:
        raise ToolAuthorizationError(
            "refund order does not match the verified workflow order",
            details={"requested": args.order_id, "verified": ctx.workflow.order_id},
        )
    approval = ctx.approval_service.get(args.approval_id)
    execution, created = ctx.refund_service.execute(
        workflow=ctx.workflow,
        approval=approval,
        amount_paise=args.amount_paise,
        actor=ctx.principal,
    )
    return ExecuteRefundOutput(
        execution_id=execution.id,
        workflow_id=execution.workflow_id,
        order_id=execution.order_id,
        amount_paise=execution.amount_paise,
        gateway_reference=execution.gateway_reference,
        status=execution.status,
        created=created,
        executed_at=execution.executed_at.isoformat(),
    )


def get_workflow_status(ctx: ToolContext, args: WorkflowStatusInput) -> WorkflowStatusOutput:
    workflow = ctx.db.get(Workflow, args.workflow_id)
    if workflow is None:
        raise NotFoundError(f"workflow {args.workflow_id} not found")
    if ctx.workflow is not None and workflow.id != ctx.workflow.id:
        raise ToolAuthorizationError("cannot inspect another workflow")
    checkpoint = workflow.checkpoint or {}
    return WorkflowStatusOutput(
        workflow_id=workflow.id,
        state=workflow.state,
        checkpoint_step=checkpoint.get("step"),
        resumable=workflow.resumable,
    )


def update_customer_record(ctx: ToolContext, args: UpdateCustomerInput) -> UpdateCustomerOutput:
    """Administrative tool. The agent principal is never granted customer:update."""
    customers = CustomerService(ctx.db)
    updated: list[str] = []
    if "email" in args.changes:
        customers.update_email(args.customer_id, str(args.changes["email"]))
        updated.append("email")
    if "tier" in args.changes:
        customer = customers.get(args.customer_id)
        customer.tier = str(args.changes["tier"])
        ctx.db.add(customer)
        updated.append("tier")
    return UpdateCustomerOutput(customer_id=args.customer_id, updated_fields=updated)


# --------------------------------------------------------------------------- registry
def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="get_customer_details",
            description="Fetch trusted profile facts for the workflow's customer.",
            input_model=CustomerDetailsInput,
            output_model=CustomerDetailsOutput,
            permission=Permission.CUSTOMER_READ,
            handler=get_customer_details,
            failure_behavior="read-only; retried on transient errors",
        )
    )
    registry.register(
        ToolSpec(
            name="get_order_information",
            description="Fetch an order. Only orders belonging to the workflow's customer are "
            "visible.",
            input_model=OrderInfoInput,
            output_model=OrderInfoOutput,
            permission=Permission.ORDER_READ,
            handler=get_order_information,
            failure_behavior="read-only; retried on transient errors; out-of-scope orders are "
            "denied",
        )
    )
    registry.register(
        ToolSpec(
            name="retrieve_refund_policy",
            description="Return the active refund policy configuration.",
            input_model=EmptyInput,
            output_model=PolicyOutput,
            permission=Permission.POLICY_READ,
            handler=retrieve_refund_policy,
            failure_behavior="read-only",
        )
    )
    registry.register(
        ToolSpec(
            name="evaluate_refund_eligibility",
            description="Run the deterministic policy engine for an order and amount.",
            input_model=EligibilityInput,
            output_model=EligibilityOutput,
            permission=Permission.POLICY_EVALUATE,
            handler=evaluate_refund_eligibility,
            failure_behavior="pure computation over trusted order facts; retried on transient "
            "errors",
        )
    )
    registry.register(
        ToolSpec(
            name="create_approval_request",
            description="Ask a human reviewer to approve a refund. Allowed only during "
            "POLICY_CHECK.",
            input_model=CreateApprovalInput,
            output_model=ApprovalOutput,
            permission=Permission.APPROVAL_REQUEST,
            handler=create_approval_request,
            allowed_states=frozenset({WorkflowState.POLICY_CHECK}),
            side_effect=True,
            idempotent=True,  # a pending approval is reused rather than duplicated
            failure_behavior="idempotent per workflow; retried on transient errors",
        )
    )
    registry.register(
        ToolSpec(
            name="check_approval_status",
            description="Read the status of an approval that belongs to this workflow.",
            input_model=CheckApprovalInput,
            output_model=ApprovalOutput,
            permission=Permission.APPROVAL_READ,
            handler=check_approval_status,
            failure_behavior="read-only",
        )
    )
    registry.register(
        ToolSpec(
            name="execute_simulated_refund",
            description="Execute the simulated refund. Allowed only in EXECUTING with a bound, "
            "approved "
            "approval; the database guarantees at most one execution per workflow.",
            input_model=ExecuteRefundInput,
            output_model=ExecuteRefundOutput,
            permission=Permission.REFUND_EXECUTE,
            handler=execute_simulated_refund,
            allowed_states=frozenset({WorkflowState.EXECUTING}),
            side_effect=True,
            idempotent=True,  # idempotency key + unique constraint make retries safe
            failure_behavior="retried on transient gateway/database errors; duplicates are "
            "impossible",
        )
    )
    registry.register(
        ToolSpec(
            name="get_workflow_status",
            description="Read the current state and checkpoint of this workflow.",
            input_model=WorkflowStatusInput,
            output_model=WorkflowStatusOutput,
            permission=Permission.WORKFLOW_READ,
            handler=get_workflow_status,
            failure_behavior="read-only",
        )
    )
    registry.register(
        ToolSpec(
            name="update_customer_record",
            description="Administrative: change customer profile fields. Never granted to the "
            "agent.",
            input_model=UpdateCustomerInput,
            output_model=UpdateCustomerOutput,
            permission=Permission.CUSTOMER_UPDATE,
            handler=update_customer_record,
            side_effect=True,
            idempotent=False,
            max_attempts=1,
            failure_behavior="not retried; requires customer:update permission",
        )
    )
    return registry
