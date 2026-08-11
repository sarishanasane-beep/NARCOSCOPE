"""NARCOSCOPE Phase 1 — FastAPI application entry point.

Run from ``backend/``:

    uvicorn app.main:app --reload

The application runs in deterministic (non-AI) mode when no AI API key
is configured.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from app.config.settings import settings
from app.database.init_db import init_db
from app.services.ai.service import get_ai_service
from app.utils.errors import AppError
from app.utils.logging import setup_logging

setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

from app.api.routes import (  # noqa: E402
    audit,
    bookmarks,
    candidates,
    cases,
    changes,
    cross_case,
    documents,
    entities,
    events,
    evidence,
    graph,
    health,
    notes,
    priority,
    relationships,
    saved_searches,
    search,
    snapshots,
    sources,
    timeline,
    workspaces,
)

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Evidence-backed investigation-support platform (Phase 1). "
        "AI is optional; the application runs in deterministic mode when "
        "no API key is configured."
    ),
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    ai = get_ai_service()
    logger.info(
        "startup complete ai_enabled=%s provider=%s database=%s",
        ai.ai_enabled,
        ai.provider.name,
        settings.database_url,
    )


# ---------------------------------------------------------------------------
# Centralized error handling — users see human-readable messages only.
# Technical details are logged server-side.
# ---------------------------------------------------------------------------

@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    if exc.technical:
        logger.warning("app_error message=%s technical=%s", exc.message, exc.technical)
    else:
        logger.warning("app_error message=%s", exc.message)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error type=%s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again later."},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(sources.router)
app.include_router(evidence.router)
app.include_router(cases.router)
app.include_router(graph.router)
app.include_router(entities.router)
app.include_router(events.router)
app.include_router(relationships.router)
app.include_router(candidates.router)
app.include_router(audit.router)
app.include_router(search.router)
app.include_router(snapshots.router)
app.include_router(changes.router)
app.include_router(priority.router)
app.include_router(timeline.router)
app.include_router(cross_case.router)
app.include_router(workspaces.router)
app.include_router(bookmarks.router)
app.include_router(notes.router)
app.include_router(saved_searches.router)

_FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Minimal API-testing interface for Phase 1."""
    return FileResponse(_FRONTEND)
