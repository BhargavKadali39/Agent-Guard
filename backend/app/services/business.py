"""Business operations: customers, orders and the simulated refund execution.

``RefundService.execute`` is the one place money (simulated) moves. It is idempotent:
the database enforces at most one successful execution per workflow, so concurrent or
repeated calls can never refund twice.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.permissions import Principal
from app.database import utcnow
from app.errors import NotFoundError, TransientToolError, ValidationFailed
from app.evaluations.failure_injection import FailureInjector
from app.models import (
    ApprovalRequest,
    ApprovalStatus,
    Customer,
    Order,
    RefundExecution,
    Workflow,
)
from app.policies.engine import OrderFacts

logger = logging.getLogger(__name__)


class CustomerService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, customer_id: str) -> Customer:
        customer = self.db.get(Customer, customer_id)
        if customer is None:
            raise NotFoundError(f"customer {customer_id} not found")
        return customer

    def list(self) -> list[Customer]:
        return list(self.db.scalars(select(Customer).order_by(Customer.id)))

    def update_email(self, customer_id: str, email: str) -> Customer:
        customer = self.get(customer_id)
        customer.email = email
        self.db.add(customer)
        self.db.flush()
        return customer


class OrderService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, order_id: str) -> Order:
        order = self.db.get(Order, order_id)
        if order is None:
            raise NotFoundError(f"order {order_id} not found")
        return order

    def get_for_customer(self, order_id: str, customer_id: str) -> Order | None:
        """Scoped lookup: an order that belongs to another customer is invisible."""
        order = self.db.get(Order, order_id)
        if order is None or order.customer_id != customer_id:
            return None
        return order

    def list_for_customer(self, customer_id: str) -> list[Order]:
        return list(
            self.db.scalars(
                select(Order)
                .where(Order.customer_id == customer_id)
                .order_by(Order.placed_at.desc())
            )
        )

    def list(self, limit: int = 200) -> list[Order]:
        return list(self.db.scalars(select(Order).order_by(Order.placed_at.desc()).limit(limit)))

    @staticmethod
    def facts(order: Order) -> OrderFacts:
        return OrderFacts(
            order_id=order.id,
            status=order.status,
            total_paise=order.total_paise,
            refunded_paise=order.refunded_paise,
            delivered_at=order.delivered_at,
        )


@dataclass(frozen=True)
class GatewayReceipt:
    reference: str
    latency_ms: int


class SimulatedPaymentGateway:
    """A stand-in for a payment provider. No real money is ever moved."""

    def __init__(self, injector: FailureInjector, latency_ms: int = 0) -> None:
        self.injector = injector
        self.latency_ms = latency_ms

    def refund(
        self, db: Session, workflow: Workflow | None, *, order_id: str, amount_paise: int, key: str
    ) -> GatewayReceipt:
        self.injector.before_gateway(db, workflow)
        started = time.perf_counter()
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000)
        digest = hashlib.sha256(f"{order_id}:{amount_paise}:{key}".encode()).hexdigest()[:12]
        return GatewayReceipt(
            reference=f"SIM-RFND-{digest.upper()}",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class RefundService:
    def __init__(self, db: Session, gateway: SimulatedPaymentGateway, injector: FailureInjector):
        self.db = db
        self.gateway = gateway
        self.injector = injector

    def existing_execution(self, workflow_id: str) -> RefundExecution | None:
        return self.db.scalars(
            select(RefundExecution).where(RefundExecution.workflow_id == workflow_id)
        ).first()

    def execute(
        self,
        *,
        workflow: Workflow,
        approval: ApprovalRequest,
        amount_paise: int,
        actor: Principal,
    ) -> tuple[RefundExecution, bool]:
        """Perform the simulated refund exactly once.

        Returns ``(execution, created)`` where ``created`` is False when a previous
        successful execution was found (idempotent replay).
        """
        # --- Approval binding: the approval must be for *this* workflow/order/amount.
        if approval.workflow_id != workflow.id:
            raise ValidationFailed("approval does not belong to this workflow")
        if approval.action != "execute_refund":
            raise ValidationFailed("approval is for a different action")
        if approval.status != ApprovalStatus.APPROVED:
            raise ValidationFailed(f"approval status is {approval.status}, not approved")
        if approval.amount_paise != amount_paise:
            raise ValidationFailed(
                f"approval amount {approval.amount_paise} does not match requested {amount_paise}"
            )
        if workflow.order_id is None or approval.order_id != workflow.order_id:
            raise ValidationFailed("approval order does not match workflow order")

        # --- Idempotency: replay returns the original result without side effects.
        existing = self.existing_execution(workflow.id)
        if existing is not None:
            return existing, False

        # Lock the order row (PostgreSQL: SELECT ... FOR UPDATE; SQLite serialises writers),
        # then re-check: a concurrent worker may have completed the refund meanwhile.
        order = self.db.scalars(
            select(Order)
            .where(Order.id == workflow.order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if order is None:
            raise NotFoundError(f"order {workflow.order_id} not found")
        existing = self.existing_execution(workflow.id)
        if existing is not None:
            return existing, False
        if amount_paise <= 0 or amount_paise > order.refundable_paise:
            raise ValidationFailed(
                f"amount {amount_paise} exceeds refundable balance {order.refundable_paise}"
            )

        idempotency_key = f"refund:{workflow.id}"
        receipt = self.gateway.refund(
            self.db, workflow, order_id=order.id, amount_paise=amount_paise, key=idempotency_key
        )

        # Injected "database failure" happens after the gateway call and before commit, the
        # classic partial-failure window that idempotency keys exist to make safe.
        self.injector.before_db_commit(self.db, workflow, "refund_commit")

        execution = RefundExecution(
            workflow_id=workflow.id,
            order_id=order.id,
            approval_id=approval.id,
            amount_paise=amount_paise,
            currency=approval.currency,
            idempotency_key=idempotency_key,
            status="succeeded",
            gateway_reference=receipt.reference,
            executed_by=actor.id,
            executed_at=utcnow(),
        )
        try:
            with self.db.begin_nested():
                order.refunded_paise = order.refunded_paise + amount_paise
                self.db.add(order)
                self.db.add(execution)
                self.db.flush()
        except IntegrityError:
            # A concurrent execution won the race; the unique constraint protected us.
            logger.warning("duplicate refund execution prevented", extra={"workflow": workflow.id})
            self.db.expire(order)
            existing = self.existing_execution(workflow.id)
            if existing is None:  # pragma: no cover - defensive
                raise TransientToolError("refund execution conflict; retry") from None
            return existing, False
        return execution, True
