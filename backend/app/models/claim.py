from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

CLAIM_STATUS_REPORTED = "REPORTED"
CLAIM_STATUS_ALLEGED = "ALLEGED"
CLAIM_STATUS_OFFICIALLY_STATED = "OFFICIALLY_STATED"
CLAIM_STATUS_COURT_RECORDED = "COURT_RECORDED"
CLAIM_STATUS_UNKNOWN = "UNKNOWN"


class Claim(Base):
    """A statement as reported by a source, preserving its status.

    If the source says "Authorities alleged that Person A...", the claim
    is stored with claim_status = ALLEGED — it is never silently converted
    into a confirmed fact.
    """

    __tablename__ = "claims"

    claim_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_status: Mapped[str] = mapped_column(String(30), default=CLAIM_STATUS_UNKNOWN, nullable=False)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.evidence_id"), nullable=True)
    subject_entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.entity_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    evidence = relationship("Evidence", back_populates="claims")
    subject_entity = relationship("Entity")
