"""FastAPI dependencies: settings, database sessions, authentication and authorization."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.agents.orchestrator import WorkflowOrchestrator
from app.auth.permissions import Permission, Principal
from app.auth.service import AuthService
from app.config import Settings
from app.errors import AuthenticationError, PermissionDenied
from app.evaluations.failure_lab import FailureLab

bearer_scheme = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Generator[Session, None, None]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


def get_current_principal(
    db: DbDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("missing bearer token")
    return AuthService(db, settings).principal_from_token(credentials.credentials)


PrincipalDep = Annotated[Principal, Depends(get_current_principal)]


def require(*permissions: Permission) -> Callable[..., Principal]:
    """Dependency factory: the caller must hold *all* of the given permissions."""

    def dependency(principal: PrincipalDep) -> Principal:
        missing = [p.value for p in permissions if not principal.can(p)]
        if missing:
            raise PermissionDenied(
                f"role {principal.role.value} lacks permission(s): {', '.join(missing)}",
                details={"missing_permissions": missing},
            )
        return principal

    return dependency


def get_orchestrator(request: Request, db: DbDep) -> WorkflowOrchestrator:
    state = request.app.state
    return WorkflowOrchestrator(
        db,
        settings=state.settings,
        provider=state.provider,
        registry=state.registry,
        injector=state.injector,
    )


OrchestratorDep = Annotated[WorkflowOrchestrator, Depends(get_orchestrator)]


def get_failure_lab(request: Request, db: DbDep) -> FailureLab:
    state = request.app.state
    return FailureLab(
        db,
        settings=state.settings,
        registry=state.registry,
        injector=state.injector,
        engine=state.engine,
        session_factory=state.session_factory,
    )


FailureLabDep = Annotated[FailureLab, Depends(get_failure_lab)]
