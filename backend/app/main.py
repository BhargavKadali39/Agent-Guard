"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.agents.factory import build_provider
from app.agents.mock_provider import MockAIProvider
from app.agents.orchestrator import WorkflowOrchestrator
from app.api import (
    routes_approvals,
    routes_auth,
    routes_commerce,
    routes_lab_admin,
    routes_observability,
    routes_workflows,
)
from app.config import Settings, get_settings
from app.database import Base, make_engine, make_session_factory
from app.errors import AgentGuardError
from app.evaluations.failure_injection import FailureInjector
from app.observability.logging import configure_logging
from app.services.seed import seed_reference_data, seed_sample_workflows
from app.tools.refund_tools import build_registry

logger = logging.getLogger("agentguard")

APP_VERSION = "0.1.0"


def create_app(settings: Settings | None = None, *, create_schema: bool | None = None) -> FastAPI:
    """Build the application.

    ``create_schema`` controls whether tables are created with ``Base.metadata.create_all``
    at startup. The default (``None``) creates them only for SQLite, which is the zero-setup
    local path; PostgreSQL deployments run ``alembic upgrade head`` (see docker-compose).
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    engine = make_engine(settings.database_url, echo=settings.db_echo)
    session_factory = make_session_factory(engine)
    if create_schema is None:
        create_schema = settings.is_sqlite

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if create_schema:
            Base.metadata.create_all(engine)
        db: Session = session_factory()
        try:
            if settings.seed_demo_data:
                counts = seed_reference_data(db, settings)
                db.commit()
                logger.info("demo reference data ready", extra={"seeded": counts})
                seeder = WorkflowOrchestrator(
                    db,
                    settings=settings,
                    provider=MockAIProvider(settings.mock_injection_behavior),
                    registry=app.state.registry,
                    injector=app.state.injector,
                )
                if settings.seed_sample_workflows:
                    created = seed_sample_workflows(db, seeder, settings)
                    if created:
                        logger.info("seeded %d sample workflows", created)
            if settings.auto_recover_on_startup:
                recoverer = WorkflowOrchestrator(
                    db,
                    settings=settings,
                    provider=app.state.provider,
                    registry=app.state.registry,
                    injector=app.state.injector,
                )
                recovered = recoverer.recover_in_flight()
                if recovered:
                    logger.info("recovered %d in-flight workflow(s)", len(recovered))
        finally:
            db.close()
        yield
        engine.dispose()

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=APP_VERSION,
        description="AI agent reliability & security demonstration platform (The GenAI Foundry). "
        "Simulation only: no real customers, no real money.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.provider = build_provider(settings)
    app.state.registry = build_registry()
    app.state.injector = FailureInjector()

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        logger.info(
            "%s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        return response

    @app.exception_handler(AgentGuardError)
    async def domain_error_handler(_: Request, exc: AgentGuardError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_failed",
                    "message": "request validation failed",
                    "details": {"errors": errors},
                }
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_value", "message": str(exc), "details": {}}},
        )

    app.include_router(routes_auth.router)
    app.include_router(routes_commerce.router)
    app.include_router(routes_workflows.router)
    app.include_router(routes_approvals.router)
    app.include_router(routes_observability.router)
    app.include_router(routes_lab_admin.router)
    return app


app = create_app()
