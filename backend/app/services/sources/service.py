"""Source service.

A source describes the publisher/origin of a document. The source type
describes the origin only — it does not prove statements inside the
document are true.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.source import SOURCE_TYPE_UNKNOWN, Source
from app.utils.errors import NotFoundError
from app.utils.logging import log_event

import logging

logger = logging.getLogger(__name__)


def create_source(
    db: Session,
    *,
    publisher: str | None = None,
    agency: str | None = None,
    source_type: str | None = None,
    source_url: str | None = None,
    publication_date: date | None = None,
    document_id: str | None = None,
) -> Source:
    source = Source(
        source_id=str(uuid.uuid4()),
        publisher=publisher,
        agency=agency,
        source_type=source_type or SOURCE_TYPE_UNKNOWN,
        source_url=source_url,
        publication_date=publication_date,
        document_id=document_id,
    )
    db.add(source)
    db.flush()
    log_event(logger, "source_created", source_id=source.source_id, source_type=source.source_type)
    return source


def get_source(db: Session, source_id: str) -> Source:
    source = db.get(Source, source_id)
    if source is None:
        raise NotFoundError("Source not found.")
    return source


def list_sources(db: Session, limit: int = 100, offset: int = 0) -> list[Source]:
    return db.query(Source).order_by(Source.created_at.desc()).offset(offset).limit(limit).all()
