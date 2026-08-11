from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class SourceCreate(BaseModel):
    publisher: str | None = None
    agency: str | None = None
    source_type: str = "UNKNOWN"
    source_url: str | None = None
    publication_date: date | None = None


class SourceOut(ORMModel):
    source_id: str
    publisher: str | None = None
    agency: str | None = None
    source_type: str
    source_url: str | None = None
    publication_date: date | None = None
    document_id: str | None = None
    source_status: str
    created_at: datetime
    updated_at: datetime


class SourceList(BaseModel):
    items: list[SourceOut]
    total: int = 0
