"""Application entrypoint.

The database is rebuilt from the source file on every startup. That is a real
tradeoff, not an oversight: the file is the source of truth, there are no
migrations to reason about, and any run is reproducible from scratch. What it
costs is persistence -- anything written through the API dies on restart. See
the README's "Known limitations".
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import SessionLocal, create_schema
from app.errors import register_error_handlers
from app.ingest.loader import ingest_file
from app.routers import health, ingest, patients, raw

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.testing:
        yield
        return

    create_schema(drop_first=settings.reset_on_startup)
    if settings.reset_on_startup:
        session = SessionLocal()
        try:
            summary = ingest_file(settings.data_file, session)
            app.state.ingest_summary = summary
        finally:
            session.close()
    yield


app = FastAPI(
    title="Novellia Health API",
    version="0.1.0",
    description=(
        "A patient-centric API over FHIR clinical data.\n\n"
        "The primary surface under `/patients` is translated for product "
        "consumers and contains no FHIR vocabulary. `/fhir` returns source "
        "resources unchanged for integration work, and `/ingest` exposes "
        "exactly what arrived and what could not be resolved."
    ),
    lifespan=lifespan,
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(patients.router)
app.include_router(ingest.router)
app.include_router(raw.router)
