from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

FACT_STATUS_CANDIDATE = "CANDIDATE"
FACT_STATUS_CONFIRMED = "CONFIRMED"
FACT_STATUS_REJECTED = "REJECTED"


class Fact(Base):
    """Structured information supported by evidence.

    Example: "Person A was arrested during Operation X in Mumbai on 15
    June 2026" produces facts such as:

        Person A  ARRESTED_IN  Operation X
        Operation X OCCURRED_IN Mumbai
        Operation X OCCURRED_ON 15 June 2026

    Facts are only created when the source supports them.
    """

    __tablename__ = "facts"

    fact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.entity_id"), nullable=False)
    predicate: Mapped[str] = mapped_column(String(80), nullable=False)
    object_entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.entity_id"), nullable=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.event_id"), nullable=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.case_id"), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.evidence_id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=FACT_STATUS_CANDIDATE, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    subject_entity = relationship("Entity", foreign_keys=[subject_entity_id])
    object_entity = relationship("Entity", foreign_keys=[object_entity_id])
    event = relationship("Event")
    case = relationship("Case", back_populates="facts")
    evidence = relationship("Evidence", back_populates="facts")
