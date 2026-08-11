from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow


class Organization(Base):
    """An organization entity (agency, company, institution, group...).

    Supports agencies, companies, organizations, institutions and other
    documented groups. Being mentioned in a document does not imply
    involvement.
    """

    __tablename__ = "organizations"

    organization_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.entity_id"), nullable=False, unique=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    organization_type: Mapped[str] = mapped_column(String(40), default="ORGANIZATION", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    entity = relationship("Entity", back_populates="organization")

    __table_args__ = (Index("ix_organizations_canonical_name", "canonical_name"),)
