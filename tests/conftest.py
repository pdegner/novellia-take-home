"""Test harness: an isolated in-memory database per test, loaded from a file."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers mapped classes)
from app.config import settings

from app.db import get_session
from app.ingest.loader import IngestSummary, ingest_file
from app.main import app as fastapi_app
from app.models import Base

# Read by the lifespan hook when TestClient starts the app, so setting it at
# import time is early enough.
settings.testing = True

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
REAL_DATA = REPO_ROOT / "instructions" / "backend-takehome-fhir-resources.txt"


@pytest.fixture
def session() -> Iterator[Session]:
    """A fresh empty database.

    StaticPool keeps every connection pointed at the same in-memory database;
    without it each connection would get its own and the tables would vanish.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def load(session: Session) -> Callable[[Path | str], IngestSummary]:
    """Ingest a file into the test database and hand back the summary."""

    def _load(path: Path | str) -> IngestSummary:
        return ingest_file(path, session)

    return _load


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """A TestClient bound to the test database, with startup ingest disabled.

    Tests choose their own data by calling the `load` fixture, so the app's
    lifespan hook must not also load the real file underneath them.
    """
    fastapi_app.dependency_overrides[get_session] = lambda: session
    # Bypassing the lifespan avoids create_schema/ingest against the real engine.
    with TestClient(fastapi_app, raise_server_exceptions=False) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()
