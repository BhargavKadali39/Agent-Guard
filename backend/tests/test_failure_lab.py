"""Every Failure Lab scenario must pass its own executable assertions, repeatedly."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from tests.conftest import OPERATOR

from app.evaluations.failure_lab import SCENARIOS, FailureLab
from app.models import LabRun


@pytest.fixture
def lab(app, db: Session) -> FailureLab:
    return FailureLab(
        db,
        settings=app.state.settings,
        registry=app.state.registry,
        injector=app.state.injector,
        engine=app.state.engine,
        session_factory=app.state.session_factory,
    )


def test_scenario_catalogue() -> None:
    keys = [s.key for s in SCENARIOS]
    assert keys == [
        "prompt_injection",
        "unauthorized_tool_execution",
        "duplicate_refund_request",
        "workflow_interruption",
        "human_approval_rejection",
        "agent_decision_error",
    ]
    for scenario in SCENARIOS:
        assert scenario.expected_behavior and scenario.explanation and scenario.initial_request


@pytest.mark.parametrize("key", [s.key for s in SCENARIOS])
def test_each_scenario_passes_with_real_assertions(lab: FailureLab, db: Session, key: str) -> None:
    result = lab.run(key, run_by=OPERATOR)
    failed = [a for a in result.assertions if not a.passed]
    assert result.passed, f"{key} failed assertions: {[(a.name, a.detail) for a in failed]}"
    assert len(result.assertions) >= 5
    assert result.workflow_ids and result.events
    assert result.observed_behavior
    stored = db.get(LabRun, result.run_id)
    assert stored is not None and stored.passed is True and stored.scenario_key == key
    assert stored.result["assertions"] == [a.model_dump() for a in result.assertions]


def test_scenarios_are_repeatable(lab: FailureLab) -> None:
    for _ in range(2):
        for key in ("duplicate_refund_request", "workflow_interruption"):
            assert lab.run(key, run_by=OPERATOR).passed


def test_lab_over_http(client: TestClient, operator_headers) -> None:
    scenarios = client.get("/api/failure-lab/scenarios", headers=operator_headers).json()
    assert len(scenarios) == 6
    result = client.post(
        "/api/failure-lab/scenarios/human_approval_rejection/run", headers=operator_headers
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["passed"] is True
    assert all(a["passed"] for a in body["assertions"])
    assert body["scenario"]["key"] == "human_approval_rejection"
    runs = client.get("/api/failure-lab/runs", headers=operator_headers).json()
    assert runs[0]["scenario_key"] == "human_approval_rejection" and runs[0]["passed"] is True
    assert (
        client.post("/api/failure-lab/scenarios/nope/run", headers=operator_headers).status_code
        == 404
    )


def test_a_broken_invariant_is_reported_not_hidden(lab: FailureLab, monkeypatch) -> None:
    """If the system misbehaves, the scenario must fail: results are never hardcoded."""
    from app.evaluations import failure_lab as module

    def sabotaged(ctx) -> None:
        ctx.check("always_false", False, "deliberately failing assertion")

    monkeypatch.setitem(
        module.SCENARIOS_BY_KEY,
        "prompt_injection",
        module.Scenario(
            key="prompt_injection",
            title="t",
            category="c",
            description="d",
            initial_request="r",
            expected_behavior="e",
            explanation="x",
            runner=sabotaged,
        ),
    )
    result = lab.run("prompt_injection", run_by=OPERATOR)
    assert result.passed is False
    assert [a.name for a in result.assertions if not a.passed] == ["always_false"]

    def crashing(ctx) -> None:
        raise RuntimeError("boom")

    module.SCENARIOS_BY_KEY["prompt_injection"].runner = crashing  # type: ignore[attr-defined]
    crashed = lab.run("prompt_injection", run_by=OPERATOR)
    assert crashed.passed is False
    assert crashed.assertions[-1].name == "scenario_executed_without_errors"
    assert "RuntimeError" in crashed.assertions[-1].detail
