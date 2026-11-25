"""Policy persistence: the active policy lives in the database and is versioned."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import RefundPolicy
from app.policies.engine import DEFAULT_POLICY_CONFIG, PolicyConfig, PolicyEngine

DEFAULT_POLICY_NAME = "standard-refund-policy"


class PolicyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active(self) -> RefundPolicy:
        policy = self.db.scalars(
            select(RefundPolicy)
            .where(RefundPolicy.is_active.is_(True))
            .order_by(RefundPolicy.version.desc())
        ).first()
        if policy is None:
            raise NotFoundError("no active refund policy configured")
        return policy

    def engine(self) -> PolicyEngine:
        policy = self.get_active()
        return PolicyEngine(
            PolicyConfig.model_validate(policy.config), name=policy.name, version=policy.version
        )

    def ensure_default(self) -> RefundPolicy:
        existing = self.db.scalars(select(RefundPolicy).where(RefundPolicy.is_active.is_(True)))
        policy = existing.first()
        if policy is not None:
            return policy
        policy = RefundPolicy(
            name=DEFAULT_POLICY_NAME,
            version=1,
            is_active=True,
            config=DEFAULT_POLICY_CONFIG.model_dump(),
            created_by="system",
        )
        self.db.add(policy)
        self.db.flush()
        return policy

    def publish(self, config: PolicyConfig, *, created_by: str | None) -> RefundPolicy:
        """Create a new active version and retire the previous one."""
        current = self.db.scalars(
            select(RefundPolicy).where(RefundPolicy.is_active.is_(True))
        ).all()
        next_version = 1
        name = DEFAULT_POLICY_NAME
        for old in current:
            old.is_active = False
            next_version = max(next_version, old.version + 1)
            name = old.name
        policy = RefundPolicy(
            name=name,
            version=next_version,
            is_active=True,
            config=config.model_dump(),
            created_by=created_by,
        )
        self.db.add(policy)
        self.db.flush()
        return policy

    def history(self) -> list[RefundPolicy]:
        return list(self.db.scalars(select(RefundPolicy).order_by(RefundPolicy.version.desc())))
