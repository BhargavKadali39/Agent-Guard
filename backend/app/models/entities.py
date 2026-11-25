"""SQLAlchemy ORM models.

Money is stored as integer *paise* (1 rupee = 100 paise) so arithmetic is exact on every
database backend. Enumerations are stored as short strings to stay portable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, PortableJSON, UTCDateTime, utcnow


def new_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    city: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="regular")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    orders: Mapped[list[Order]] = relationship(back_populates="customer")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    price_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.id"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(String(32), ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refunded_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    customer: Mapped[Customer] = relationship(back_populates="orders")
    product: Mapped[Product] = relationship()

    @property
    def refundable_paise(self) -> int:
        return max(self.total_paise - self.refunded_paise, 0)


class RefundPolicy(Base):
    __tablename__ = "refund_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    config: Mapped[dict[str, Any]] = mapped_column(PortableJSON, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class Workflow(Base):
    """A refund request and everything the agent/system did with it."""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    customer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.id"), nullable=False, index=True
    )
    order_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("orders.id"), nullable=True, index=True
    )
    # Untrusted customer-provided text. Never treated as an instruction.
    message: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    client_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    provider_name: Mapped[str] = mapped_column(String(32), nullable=False, default="mock")

    interpretation: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON, nullable=True)
    verification: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON, nullable=True)
    policy_decision: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON, nullable=True)
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON, nullable=True)
    simulation: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON, nullable=True)

    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resumable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resume_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Processing lease: at most one worker advances a workflow at a time.
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    customer: Mapped[Customer] = relationship()
    order: Mapped[Order | None] = relationship()
    approvals: Mapped[list[ApprovalRequest]] = relationship(
        back_populates="workflow", order_by="ApprovalRequest.requested_at"
    )
    execution: Mapped[RefundExecution | None] = relationship(
        back_populates="workflow", uselist=False
    )


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    required_role: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Binds the approval to the exact operation it was raised for.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_state_at_request: Mapped[str] = mapped_column(String(32), nullable=False)
    auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_by_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    workflow: Mapped[Workflow] = relationship(back_populates="approvals")


class RefundExecution(Base):
    """One successful simulated refund per workflow, enforced by the database."""

    __tablename__ = "refund_executions"
    __table_args__ = (
        UniqueConstraint("workflow_id", name="uq_refund_execution_workflow"),
        UniqueConstraint("idempotency_key", name="uq_refund_execution_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workflow_id: Mapped[str] = mapped_column(String(36), ForeignKey("workflows.id"), nullable=False)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.id"), nullable=False)
    approval_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("approval_requests.id"), nullable=False
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="succeeded")
    gateway_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    executed_by: Mapped[str] = mapped_column(String(64), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    workflow: Mapped[Workflow] = relationship(back_populates="execution")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_workflow_ts", "workflow_id", "timestamp"),
        Index("ix_audit_events_category_ts", "category", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflows.id"), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authorization_outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="n/a")
    workflow_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON, nullable=True)


class LabRun(Base):
    __tablename__ = "lab_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    scenario_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    run_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[dict[str, Any]] = mapped_column(PortableJSON, nullable=False)
