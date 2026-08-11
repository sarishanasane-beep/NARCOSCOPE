from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

RELATIONSHIP_TYPES = [
    "MENTIONED_IN",
    "INVOLVED_IN",
    "ROLE_IN",
    "QUESTIONED_IN",
    "ARRESTED_IN",
    "PARTICIPATED_IN",
    "ASSOCIATED_WITH",
    "OPERATES",
    "OWNS",
    "LOCATED_IN",
    "RESIDES_IN",
    "OCCURRED_IN",
    "PART_OF",
    "JURISDICTION",
    "POSSIBLE_MATCH",
]

CLASSIFICATION_DIRECT = "DIRECT"
CLASSIFICATION_DERIVED = "DERIVED"
CLASSIFICATION_CANDIDATE = "CANDIDATE"

REL_STATUS_CANDIDATE = "CANDIDATE"
REL_STATUS_CONFIRMED = "CONFIRMED"
REL_STATUS_REJECTED = "REJECTED"


class Relationship(Base):
    """A relationship between two entities.

    A relationship is NEVER created merely because two entities occur in
    the same document — only when a meaningful pattern exists. Location
    relationships carry specific meanings (RESIDES_IN, LOCATED_IN,
    OCCURRED_IN, JURISDICTION), never a generic "CONNECTED_TO".
    """

    __tablename__ = "relationships"

    relationship_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.entity_id"), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.entity_id"), nullable=False)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.case_id"), nullable=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.event_id"), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.evidence_id"), nullable=True)
    claim_id: Mapped[str | None] = mapped_column(ForeignKey("claims.claim_id"), nullable=True)
    classification: Mapped[str] = mapped_column(String(20), default=CLASSIFICATION_DIRECT, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=REL_STATUS_CANDIDATE, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_observed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_observed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    source_entity = relationship("Entity", foreign_keys=[source_entity_id])
    target_entity = relationship("Entity", foreign_keys=[target_entity_id])
    case = relationship("Case", back_populates="relationships")
    event = relationship("Event")
    evidence = relationship("Evidence")
    claim = relationship("Claim")

    __table_args__ = (Index("ix_relationships_relationship_type", "relationship_type"),)
