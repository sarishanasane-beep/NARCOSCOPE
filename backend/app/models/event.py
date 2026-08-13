from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

EVENT_TYPES = [
    "OPERATION",
    "ARREST",
    "SEIZURE",
    "RAID",
    "INVESTIGATION",
    "SEARCH",
    "COURT_PROCEEDING",
    "INTERCEPTION",
    "OTHER",
]

DATE_PRECISION_DAY = "DAY"
DATE_PRECISION_MONTH = "MONTH"
DATE_PRECISION_YEAR = "YEAR"
DATE_PRECISION_RANGE = "RANGE"
DATE_PRECISION_UNKNOWN = "UNKNOWN"
DATE_PRECISIONS = [
    DATE_PRECISION_DAY,
    DATE_PRECISION_MONTH,
    DATE_PRECISION_YEAR,
    DATE_PRECISION_RANGE,
    DATE_PRECISION_UNKNOWN,
]


class Event(Base):
    """A first-class event (operation, arrest, seizure, raid, ...).

    NARCOSCOPE does not build only a person-to-person graph — events are
    first-class objects. Date precision is always recorded; exact dates are
    never invented.
    """

    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_precision: Mapped[str] = mapped_column(
        String(20), default=DATE_PRECISION_UNKNOWN, nullable=False
    )
    # Exact TIME value from the structured source (e.g. "14:30") — kept as
    # the source wrote it; "Not provided" when absent. Never derived from
    # the document publication date or upload timestamp.
    event_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.location_id"), nullable=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.case_id"), nullable=True)
    # Direct traceability: the source document + exact evidence block that
    # materialized this event (set at confirmation from the candidate).
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.document_id"), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.evidence_id"), nullable=True)
    # Structured-source semantics preserved at confirmation (status,
    # duration, organization, drug, vehicle, person, evidence_snippet...).
    structured_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    location = relationship("Location")
    case = relationship("Case", back_populates="events")
    document = relationship("Document")
    evidence = relationship("Evidence")

    __table_args__ = (
        Index("ix_events_start_date", "start_date"),
        Index("ix_events_event_type", "event_type"),
        Index("ix_events_case_id", "case_id"),
        Index("ix_events_document_id", "document_id"),
    )
