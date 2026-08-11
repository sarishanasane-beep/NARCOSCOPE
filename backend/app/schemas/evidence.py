from datetime import datetime

from app.schemas.common import ORMModel


class EvidenceOut(ORMModel):
    evidence_id: str
    document_id: str
    source_id: str | None = None
    exact_text: str
    page_number: int | None = None
    text_start: int | None = None
    text_end: int | None = None
    extraction_method: str
    extraction_confidence: float | None = None
    created_at: datetime
