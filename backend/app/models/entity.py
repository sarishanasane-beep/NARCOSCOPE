from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

ENTITY_TYPE_PERSON = "PERSON"
ENTITY_TYPE_ORGANIZATION = "ORGANIZATION"
ENTITY_TYPE_AGENCY = "AGENCY"
ENTITY_TYPE_LOCATION = "LOCATION"
ENTITY_TYPE_PROPERTY = "PROPERTY"
ENTITY_TYPE_OTHER = "OTHER"
ENTITY_TYPE_DRUG = "DRUG"
ENTITY_TYPE_VEHICLE = "VEHICLE"
ENTITY_TYPE_CASE = "CASE"

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
    # Structured-source metadata preserved at confirmation (role, status,
    # mention_context, investigative_status, evidence_snippet). Nullable so
    # entities created outside the structured pipeline stay unchanged.
    structured_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Source document that materialized this entity (set at confirmation).
    # Enables case scoping of isolated/mentioned-only entities without
    # fabricating membership edges.
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.document_id"), nullable=True)
    # When this record was merged into another (deduplication), the
    # canonical entity's id. Set only by an explicit human-approved merge;
    # merged records are excluded from active graphs/stats/duplicate scans.
    merged_into_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.entity_id"), nullable=True
    )
    # CASE-typed entities reconciled into a canonical Case record (the
    # legacy CASE-entity / Case duplicate). The entity row remains as the
    # relationship-endpoint FK target but is marked MERGED and points at
    # the canonical Case — it never appears as an independent record.
    merged_into_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("cases.case_id"), nullable=True
    )
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
