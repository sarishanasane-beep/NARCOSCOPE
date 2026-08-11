from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow


class Case(Base):
    """A case record.

    Case identification hierarchy:
      1. Official case number
      2. Official operation/reference number
      3. Official operation name
      4. Strong case reference
      5. NARCOSCOPE internal ID
      6. Unclassified

    The official case number is unique when present. A similar case name
    alone does NOT automatically prove two cases are the same.
    """

    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    official_case_number: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    case_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="UNKNOWN", nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    events = relationship("Event", back_populates="case")
    relationships = relationship("Relationship", back_populates="case")
    facts = relationship("Fact", back_populates="case")

    __table_args__ = (
        Index("ix_cases_official_case_number", "official_case_number"),
        Index("ix_cases_case_name", "case_name"),
    )
