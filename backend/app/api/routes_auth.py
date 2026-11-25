"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbDep, PrincipalDep, SettingsDep
from app.auth.permissions import PERMISSION_MATRIX
from app.auth.service import DEMO_USERS, AuthService
from app.models import User
from app.schemas.api import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.permissions = sorted(p.value for p in PERMISSION_MATRIX[user.role])  # type: ignore[index]
    return out


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: DbDep, settings: SettingsDep) -> TokenResponse:
    service = AuthService(db, settings)
    user = service.authenticate(body.username, body.password)
    token, expires_at = service.issue_token(user)
    return TokenResponse(access_token=token, expires_at=expires_at, user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me(principal: PrincipalDep, db: DbDep) -> UserOut:
    user = db.get(User, principal.id)
    assert user is not None  # principal resolution already verified existence
    return _user_out(user)


@router.get("/demo-users")
def demo_users(settings: SettingsDep) -> dict:
    """Demo identities for the login page. Only exposed outside production."""
    if settings.environment == "production" or not settings.seed_demo_data:
        return {"enabled": False, "users": []}
    return {
        "enabled": True,
        "password": settings.demo_user_password,
        "users": [
            {"username": u["username"], "role": u["role"], "display_name": u["display_name"]}
            for u in DEMO_USERS
        ],
    }
