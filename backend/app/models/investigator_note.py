"""Investigator note — a human annotation.

Notes are investigator-created annotations ONLY. They never become
evidence, facts, relationships, claims, or graph edges automatically.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.utils.time import utcnow


class InvestigatorNote(Base):
    __tablename__ = "investigator_notes"

    note_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Optional subject the note is attached to
    # (entity | case | event | location | workspace | change | null).
    subject_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
