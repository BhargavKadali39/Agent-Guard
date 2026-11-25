"""Database engine/session helpers shared by the application, migrations and tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes that behave identically on SQLite and PostgreSQL.

    SQLite discards tzinfo, so values are normalised to UTC on the way in and re-tagged
    as UTC on the way out.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:  # type: ignore[override]
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed; use timezone-aware UTC values")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:  # type: ignore[override]
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


# JSON column that becomes JSONB on PostgreSQL and plain JSON elsewhere.
PortableJSON = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create an engine with sensible defaults for the configured backend."""
    if database_url.startswith("sqlite"):
        in_memory = (
            database_url in ("sqlite://", "sqlite:///:memory:") or ":memory:" in database_url
        )
        connect_args = {"check_same_thread": False, "timeout": 30}
        if in_memory:
            engine = create_engine(
                database_url, connect_args=connect_args, poolclass=StaticPool, echo=echo
            )
        else:
            engine = create_engine(database_url, connect_args=connect_args, echo=echo)

        @event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection, _record) -> None:  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            if not in_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return engine
    return create_engine(database_url, echo=echo, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
    finally:
        session.close()
