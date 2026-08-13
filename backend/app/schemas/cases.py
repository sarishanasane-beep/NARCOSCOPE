from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class CaseCreate(BaseModel):
    official_case_number: str | None = None
    case_name: str | None = None
    operation_name: str | None = None
    category: str | None = None
    jurisdiction: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str = "UNKNOWN"
    description: str | None = None


class CaseUpdate(BaseModel):
    official_case_number: str | None = None
    case_name: str | None = None
    operation_name: str | None = None
    category: str | None = None
    jurisdiction: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    description: str | None = None


class CaseOut(ORMModel):
    case_id: str
    official_case_number: str | None = None
    case_name: str | None = None
    operation_name: str | None = None
    category: str | None = None
    jurisdiction: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class CaseList(BaseModel):
    items: list[CaseOut]
    total: int = 0


class EventCreate(BaseModel):
    event_type: str = "OTHER"
    title: str
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    date_precision: str = "UNKNOWN"
    location_id: str | None = None
    case_id: str | None = None


class EventOut(ORMModel):
    event_id: str
    event_type: str
    title: str
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    date_precision: str
    event_time: str | None = None
    location_id: str | None = None
    case_id: str | None = None
    document_id: str | None = None
    evidence_id: str | None = None
    structured_metadata: dict | None = None
    created_at: datetime
    updated_at: datetime


class EventList(BaseModel):
    items: list[EventOut]
    total: int = 0
