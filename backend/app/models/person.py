from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow


class Person(Base):
    """A person entity.

    Neutral terminology is used throughout. A person is simply a PERSON
    entity — never automatically labeled criminal/guilty/trafficker unless
    an explicitly sourced legal/document status is being preserved as a
    claim.
    """

    __tablename__ = "people"

    person_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.entity_id"), nullable=False, unique=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    public_identifiers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    entity = relationship("Entity", back_populates="person")

    __table_args__ = (Index("ix_people_canonical_name", "canonical_name"),)
