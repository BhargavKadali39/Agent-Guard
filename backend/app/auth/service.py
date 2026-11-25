"""Authentication service: credential checks, token issuance and principal resolution."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.permissions import Principal, Role
from app.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.config import Settings
from app.errors import AuthenticationError
from app.models import User

# Fictional demonstration identities. Local development only.
DEMO_USERS: list[dict[str, str]] = [
    {
        "username": "olivia.operator",
        "display_name": "Olivia Fernandes",
        "role": Role.SUPPORT_OPERATOR.value,
    },
    {"username": "ravi.reviewer", "display_name": "Ravi Menon", "role": Role.REVIEWER.value},
    {"username": "sana.senior", "display_name": "Sana Iyer", "role": Role.SENIOR_REVIEWER.value},
    {"username": "arjun.admin", "display_name": "Arjun Kapoor", "role": Role.ADMINISTRATOR.value},
]


class AuthService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def seed_demo_users(self) -> int:
        created = 0
        for spec in DEMO_USERS:
            exists = self.db.scalars(select(User).where(User.username == spec["username"])).first()
            if exists:
                continue
            self.db.add(
                User(
                    username=spec["username"],
                    display_name=spec["display_name"],
                    role=spec["role"],
                    password_hash=hash_password(self.settings.demo_user_password),
                )
            )
            created += 1
        self.db.flush()
        return created

    def authenticate(self, username: str, password: str) -> User:
        user = self.db.scalars(select(User).where(User.username == username.lower())).first()
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise AuthenticationError("invalid username or password")
        return user

    def issue_token(self, user: User) -> tuple[str, datetime]:
        return create_access_token(
            subject=user.id,
            role=user.role,
            secret=self.settings.jwt_secret,
            algorithm=self.settings.jwt_algorithm,
            expires_minutes=self.settings.access_token_expire_minutes,
        )

    def principal_from_token(self, token: str) -> Principal:
        payload = decode_access_token(
            token, secret=self.settings.jwt_secret, algorithm=self.settings.jwt_algorithm
        )
        user = self.db.get(User, str(payload.get("sub", "")))
        if user is None or not user.is_active:
            raise AuthenticationError("user no longer exists or is inactive")
        # The role is always read from the database, never trusted from the token alone.
        return Principal(
            id=user.id, type="user", role=Role(user.role), display_name=user.display_name
        )

    @staticmethod
    def principal_for(user: User) -> Principal:
        return Principal(
            id=user.id, type="user", role=Role(user.role), display_name=user.display_name
        )
