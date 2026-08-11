from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow


class Evidence(Base):
    """Exact supporting text extracted from a source document.

    Every important candidate fact or relationship must be traceable to
    evidence:

        ENTITY -> RELATIONSHIP -> EVIDENCE -> SOURCE -> ORIGINAL DOCUMENT

    ``exact_text`` preserves the exact supporting text.
    """

    __tablename__ = "evidence"

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.document_id"), nullable=False)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.source_id"), nullable=True)
    exact_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(100), nullable=False)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    document = relationship("Document", back_populates="evidence")
    source = relationship("Source", back_populates="evidence")
    facts = relationship("Fact", back_populates="evidence")
    claims = relationship("Claim", back_populates="evidence")
    candidates = relationship("Candidate", back_populates="evidence")
