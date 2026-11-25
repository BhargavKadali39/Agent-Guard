"""Deterministic mock AI provider.

Runs with no API keys and produces repeatable interpretations from simple text rules so
tests, the Failure Lab and offline workshops behave identically every time.

By design the mock can *simulate a model that falls for prompt injection* (the default,
``mock_injection_behavior="comply"``): when it spots instruction-like text it proposes the
unauthorized tool calls the attacker asked for. That is deliberate. The point of
AgentGuard is that the backend refuses those proposals whether or not the model was
fooled. Set ``MOCK_INJECTION_BEHAVIOR=resist`` to simulate a model that ignores them.
"""

from __future__ import annotations

import re
import time
from decimal import ROUND_HALF_UP, Decimal

from app.agents.provider import AIProvider
from app.agents.scanner import scanner
from app.agents.schemas import (
    AgentInterpretation,
    InterpretationRequest,
    ProposedToolCall,
    ReasonCategory,
)

_ORDER_ID = re.compile(r"\bORD-\d{4}\b", re.IGNORECASE)
_AMOUNT_PREFIX = re.compile(r"(?:₹|rs\.?|inr)\s*(\d[\d,]*(?:\.\d{1,2})?)", re.IGNORECASE)
_AMOUNT_SUFFIX = re.compile(r"(\d[\d,]*(?:\.\d{1,2})?)\s*(?:rupees|rs\b|inr\b|/-)", re.IGNORECASE)

_REFUND_WORDS = (
    "refund",
    "money back",
    "reimburse",
    "return",
    "damaged",
    "defective",
    "broken",
    "not working",
    "cracked",
    "faulty",
    "wrong item",
    "never arrived",
    "not delivered",
)
_STATUS_WORDS = ("where is my order", "track", "status", "when will", "delivery date", "eta")
_CANCEL_WORDS = ("cancel",)

_REASONS: dict[ReasonCategory, tuple[str, ...]] = {
    "damaged": ("damaged", "broken", "cracked", "dented", "shattered", "smashed"),
    "defective": ("defective", "faulty", "not working", "doesn't work", "stopped working", "dead"),
    "not_as_described": ("not as described", "different from", "misleading", "not what i ordered"),
    "late_delivery": ("late", "delayed", "never arrived", "not delivered", "still waiting"),
    "wrong_item": ("wrong item", "wrong product", "different item", "wrong size", "wrong colour"),
    "changed_mind": ("changed my mind", "don't need", "no longer need", "not needed"),
}
# A request to change account details. A naive agent "helpfully" attempts it even though
# it has no permission to do so; the registry denies it (Failure Lab scenario 2).
_ACCOUNT_CHANGE = re.compile(
    r"\b(update|change|set|mark|upgrade|make)\b.{0,40}"
    r"\b(e-?mail|vip|account|tier|store credit|address|phone)\b",
    re.IGNORECASE | re.DOTALL,
)


def _to_paise(text: str) -> int:
    value = Decimal(text.replace(",", ""))
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def extract_amounts_paise(message: str) -> list[int]:
    """All distinct amounts mentioned, in the order they appear in the text."""
    matches: list[tuple[int, int]] = []
    for pattern in (_AMOUNT_PREFIX, _AMOUNT_SUFFIX):
        for match in pattern.finditer(message):
            try:
                paise = _to_paise(match.group(1))
            except Exception:  # pragma: no cover - regex guarantees numeric text
                continue
            if paise > 0:
                matches.append((match.start(), paise))
    found: list[int] = []
    for _pos, paise in sorted(matches):
        if paise not in found:
            found.append(paise)
    return found


