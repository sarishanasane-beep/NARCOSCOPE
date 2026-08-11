from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

# Processing statuses
STATUS_UPLOADED = "UPLOADED"
STATUS_PROCESSING = "PROCESSING"
STATUS_PROCESSED = "PROCESSED"
STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"
STATUS_FAILED = "FAILED"
STATUS_DUPLICATE = "DUPLICATE"


class Document(Base):
    """An uploaded source document (PDF / DOCX / TXT).

    The original file is never modified; it is preserved on disk for
    evidence verification.
    """

    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    upload_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    processing_status: Mapped[str] = mapped_column(String(30), default=STATUS_UPLOADED, nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.source_id"), nullable=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    duplicate_of_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.document_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    # Many-to-one: many Documents belong to one Source (FK: source_id).
    source = relationship("Source", foreign_keys=[source_id], back_populates="documents")
    duplicate_of = relationship(
        "Document", remote_side=[document_id], foreign_keys=[duplicate_of_document_id]
    )
    evidence = relationship("Evidence", back_populates="document", cascade="all, delete-orphan")
    candidates = relationship("Candidate", back_populates="source_document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_documents_sha256_hash", "sha256_hash"),
        Index("ix_documents_filename", "filename"),
        Index("ix_documents_status", "processing_status"),
    )
