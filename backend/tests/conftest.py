"""Shared test fixtures.

Each test gets its own application instance backed by a file-based SQLite database in a
temporary directory (file-based so threads and the Failure Lab's concurrency checks work).
Set AGENTGUARD_TEST_DATABASE_URL to run the same suite against PostgreSQL.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.mock_provider import MockAIProvider
from app.agents.orchestrator import WorkflowOrchestrator
from app.auth.permissions import Principal, Role
from app.config import Settings
from app.database import Base, make_engine
from app.main import create_app

TEST_JWT_SECRET = "unit-test-secret-value-that-is-long-enough-0123456789"
DEMO_PASSWORD = "test-demo-password"


def _database_url(tmp_path) -> str:
    override = os.environ.get("AGENTGUARD_TEST_DATABASE_URL")
    if override:
        return override
    return f"sqlite:///{tmp_path}/agentguard-test.db"


def make_settings(tmp_path, **overrides) -> Settings:
    values = {
        "environment": "test",
        "database_url": _database_url(tmp_path),
        "jwt_secret": TEST_JWT_SECRET,
        "seed_demo_data": True,
        "seed_sample_workflows": False,
        "demo_user_password": DEMO_PASSWORD,
        "ai_provider": "mock",
        "tool_retry_backoff_seconds": 0.0,
        "log_level": "WARNING",
        "auto_recover_on_startup": False,
        "cors_origins": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _reset_postgres(url: str) -> None:
    """When running against PostgreSQL, start every test from an empty schema."""
    engine = make_engine(url)
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    if not settings.is_sqlite:
        _reset_postgres(settings.database_url)
    application = create_app(settings, create_schema=True)
    with TestClient(application):
        yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(app: FastAPI) -> Iterator[Session]:
    session: Session = app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def orchestrator(app: FastAPI, db: Session) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        db,
        settings=app.state.settings,
        provider=MockAIProvider("comply"),
        registry=app.state.registry,
        injector=app.state.injector,
    )


def login(client: TestClient, username: str, password: str = DEMO_PASSWORD) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def operator_headers(client: TestClient) -> dict[str, str]:
    return login(client, "olivia.operator")


@pytest.fixture
def reviewer_headers(client: TestClient) -> dict[str, str]:
    return login(client, "ravi.reviewer")


@pytest.fixture
def senior_headers(client: TestClient) -> dict[str, str]:
    return login(client, "sana.senior")


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    return login(client, "arjun.admin")


OPERATOR = Principal(id="test:operator", type="user", role=Role.SUPPORT_OPERATOR, display_name="Op")
REVIEWER = Principal(id="test:reviewer", type="user", role=Role.REVIEWER, display_name="Rev")
SENIOR = Principal(id="test:senior", type="user", role=Role.SENIOR_REVIEWER, display_name="Senior")
ADMIN = Principal(id="test:admin", type="user", role=Role.ADMINISTRATOR, display_name="Admin")
