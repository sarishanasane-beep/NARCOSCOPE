"""Document processing pipeline.

UPLOADED -> PROCESSING -> (extract -> clean -> structured extraction
-> candidates) -> PROCESSED / REVIEW_REQUIRED / FAILED

Failures never crash the application: they set ``processing_status =
FAILED`` with a useful error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.document import (
    STATUS_FAILED,
    STATUS_PROCESSED,
    STATUS_PROCESSING,
    STATUS_REVIEW_REQUIRED,
    Document,
)
from app.models.source import Source
from app.services.cases.matching import match_case
from app.services.candidates.service import persist_extraction
from app.services.documents.cleaning import build_clean_document
from app.services.documents.extractors import get_extractor
from app.services.documents.storage import save_extracted_text
from app.services.extraction.engine import run_extraction
from app.utils.errors import ExtractionError
from app.utils.logging import log_event
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


@dataclass
class ProcessingOutcome:
    status: str
    message: str
    candidates: int = 0
    evidence: int = 0
    claims: int = 0
    error: str | None = None


def process_document(db: Session, document: Document) -> ProcessingOutcome:
    """Run the full processing pipeline for one document."""
    log_event(logger, "processing_started", document_id=document.document_id)
    document.processing_status = STATUS_PROCESSING
    document.processing_started_at = utcnow()
    document.processing_error = None
    db.flush()

    storage_path = Path(document.storage_path)
    if not storage_path.exists():
        return _fail(db, document, ExtractionError(technical="stored file missing"))

    try:
        extractor = get_extractor(document.file_type)
        pages = extractor.extract(storage_path)
        full_text, segments = build_clean_document(pages)
        document.extracted_text = full_text
        save_extracted_text(document.document_id, full_text)

        def _case_matcher(number, name):
            existing_id, kind = match_case(db, case_number=number, case_name=name)
            return existing_id, kind

        result = run_extraction(full_text, case_matcher=_case_matcher)
        stats = persist_extraction(
            db, document=document, source=_source_of(db, document), result=result, segments=segments
        )

        document.processing_completed_at = utcnow()
        if result.total > 0:
            document.processing_status = STATUS_REVIEW_REQUIRED
        else:
            document.processing_status = STATUS_PROCESSED
        db.flush()

        log_event(
            logger, "processing_completed", document_id=document.document_id,
            status=document.processing_status, candidates=stats.candidates,
        )
        return ProcessingOutcome(
            status=document.processing_status,
            message=(
                "Extraction complete; candidates created for review."
                if result.total > 0
                else "No structured entities were confidently detected. Manual review is available."
            ),
            candidates=stats.candidates,
            evidence=stats.evidence,
            claims=stats.claims,
        )
    except ExtractionError as exc:
        return _fail(db, document, exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("processing failed document_id=%s", document.document_id)
        return _fail(db, document, ExtractionError(technical=f"unexpected error: {exc}"))


def _source_of(db: Session, document: Document) -> Source | None:
    if document.source_id:
        return db.get(Source, document.source_id)
    return None


def _fail(db: Session, document: Document, exc: Exception) -> ProcessingOutcome:
    document.processing_status = STATUS_FAILED
    document.processing_completed_at = utcnow()
    document.processing_error = str(exc)
    db.flush()
    logger.error("processing_failed document_id=%s error=%s", document.document_id, exc)
    return ProcessingOutcome(
        status=STATUS_FAILED,
        message="Text extraction failed. Please review the original document.",
        error=str(exc),
    )
