"""Real-provider adapters (mocked HTTP), provider faults, migrations, audit hygiene, seed."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tests.conftest import make_settings

from app.agents.factory import apply_provider_fault, build_provider
from app.agents.llm_providers import AnthropicProvider, OpenAICompatibleProvider
from app.agents.mock_provider import MockAIProvider, extract_amounts_paise
from app.agents.provider import SYSTEM_PROMPT, build_user_prompt
from app.agents.schemas import AgentInterpretation, CandidateOrder, InterpretationRequest
from app.config import Settings
from app.errors import ProviderError
from app.observability.audit import sanitize
from app.services.seed import ORDERS, reset_demo_data, seed_reference_data

REQUEST = InterpretationRequest(
    workflow_id="wf-1",
    customer_id="CUST-1001",
    customer_name="Priya Sharma",
    candidate_orders=[
        CandidateOrder(
            order_id="ORD-1001",
            product_name="Wireless Headphones",
            total_paise=850_000,
            refunded_paise=0,
            status="DELIVERED",
            delivered_at=None,
        )
    ],
    untrusted_message="Headphones ORD-1001 damaged, refund ₹8,500.",
    tools=[],
)
GOOD_PAYLOAD = {
    "intent": "refund_request",
    "order_id": "ord-1001",
    "requested_amount_paise": 850000,
    "reason_category": "damaged",
    "summary": "Refund for damaged headphones",
    "confidence": 0.9,
    "suspected_injection": False,
    "proposed_tool_calls": [
        {"tool": "get_order_information", "arguments": {"order_id": "ORD-1001"}}
    ],
    "unexpected_field": "ignored",
}


# ------------------------------------------------------------------ anthropic
def _anthropic(handler) -> AnthropicProvider:
    return AnthropicProvider(
        api_key="test-key", model="claude-test", transport=httpx.MockTransport(handler)
    )


def test_anthropic_provider_parses_tool_use() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "claude-test-2",
                "content": [
                    {"type": "text", "text": "thinking..."},
                    {"type": "tool_use", "name": "submit_interpretation", "input": GOOD_PAYLOAD},
                ],
            },
        )

    result = _anthropic(handler).interpret(REQUEST)
    assert isinstance(result, AgentInterpretation)
    assert result.order_id == "ORD-1001" and result.provider == "anthropic"
    assert result.model == "claude-test-2" and result.latency_ms is not None
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    body = captured["body"]
    assert body["tool_choice"] == {"type": "tool", "name": "submit_interpretation"}
    assert body["system"] == SYSTEM_PROMPT
    assert "<<END_OF_CUSTOMER_MESSAGE>>" in body["messages"][0]["content"]


def test_anthropic_provider_error_paths() -> None:
    with pytest.raises(ProviderError):
        _anthropic(lambda r: httpx.Response(500, text="boom")).interpret(REQUEST)
    with pytest.raises(ProviderError):
        _anthropic(
            lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": "no"}]})
        ).interpret(REQUEST)
    bad = {**GOOD_PAYLOAD, "confidence": 7}
    with pytest.raises(ProviderError):
        _anthropic(
            lambda r: httpx.Response(
                200,
                json={
                    "content": [{"type": "tool_use", "name": "submit_interpretation", "input": bad}]
                },
            )
        ).interpret(REQUEST)

    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(ProviderError):
        _anthropic(timeout).interpret(REQUEST)
    with pytest.raises(ValueError):
        AnthropicProvider(api_key="", model="m")


# --------------------------------------------------------------------- openai
def _openai(handler) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key="sk-test",
        model="gpt-test",
        base_url="http://llm.local/v1",
        transport=httpx.MockTransport(handler),
    )


def test_openai_compatible_provider_parses_function_call() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "gpt-test",
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "submit_interpretation",
                                        "arguments": json.dumps(GOOD_PAYLOAD),
                                    },
                                }
                            ]
                        }
                    }
                ],
            },
        )

    result = _openai(handler).interpret(REQUEST)
    assert result.requested_amount_paise == 850_000 and result.provider == "openai_compatible"
    assert captured["url"] == "http://llm.local/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["tool_choice"]["function"]["name"] == "submit_interpretation"


def test_openai_compatible_error_paths() -> None:
    with pytest.raises(ProviderError):
        _openai(lambda r: httpx.Response(429, text="rate limited")).interpret(REQUEST)
    with pytest.raises(ProviderError):
        _openai(lambda r: httpx.Response(200, json={"choices": []})).interpret(REQUEST)
    with pytest.raises(ProviderError):
        _openai(
            lambda r: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "submit_interpretation",
                                            "arguments": "{not json",
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        ).interpret(REQUEST)


# -------------------------------------------------------------------- factory
def test_build_provider_from_settings(tmp_path) -> None:
    assert build_provider(make_settings(tmp_path)).name == "mock"
    anthropic = build_provider(
        make_settings(tmp_path, ai_provider="anthropic", anthropic_api_key="k")
    )
    assert anthropic.name == "anthropic" and anthropic.describe()["model"] == "claude-sonnet-5-5"
    openai = build_provider(
        make_settings(
            tmp_path, ai_provider="openai_compatible", openai_api_key="k", openai_model="llama3"
        )
    )
    assert openai.describe() == {"name": "openai_compatible", "model": "llama3", "mode": "remote"}
    with pytest.raises(ValueError):
        make_settings(tmp_path, ai_provider="anthropic")  # key required
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="production", jwt_secret="short")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="production", jwt_secret="change-me-" + "x" * 40)  # type: ignore[call-arg]
    strong = Settings(
        _env_file=None, environment="production", jwt_secret="k" * 48, seed_demo_data=False
    )  # type: ignore[call-arg]
    assert strong.environment == "production"


def test_apply_provider_fault() -> None:
    base = MockAIProvider().interpret(REQUEST)
    assert apply_provider_fault(base, None) is base
    misread = apply_provider_fault(base, "misread_amount")
    assert misread.requested_amount_paise == 8_500_000 and misread.confidence == 0.95
    wrong = apply_provider_fault(base, "wrong_intent")
    assert wrong.intent == "order_status_inquiry"
    low = apply_provider_fault(base, "low_confidence")
    assert low.confidence == 0.3
    no_amount = apply_provider_fault(
        base.model_copy(update={"requested_amount_paise": None}), "misread_amount"
    )
    assert no_amount.requested_amount_paise == 10_000_000


def test_mock_amount_extraction_and_prompt_building() -> None:
    assert extract_amounts_paise("₹8,500 and Rs. 1,200.50 and 300 rupees and INR 99") == [
        850_000,
        120_050,
        30_000,
        9_900,
    ]
    assert extract_amounts_paise("no money here") == []
    prompt = build_user_prompt(REQUEST)
    assert "UNTRUSTED CUSTOMER MESSAGE" in prompt and "ORD-1001" in prompt


# ----------------------------------------------------------------- migrations
def test_alembic_migrations_match_models(tmp_path) -> None:
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext

    from app.database import Base

    url = f"sqlite:///{tmp_path}/migrated.db"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    import os

    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(config, "head")
        engine = create_engine(url)
        with engine.connect() as conn:
            diff = compare_metadata(
                MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
            )
        assert diff == [], diff
        command.downgrade(config, "base")
        with engine.connect() as conn:
            remaining = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert remaining, "downgrade should remove the tables"
        engine.dispose()
    finally:
        os.environ.pop("DATABASE_URL", None)


# --------------------------------------------------------------- audit & seed
def test_audit_payload_sanitisation() -> None:
    assert sanitize(None) is None
    clean = sanitize({"email": "a@b.c", "nested": {"api_key": "x", "ok": 1}, "amount": 5})
    assert clean == {
        "email": "[redacted]",
        "nested": {"api_key": "[redacted]", "ok": 1},
        "amount": 5,
    }


def test_seed_is_idempotent_and_reset_restores_balances(app, db: Session, orchestrator) -> None:
    counts = seed_reference_data(db, app.state.settings)
    assert counts == {"users": 0, "customers": 0, "products": 0, "orders": 0}
    from tests.conftest import OPERATOR

    workflow, _ = orchestrator.submit(
        customer_id="CUST-1005",
        message="Backpack ORD-1009 broken zip, refund ₹1,999.",
        actor=OPERATOR,
    )
    assert orchestrator.orders.get("ORD-1009").refunded_paise == 199_900
    removed = reset_demo_data(db)
    db.commit()
    assert removed["workflows"] == 1 and removed["refund_executions"] == 1
    assert orchestrator.orders.get("ORD-1009").refunded_paise == 0
    seeded = {order_id: refunded for order_id, *_r, refunded in ORDERS}
    assert orchestrator.orders.get("ORD-1011").refunded_paise == seeded["ORD-1011"] == 3_200_000


def test_sample_workflows_seed_runs_once(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.models import Workflow

    settings = make_settings(tmp_path, seed_sample_workflows=True)
    application = create_app(settings, create_schema=True)
    with TestClient(application):
        session: Session = application.state.session_factory()
        states = {w.client_request_id: w.state for w in session.query(Workflow).all()}
        session.close()
    assert states["seed:auto-boundary"] == "COMPLETED"
    assert states["seed:reviewer-boundary"] == "AWAITING_APPROVAL"
    assert states["seed:outside-window"] == "REJECTED"
    assert states["seed:transient-failure"] == "FAILED"
    assert states["seed:reviewer-approved"] == "COMPLETED"
    assert states["seed:reviewer-rejected"] == "REJECTED"
    application.state.engine.dispose()
    # Second start-up with the same database must not duplicate the samples.
    again = create_app(make_settings(tmp_path, seed_sample_workflows=True), create_schema=True)
    with TestClient(again):
        session = again.state.session_factory()
        assert session.query(Workflow).count() == len(states)
        session.close()
    again.state.engine.dispose()
