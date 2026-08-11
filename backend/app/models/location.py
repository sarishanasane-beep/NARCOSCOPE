from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow


class Location(Base):
    """A location entity.

    Locations can form a hierarchy (Pune -> Maharashtra -> India) through
    ``parent_location_id``. Latitude/longitude are optional — NARCOSCOPE
    never attempts automatic precise geolocation from vague text.
    """

    __tablename__ = "locations"

    location_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.entity_id"), nullable=False, unique=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_type: Mapped[str] = mapped_column(String(30), default="OTHER", nullable=False)
    parent_location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.location_id"), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    entity = relationship("Entity", back_populates="location")
    parent = relationship("Location", remote_side=[location_id], foreign_keys=[parent_location_id])

    __table_args__ = (Index("ix_locations_canonical_name", "canonical_name"),)
