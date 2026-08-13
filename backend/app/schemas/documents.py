from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class DocumentMetadata(BaseModel):
    """Optional metadata provided by the user at upload time.

    Everything is optional except what is required for processing (the
    file itself). Information that can be extracted from the document is
    not forced on the user.
    """

    publisher: str | None = None
    agency: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    publication_date: date | None = None
    case_number: str | None = None
    case_name: str | None = None


class DocumentOut(ORMModel):
    document_id: str
    filename: str
    stored_filename: str
    file_type: str
    mime_type: str
    file_size: int
    sha256_hash: str
    storage_path: str
    upload_timestamp: datetime
    processing_status: str
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    processing_error: str | None = None
    extracted_text: str | None = None
    source_id: str | None = None
    publication_date: date | None = None
    duplicate_of_document_id: str | None = None
    # Structured-validation issues found while parsing a v2 document
    # (unknown IDs, invalid types, conflicting duplicate declarations).
    structured_validation: list | None = None
    created_at: datetime
    updated_at: datetime


class UploadResponse(BaseModel):
    document: DocumentOut
    message: str
    duplicate_of: str | None = None


class DocumentProcessResponse(BaseModel):
    document: DocumentOut
    message: str


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int = Field(default=0)
