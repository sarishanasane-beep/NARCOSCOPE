from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.document import STATUS_FAILED, STATUS_PROCESSED, STATUS_REVIEW_REQUIRED
from app.schemas.documents import (
    DocumentList,
    DocumentMetadata,
    DocumentOut,
    DocumentProcessResponse,
    UploadResponse,
)
from app.services.documents.processing import process_document
from app.services.documents.similarity import text_similarity
from app.services.documents.upload import receive_upload
from app.utils.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse, status_code=201)
def upload_document(
    file: UploadFile = File(...),
    publisher: str | None = Form(default=None),
    agency: str | None = Form(default=None),
    source_type: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    publication_date: str | None = Form(default=None),
    case_number: str | None = Form(default=None),
    case_name: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> UploadResponse:
    metadata = DocumentMetadata(
        publisher=publisher,
        agency=agency,
        source_type=source_type,
        source_url=source_url,
        publication_date=publication_date,
        case_number=case_number,
        case_name=case_name,
    )
    result = receive_upload(db, file, metadata=metadata.model_dump(exclude_none=True))
    db.commit()
    return UploadResponse(
        document=DocumentOut.model_validate(result.document),
        message=result.message,
        duplicate_of=result.duplicate_of,
    )


@router.get("", response_model=DocumentList)
def list_documents(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> DocumentList:
    from app.models.document import Document

    query = db.query(Document).order_by(Document.upload_timestamp.desc())
    if status:
        query = query.filter(Document.processing_status == status)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return DocumentList(items=[DocumentOut.model_validate(d) for d in items], total=total)


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentOut:
    from app.models.document import Document

    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    return DocumentOut.model_validate(document)


@router.post("/{document_id}/process", response_model=DocumentProcessResponse)
def reprocess_document(document_id: str, db: Session = Depends(get_db)) -> DocumentProcessResponse:
    from app.models.document import Document

    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    if document.processing_status in (STATUS_PROCESSED, STATUS_REVIEW_REQUIRED):
        raise ValidationError(
            "Document is already processed. Only failed or uploaded documents can be reprocessed."
        )
    outcome = process_document(db, document)
    db.commit()
    return DocumentProcessResponse(
        document=DocumentOut.model_validate(document),
        message=outcome.message,
    )


@router.get("/{document_id}/similar")
def similar_documents(document_id: str, threshold: float = 0.9, db: Session = Depends(get_db)) -> dict:
    """Near-duplicate foundation: similarity of extracted text vs other docs."""
    from app.models.document import Document

    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    results = []
    if document.extracted_text:
        others = (
            db.query(Document)
            .filter(
                Document.document_id != document_id,
                Document.extracted_text.isnot(None),
                Document.processing_status.in_([STATUS_PROCESSED, STATUS_REVIEW_REQUIRED]),
            )
            .all()
        )
        for other in others:
            score = text_similarity(document.extracted_text, other.extracted_text or "")
            if score >= threshold:
                results.append({"document_id": other.document_id, "similarity": round(score, 4)})
    return {"document_id": document_id, "near_duplicates": results}
