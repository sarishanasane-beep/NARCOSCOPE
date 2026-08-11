from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

SOURCE_TYPE_UNKNOWN = "UNKNOWN"
SOURCE_TYPES = [
    "OFFICIAL_GOVERNMENT",
    "OFFICIAL_POLICE",
    "OFFICIAL_AGENCY",
    "COURT_PUBLIC_RECORD",
    "SECONDARY_SOURCE",
    "UNKNOWN",
]


class Source(Base):
    """The publisher/origin of a document.

    The source type describes the origin only. It does NOT automatically
    prove that every statement inside the document is true.
    """

    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agency: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), default=SOURCE_TYPE_UNKNOWN, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Stored reference to the document this source was created from (spec §12
    # lists document_id on sources). The relationship itself is modeled the
    # other way around: documents.source_id -> sources.source_id, so this
    # column deliberately has NO ForeignKey (a second FK would create a
    # circular dependency between documents and sources).
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    # One Source has many Documents; the FK lives on documents.source_id.
    documents = relationship("Document", back_populates="source")
    evidence = relationship("Evidence", back_populates="source")

    __table_args__ = (Index("ix_sources_publisher", "publisher"),)
