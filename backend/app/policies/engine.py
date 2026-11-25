"""Deterministic refund policy engine.

The engine is pure: given order facts, a requested amount, the current time and a policy
configuration it returns a ``PolicyDecision``. No LLM output is consulted here. The AI
may *explain* a decision to a customer; it never *makes* one.

Amounts are integer paise. Default demo thresholds: <= ₹2,000 auto-approve,
₹2,000.01 - ₹10,000 reviewer, > ₹10,000 senior reviewer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.auth.permissions import Role
from app.models.enums import OrderStatus, RefundTier


class PolicyConfig(BaseModel):
    """Structured, validated policy configuration (stored as JSON)."""

    currency: str = "INR"
    eligible_statuses: list[str] = Field(default_factory=lambda: [OrderStatus.DELIVERED.value])
    refund_window_days: int = Field(default=30, ge=0, le=3650)
    auto_approve_max_paise: int = Field(default=200_000, ge=0)
    reviewer_max_paise: int = Field(default=1_000_000, ge=0)
    allow_partial_refunds: bool = True
    # When true, ineligible requests are escalated to a senior reviewer instead of being
    # rejected outright (an explicit exception workflow). Off by default.
    allow_exception_override: bool = False

    @field_validator("eligible_statuses")
    @classmethod
    def _validate_statuses(cls, value: list[str]) -> list[str]:
        valid = {s.value for s in OrderStatus}
        unknown = [s for s in value if s not in valid]
        if unknown:
            raise ValueError(f"unknown order statuses: {unknown}")
        return value

    def model_post_init(self, _ctx: Any) -> None:
        if self.reviewer_max_paise < self.auto_approve_max_paise:
            raise ValueError("reviewer_max_paise must be >= auto_approve_max_paise")


DEFAULT_POLICY_CONFIG = PolicyConfig()


@dataclass(frozen=True)
class OrderFacts:
    """Trusted facts about an order, loaded from the database (never from the message)."""

    order_id: str
    status: str
    total_paise: int
    refunded_paise: int
    delivered_at: datetime | None

    @property
    def refundable_paise(self) -> int:
        return max(self.total_paise - self.refunded_paise, 0)


class PolicyRuleResult(BaseModel):
    rule: str
    passed: bool
    detail: str


class PolicyDecision(BaseModel):
    eligible: bool
    tier: RefundTier
    required_role: Role | None
    amount_paise: int
    refundable_paise: int
    reasons: list[str]
    rules: list[PolicyRuleResult]
    policy_name: str
    policy_version: int
    evaluated_at: datetime
    exception_override_available: bool = False

    @property
    def requires_human_approval(self) -> bool:
        return self.required_role is not None


class PolicyEngine:
    def __init__(self, config: PolicyConfig, *, name: str = "default", version: int = 1) -> None:
        self.config = config
        self.name = name
        self.version = version

    def evaluate(self, order: OrderFacts, amount_paise: int, now: datetime) -> PolicyDecision:
        cfg = self.config
        rules: list[PolicyRuleResult] = []
        reasons: list[str] = []

        # Rule 1: order status must be eligible.
        status_ok = order.status in cfg.eligible_statuses
        rules.append(
            PolicyRuleResult(
                rule="eligible_status",
                passed=status_ok,
                detail=f"order status {order.status} "
                f"{'is' if status_ok else 'is not'} in {cfg.eligible_statuses}",
            )
        )
        if not status_ok:
            reasons.append(f"order_status_not_eligible:{order.status}")

        # Rule 2: within the refund window measured from delivery.
        if order.delivered_at is None:
            window_ok = False
            window_detail = "order has no delivery date"
        else:
            deadline = order.delivered_at + timedelta(days=cfg.refund_window_days)
            window_ok = now <= deadline
            days_since = (now - order.delivered_at).days
            window_detail = (
                f"{days_since} day(s) since delivery; window is {cfg.refund_window_days} day(s)"
            )
        rules.append(PolicyRuleResult(rule="refund_window", passed=window_ok, detail=window_detail))
        if not window_ok:
            reasons.append("outside_refund_window")

        # Rule 3: amount must be positive and within the refundable balance.
        amount_positive = amount_paise > 0
        rules.append(
            PolicyRuleResult(
                rule="amount_positive",
                passed=amount_positive,
                detail=f"requested {amount_paise} paise",
            )
        )
        if not amount_positive:
            reasons.append("amount_not_positive")

        balance_available = order.refundable_paise > 0
        rules.append(
            PolicyRuleResult(
                rule="refundable_balance_available",
                passed=balance_available,
                detail=f"refundable balance {order.refundable_paise} paise "
                f"(total {order.total_paise}, already refunded {order.refunded_paise})",
            )
        )
        if not balance_available:
            reasons.append("already_refunded")

        balance_ok = amount_paise <= order.refundable_paise
        rules.append(
            PolicyRuleResult(
                rule="within_refundable_balance",
                passed=balance_ok,
                detail=f"requested {amount_paise} paise; refundable {order.refundable_paise} paise",
            )
        )
        if not balance_ok and balance_available:
            reasons.append("amount_exceeds_refundable")

        partial = amount_paise < order.refundable_paise
        partial_ok = cfg.allow_partial_refunds or not partial
        rules.append(
            PolicyRuleResult(
                rule="partial_refund_allowed",
                passed=partial_ok,
                detail="partial refund" if partial else "full refund of remaining balance",
            )
        )
        if not partial_ok:
            reasons.append("partial_refunds_not_allowed")

        eligible = (
            status_ok
            and window_ok
            and amount_positive
            and balance_available
            and balance_ok
            and partial_ok
        )

        if eligible:
            if amount_paise <= cfg.auto_approve_max_paise:
                tier, required_role = RefundTier.AUTO, None
                reasons.append("auto_approval_tier")
            elif amount_paise <= cfg.reviewer_max_paise:
                tier, required_role = RefundTier.REVIEWER, Role.REVIEWER
                reasons.append("reviewer_approval_tier")
            else:
                tier, required_role = RefundTier.SENIOR_REVIEWER, Role.SENIOR_REVIEWER
                reasons.append("senior_reviewer_approval_tier")
        else:
            tier, required_role = RefundTier.REJECTED, None

        return PolicyDecision(
            eligible=eligible,
            tier=tier,
            required_role=required_role,
            amount_paise=amount_paise,
            refundable_paise=order.refundable_paise,
            reasons=reasons,
            rules=rules,
            policy_name=self.name,
            policy_version=self.version,
            evaluated_at=now,
            exception_override_available=(not eligible) and cfg.allow_exception_override,
        )

    def describe(self) -> dict[str, Any]:
        cfg = self.config
        return {
            "name": self.name,
            "version": self.version,
            "currency": cfg.currency,
            "eligible_statuses": cfg.eligible_statuses,
            "refund_window_days": cfg.refund_window_days,
            "auto_approve_max_paise": cfg.auto_approve_max_paise,
            "reviewer_max_paise": cfg.reviewer_max_paise,
            "allow_partial_refunds": cfg.allow_partial_refunds,
            "allow_exception_override": cfg.allow_exception_override,
        }
