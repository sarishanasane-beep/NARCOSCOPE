from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

ENTITY_TYPE_PERSON = "PERSON"
ENTITY_TYPE_ORGANIZATION = "ORGANIZATION"
ENTITY_TYPE_AGENCY = "AGENCY"
ENTITY_TYPE_LOCATION = "LOCATION"
ENTITY_TYPE_PROPERTY = "PROPERTY"
ENTITY_TYPE_OTHER = "OTHER"

ENTITY_STATUS_ACTIVE = "ACTIVE"
ENTITY_STATUS_MERGED = "MERGED"
ENTITY_STATUS_ARCHIVED = "ARCHIVED"


class Entity(Base):
    """A generic entity.

    Specialized tables (people, organizations, locations) extend this base
    record. Entities can be PERSON, ORGANIZATION, AGENCY, LOCATION,
    PROPERTY or OTHER.
    """

    __tablename__ = "entities"

    entity_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=ENTITY_STATUS_ACTIVE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    person = relationship("Person", back_populates="entity", uselist=False, cascade="all, delete-orphan")
    organization = relationship(
        "Organization", back_populates="entity", uselist=False, cascade="all, delete-orphan"
    )
    location = relationship("Location", back_populates="entity", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (Index("ix_entities_canonical_name", "canonical_name"),)
