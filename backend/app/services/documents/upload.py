"""Document upload pipeline.

1. Check extension         5. Generate unique storage filename
2. Check MIME type          6. Calculate SHA-256 hash
3. Check file size          7. Store original file
4. Sanitize filename        8. Create database record
                             9. Begin processing

Original uploaded files are never modified. Exact duplicates (same
SHA-256) are detected and referenced rather than processed again.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.document import STATUS_DUPLICATE, STATUS_UPLOADED, Document
from app.models.source import Source
from app.services.audit.service import log_action
from app.services.documents.processing import process_document
from app.services.documents.storage import sanitize_filename, save_original_file
from app.services.documents.validation import validate_upload
from app.services.sources.service import create_source
from app.utils.logging import log_event

logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    document: Document
    message: str
    duplicate_of: str | None = None


def receive_upload(
    db: Session,
    file: UploadFile,
    *,
    metadata: dict | None = None,
    process: bool | None = None,
) -> UploadResult:
    """Upload from a FastAPI UploadFile."""
    data = file.file.read()
    return receive_upload_bytes(
        db, filename=file.filename or "document", data=data, metadata=metadata, process=process
    )


def receive_upload_bytes(
    db: Session,
    *,
    filename: str,
    data: bytes,
    metadata: dict | None = None,
    process: bool | None = None,
) -> UploadResult:
    """Upload from raw bytes (used by tests and the demo seed)."""
    metadata = metadata or {}
    file_type, mime_type = validate_upload(filename, data)
    sha256 = hashlib.sha256(data).hexdigest()
    safe_name = sanitize_filename(filename)

    # --- Duplicate detection (SHA-256) ---
    existing = (
        db.query(Document)
        .filter(Document.sha256_hash == sha256, Document.processing_status != "FAILED")
        .order_by(Document.upload_timestamp.asc())
        .first()
    )
    if existing is not None:
        document_id = str(uuid.uuid4())
        stored_path = save_original_file(data, document_id, file_type)
        duplicate = Document(
            document_id=document_id,
            filename=safe_name,
            stored_filename=f"{document_id}.{file_type}",
            file_type=file_type,
            mime_type=mime_type,
            file_size=len(data),
            sha256_hash=sha256,
            storage_path=str(stored_path),
            processing_status=STATUS_DUPLICATE,
            duplicate_of_document_id=existing.document_id,
        )
        db.add(duplicate)
        db.flush()
        log_action(
            db,
            action="CREATE",
            object_type="document",
            object_id=duplicate.document_id,
            new_value={"duplicate_of": existing.document_id, "sha256_hash": sha256},
            reason="Duplicate document detected.",
        )
        log_event(
            logger, "duplicate_document_detected",
            document_id=duplicate.document_id, original_id=existing.document_id,
        )
        return UploadResult(
            document=duplicate,
            message="Duplicate document detected. This document already exists.",
            duplicate_of=existing.document_id,
        )

    # --- New document ---
    document_id = str(uuid.uuid4())
    stored_path = save_original_file(data, document_id, file_type)

    source: Source | None = None
    if any(metadata.get(k) for k in ("publisher", "agency", "source_type", "source_url", "publication_date")):
        source = create_source(
            db,
            publisher=metadata.get("publisher"),
            agency=metadata.get("agency"),
            source_type=metadata.get("source_type") or "UNKNOWN",
            source_url=metadata.get("source_url"),
            publication_date=_parse_date(metadata.get("publication_date")),
        )

    document = Document(
        document_id=document_id,
        filename=safe_name,
        stored_filename=f"{document_id}.{file_type}",
        file_type=file_type,
        mime_type=mime_type,
        file_size=len(data),
        sha256_hash=sha256,
        storage_path=str(stored_path),
        processing_status=STATUS_UPLOADED,
        source_id=source.source_id if source else None,
        publication_date=_parse_date(metadata.get("publication_date")),
    )
    db.add(document)
    db.flush()

    if source:
        source.document_id = document.document_id
        db.flush()

    log_action(
        db,
        action="CREATE",
        object_type="document",
        object_id=document.document_id,
        new_value={"filename": safe_name, "file_type": file_type, "sha256_hash": sha256},
        reason="document uploaded",
    )
    log_event(
        logger, "document_uploaded",
        document_id=document.document_id, filename=safe_name, file_type=file_type, size=len(data),
    )

    # --- Processing ---
    if process if process is not None else settings.process_on_upload:
        outcome = process_document(db, document)
        return UploadResult(
            document=document,
            message=outcome.message,
        )

    return UploadResult(document=document, message="Document uploaded.")


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None
