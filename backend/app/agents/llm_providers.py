"""Real LLM providers (optional). Configured only through environment variables.

Both providers force a structured "submit_interpretation" tool call so the model's
output is always a validated ``AgentInterpretation`` rather than free text. They talk to
the vendors' public REST APIs through ``httpx`` so there is no SDK version coupling, and
they are unit-tested with mocked transports.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app.agents.provider import SYSTEM_PROMPT, AIProvider, build_user_prompt
from app.agents.schemas import (
    INTERPRETATION_JSON_SCHEMA,
    AgentInterpretation,
    InterpretationRequest,
)
from app.errors import ProviderError

logger = logging.getLogger(__name__)

TOOL_NAME = "submit_interpretation"
TOOL_DESCRIPTION = (
    "Submit the structured interpretation of the customer's message. Always call this exactly once."
)


def _parse_interpretation(payload: Any, *, provider: str, model: str | None, latency_ms: int):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{provider} returned non-JSON tool arguments") from exc
    if not isinstance(payload, dict):
        raise ProviderError(f"{provider} returned an unexpected tool payload type")
    data = dict(payload)
    data.update({"provider": provider, "model": model, "latency_ms": latency_ms})
    try:
        return AgentInterpretation.model_validate(data)
    except ValidationError as exc:
        raise ProviderError(
            f"{provider} interpretation failed validation: {exc.errors()[:3]}"
        ) from exc


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        timeout: float = 30.0,
        max_tokens: int = 1024,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Anthropic API key is required")
        self.model = model
        self.max_tokens = max_tokens
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            transport=transport,
        )

    def describe(self) -> dict[str, str]:
        return {"name": self.name, "model": self.model, "mode": "remote"}

    def interpret(self, request: InterpretationRequest) -> AgentInterpretation:
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": build_user_prompt(request)}],
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": TOOL_DESCRIPTION,
                    "input_schema": INTERPRETATION_JSON_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        }
        started = time.perf_counter()
        try:
            response = self._client.post("/v1/messages", json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"anthropic request failed: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            raise ProviderError(
                f"anthropic API error {response.status_code}",
                details={"body": response.text[:500]},
            )
        data = response.json()
        for block in data.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
                return _parse_interpretation(
                    block.get("input"),
                    provider=self.name,
                    model=data.get("model", self.model),
                    latency_ms=latency_ms,
                )
        raise ProviderError("anthropic response did not include the interpretation tool call")


class OpenAICompatibleProvider(AIProvider):
    """Works with OpenAI and any OpenAI-compatible endpoint (Groq, Ollama, OpenRouter...)."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI-compatible API key is required")
        self.model = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            transport=transport,
        )

    def describe(self) -> dict[str, str]:
        return {"name": self.name, "model": self.model, "mode": "remote"}

    def interpret(self, request: InterpretationRequest) -> AgentInterpretation:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(request)},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": TOOL_NAME,
                        "description": TOOL_DESCRIPTION,
                        "parameters": INTERPRETATION_JSON_SCHEMA,
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        }
        started = time.perf_counter()
        try:
            response = self._client.post("/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"openai-compatible request failed: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            raise ProviderError(
                f"openai-compatible API error {response.status_code}",
                details={"body": response.text[:500]},
            )
        data = response.json()
        try:
            message = data["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("openai-compatible response had no choices") from exc
        for call in tool_calls:
            function = call.get("function") or {}
            if function.get("name") == TOOL_NAME:
                return _parse_interpretation(
                    function.get("arguments"),
                    provider=self.name,
                    model=data.get("model", self.model),
                    latency_ms=latency_ms,
                )
        raise ProviderError("openai-compatible response did not include the interpretation call")
