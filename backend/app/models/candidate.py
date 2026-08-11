from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

CANDIDATE_TYPE_ENTITY = "ENTITY"
CANDIDATE_TYPE_RELATIONSHIP = "RELATIONSHIP"
CANDIDATE_TYPE_CASE_MATCH = "CASE_MATCH"
CANDIDATE_TYPE_EVENT = "EVENT"
CANDIDATE_TYPE_LOCATION = "LOCATION"
CANDIDATE_TYPE_FACT = "FACT"

CANDIDATE_STATUS_PENDING = "PENDING"
CANDIDATE_STATUS_CONFIRMED = "CONFIRMED"
CANDIDATE_STATUS_REJECTED = "REJECTED"
CANDIDATE_STATUS_EDITED = "EDITED"

WORKFLOW = "EXTRACT -> CANDIDATE -> REVIEW (CONFIRM / EDIT / REJECT) -> TRUSTED DATA"


class Candidate(Base):
    """A proposed piece of information awaiting human review.

    Nothing uncertain enters trusted data directly. Candidates carry
    proposed data, supporting evidence and a confidence score. A human
    reviewer confirms, edits or rejects each candidate.
    """

    __tablename__ = "candidates"

    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_type: Mapped[str] = mapped_column(String(30), nullable=False)
    proposed_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.document_id"), nullable=True
    )
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.evidence_id"), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=CANDIDATE_STATUS_PENDING, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    source_document = relationship("Document", back_populates="candidates")
    evidence = relationship("Evidence", back_populates="candidates")

    __table_args__ = (Index("ix_candidates_status", "status"),)
