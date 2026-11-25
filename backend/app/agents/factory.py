"""Provider selection and simulated provider faults."""

from __future__ import annotations

from app.agents.llm_providers import AnthropicProvider, OpenAICompatibleProvider
from app.agents.mock_provider import MockAIProvider
from app.agents.provider import AIProvider
from app.agents.schemas import AgentInterpretation
from app.config import Settings


def build_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "anthropic":
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            base_url=settings.anthropic_base_url,
            timeout=settings.ai_timeout_seconds,
            max_tokens=settings.ai_max_tokens,
        )
    if settings.ai_provider == "openai_compatible":
        return OpenAICompatibleProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            timeout=settings.ai_timeout_seconds,
        )
    return MockAIProvider(injection_behavior=settings.mock_injection_behavior)


def apply_provider_fault(
    interpretation: AgentInterpretation, fault: str | None
) -> AgentInterpretation:
    """Deterministically corrupt an interpretation to emulate an agent decision error.

    Used by the Failure Lab (scenario 6) and tests. Works for any provider so the
    downstream validation can be demonstrated regardless of which model is configured.
    """
    if not fault:
        return interpretation
    data = interpretation.model_dump()
    if fault == "misread_amount":
        if data["requested_amount_paise"]:
            data["requested_amount_paise"] = data["requested_amount_paise"] * 10
        else:
            data["requested_amount_paise"] = 10_000_000  # ₹1,00,000 out of thin air
        data["confidence"] = 0.95
        data["summary"] = f"[simulated misread] {data['summary']}"
    elif fault == "wrong_intent":
        data["intent"] = "order_status_inquiry"
        data["confidence"] = 0.95
        data["summary"] = "[simulated misclassification] Customer is asking about order status."
    elif fault == "low_confidence":
        data["confidence"] = 0.3
    return AgentInterpretation.model_validate(data)
