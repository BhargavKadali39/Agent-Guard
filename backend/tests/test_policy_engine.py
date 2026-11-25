"""Deterministic policy engine: boundary conditions and rule behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.auth.permissions import Role
from app.models.enums import OrderStatus, RefundTier
from app.policies.engine import OrderFacts, PolicyConfig, PolicyEngine

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def facts(
    *,
    status: str = OrderStatus.DELIVERED,
    total: int = 2_000_000,
    refunded: int = 0,
    delivered_days_ago: int | None = 5,
) -> OrderFacts:
    delivered = NOW - timedelta(days=delivered_days_ago) if delivered_days_ago is not None else None
    return OrderFacts(
        order_id="ORD-TEST",
        status=str(status),
        total_paise=total,
        refunded_paise=refunded,
        delivered_at=delivered,
    )


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine(PolicyConfig(), name="test-policy", version=7)


@pytest.mark.parametrize(
    ("amount_paise", "tier", "role"),
    [
        (1, RefundTier.AUTO, None),
        (199_999, RefundTier.AUTO, None),
        (200_000, RefundTier.AUTO, None),  # ₹2,000.00 inclusive
        (200_001, RefundTier.REVIEWER, Role.REVIEWER),  # ₹2,000.01
        (200_100, RefundTier.REVIEWER, Role.REVIEWER),  # ₹2,001
        (999_999, RefundTier.REVIEWER, Role.REVIEWER),
        (1_000_000, RefundTier.REVIEWER, Role.REVIEWER),  # ₹10,000.00 inclusive
        (1_000_001, RefundTier.SENIOR_REVIEWER, Role.SENIOR_REVIEWER),  # ₹10,000.01
        (1_000_100, RefundTier.SENIOR_REVIEWER, Role.SENIOR_REVIEWER),  # ₹10,001
        (2_000_000, RefundTier.SENIOR_REVIEWER, Role.SENIOR_REVIEWER),
    ],
)
def test_amount_tiers_at_boundaries(engine: PolicyEngine, amount_paise, tier, role) -> None:
    decision = engine.evaluate(facts(total=2_000_000), amount_paise, NOW)
    assert decision.eligible is True
    assert decision.tier == tier
    assert decision.required_role == role
    assert decision.policy_name == "test-policy" and decision.policy_version == 7


def test_refund_window_boundary(engine: PolicyEngine) -> None:
    exactly = facts(delivered_days_ago=30)
    assert engine.evaluate(exactly, 100_000, NOW).eligible is True
    just_over = OrderFacts(
        order_id="ORD-TEST",
        status=OrderStatus.DELIVERED,
        total_paise=200_000,
        refunded_paise=0,
        delivered_at=NOW - timedelta(days=30, minutes=1),
    )
    decision = engine.evaluate(just_over, 100_000, NOW)
    assert decision.eligible is False
    assert "outside_refund_window" in decision.reasons
    assert decision.tier == RefundTier.REJECTED and decision.required_role is None


def test_ineligible_statuses(engine: PolicyEngine) -> None:
    for status in (
        OrderStatus.PLACED,
        OrderStatus.SHIPPED,
        OrderStatus.CANCELLED,
        OrderStatus.RETURNED,
    ):
        decision = engine.evaluate(facts(status=status, delivered_days_ago=None), 100_000, NOW)
        assert decision.eligible is False
        assert any(r.startswith("order_status_not_eligible") for r in decision.reasons)


def test_already_refunded_order(engine: PolicyEngine) -> None:
    decision = engine.evaluate(facts(total=500_000, refunded=500_000), 100_000, NOW)
    assert decision.eligible is False
    assert "already_refunded" in decision.reasons
    assert "amount_exceeds_refundable" not in decision.reasons


def test_amount_exceeds_remaining_balance(engine: PolicyEngine) -> None:
    decision = engine.evaluate(facts(total=500_000, refunded=200_000), 300_001, NOW)
    assert decision.eligible is False
    assert "amount_exceeds_refundable" in decision.reasons
    assert decision.refundable_paise == 300_000
    ok = engine.evaluate(facts(total=500_000, refunded=200_000), 300_000, NOW)
    assert ok.eligible is True


def test_zero_and_negative_amounts_rejected(engine: PolicyEngine) -> None:
    assert "amount_not_positive" in engine.evaluate(facts(), 0, NOW).reasons
    assert "amount_not_positive" in engine.evaluate(facts(), -5, NOW).reasons


def test_partial_refunds_can_be_disabled() -> None:
    engine = PolicyEngine(PolicyConfig(allow_partial_refunds=False))
    decision = engine.evaluate(facts(total=500_000), 100_000, NOW)
    assert decision.eligible is False
    assert "partial_refunds_not_allowed" in decision.reasons
    assert engine.evaluate(facts(total=500_000), 500_000, NOW).eligible is True


def test_exception_override_flag_is_reported_only_when_ineligible() -> None:
    engine = PolicyEngine(PolicyConfig(allow_exception_override=True))
    ineligible = engine.evaluate(facts(delivered_days_ago=90), 100_000, NOW)
    assert ineligible.eligible is False and ineligible.exception_override_available is True
    eligible = engine.evaluate(facts(), 100_000, NOW)
    assert eligible.exception_override_available is False


def test_rules_are_fully_reported(engine: PolicyEngine) -> None:
    decision = engine.evaluate(facts(), 150_000, NOW)
    rule_names = {r.rule for r in decision.rules}
    assert rule_names == {
        "eligible_status",
        "refund_window",
        "amount_positive",
        "refundable_balance_available",
        "within_refundable_balance",
        "partial_refund_allowed",
    }
    assert all(r.passed for r in decision.rules)
    assert "auto_approval_tier" in decision.reasons


def test_policy_config_validation() -> None:
    with pytest.raises(ValueError):
        PolicyConfig(eligible_statuses=["NOT_A_STATUS"])
    with pytest.raises(ValueError):
        PolicyConfig(auto_approve_max_paise=500_000, reviewer_max_paise=100_000)
    cfg = PolicyConfig(auto_approve_max_paise=100, reviewer_max_paise=100)
    engine = PolicyEngine(cfg)
    assert engine.evaluate(facts(), 100, NOW).tier == RefundTier.AUTO
    assert engine.evaluate(facts(), 101, NOW).tier == RefundTier.SENIOR_REVIEWER