class MockAIProvider(AIProvider):
    name = "mock"

    def __init__(self, injection_behavior: str = "comply") -> None:
        self.injection_behavior = injection_behavior

    def describe(self) -> dict[str, str]:
        return {
            "name": self.name,
            "model": f"deterministic-rules (injection_behavior={self.injection_behavior})",
            "mode": "offline",
        }

    def interpret(self, request: InterpretationRequest) -> AgentInterpretation:
        started = time.perf_counter()
        message = request.untrusted_message
        lower = message.lower()
        scan = scanner.scan(message)

        # ---- intent -------------------------------------------------------------
        refund_score = sum(1 for w in _REFUND_WORDS if w in lower)
        status_score = sum(1 for w in _STATUS_WORDS if w in lower)
        cancel_score = sum(1 for w in _CANCEL_WORDS if w in lower)
        if refund_score and refund_score >= cancel_score:
            intent = "refund_request"
            confidence = 0.92
        elif cancel_score:
            intent = "cancel_order"
            confidence = 0.8
        elif status_score:
            intent = "order_status_inquiry"
            confidence = 0.8
        else:
            intent = "unknown"
            confidence = 0.4

        # ---- reason -------------------------------------------------------------
        reason: ReasonCategory = "unknown"
        for category, words in _REASONS.items():
            if any(w in lower for w in words):
                reason = category
                break
        if reason == "unknown" and intent == "refund_request":
            reason = "other"

        # ---- order ---------------------------------------------------------------
        order_id: str | None = None
        ids = [m.group(0).upper() for m in _ORDER_ID.finditer(message)]
        candidates = request.candidate_orders
        if ids:
            order_id = ids[0]
            if len(set(ids)) > 1:
                confidence -= 0.15
        else:
            # Try to match a product name ("my headphones") against the customer's orders.
            matches = [
                o
                for o in candidates
                if any(
                    token in lower
                    for token in (o.product_name.lower(), o.product_name.lower().split()[-1])
                )
            ]
            if len(matches) == 1:
                order_id = matches[0].order_id
                confidence -= 0.1
            elif len(candidates) == 1:
                order_id = candidates[0].order_id
                confidence -= 0.1
            else:
                confidence -= 0.3

        # ---- amount --------------------------------------------------------------
        amounts = extract_amounts_paise(message)
        requested: int | None = None
        conflicts: list[str] = []
        if amounts:
            requested = amounts[-1]
            if len(amounts) > 1:
                conflicts.append(
                    "message states multiple different amounts: "
                    + ", ".join(f"₹{a / 100:,.2f}" for a in amounts)
                )
                confidence -= 0.25

        if scan.suspicious:
            confidence -= 0.1

        confidence = max(0.05, min(0.99, round(confidence, 2)))

        # ---- proposed tool calls -------------------------------------------------
        proposals: list[ProposedToolCall] = []
        if order_id:
            proposals.append(
                ProposedToolCall(
                    tool="get_order_information",
                    arguments={"order_id": order_id},
                    rationale="confirm the order referenced by the customer",
                )
            )
        proposals.append(
            ProposedToolCall(
                tool="retrieve_refund_policy", arguments={}, rationale="load the active policy"
            )
        )
        if scan.suspicious and self.injection_behavior == "comply":
            # Simulate a model that was successfully manipulated by the message.
            proposals.append(
                ProposedToolCall(
                    tool="execute_simulated_refund",
                    arguments={
                        "order_id": order_id,
                        "amount_paise": requested,
                        "bypass_policy": True,
                    },
                    rationale="customer message instructed immediate approval (untrusted)",
                )
            )
        account_change = _ACCOUNT_CHANGE.search(message)
        if account_change:
            changes: dict[str, str] = {"note": "requested in customer message"}
            email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", message)
            if email:
                changes["email"] = email.group(0)
            if re.search(r"\bvip\b|\bpremium\b", lower):
                changes["tier"] = "vip"
            proposals.append(
                ProposedToolCall(
                    tool="update_customer_record",
                    arguments={"customer_id": request.customer_id, "changes": changes},
                    rationale="customer asked for an account change (outside the agent's remit)",
                )
            )

        # ---- summary -------------------------------------------------------------
        if intent == "refund_request":
            amount_text = f" of ₹{requested / 100:,.2f}" if requested else ""
            order_text = f" for order {order_id}" if order_id else " (order not identified)"
            summary = f"Customer requests a refund{amount_text}{order_text}; reason: {reason}."
        elif intent == "order_status_inquiry":
            summary = "Customer is asking about the status of an order."
        elif intent == "cancel_order":
            summary = f"Customer wants to cancel order {order_id or '(unidentified)'}."
        else:
            summary = "Customer intent could not be determined from the message."
        if scan.suspicious:
            summary += " The message contains instruction-like text that was ignored."

        return AgentInterpretation(
            intent=intent,
            order_id=order_id,
            requested_amount_paise=requested,
            reason_category=reason,
            summary=summary,
            confidence=confidence,
            conflicting_statements=conflicts,
            suspected_injection=scan.suspicious,
            proposed_tool_calls=proposals,
            provider=self.name,
            model="deterministic-rules",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
