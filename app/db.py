"""Engine, session factory, and schema bootstrap."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models.base import Base

# check_same_thread=False is required because FastAPI serves requests from a
# thread pool while SQLite defaults to pinning a connection to one thread.
_connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}

engine = create_engine(settings.db_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_schema(drop_first: bool = False) -> None:
    """Create all tables. Import models first so they register on Base.metadata."""
    import app.models  # noqa: F401  (registers every mapped class)

    if drop_first:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
