"""Saved investigation search.

Stores the structured filter set of an investigation query so it can be
re-run later (see app/services/search/query.py for the filter contract).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.utils.time import utcnow


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    saved_search_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The InvestigationQuery fields as a dict (dates as ISO strings).
    filters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
