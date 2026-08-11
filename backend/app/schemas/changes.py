from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    change_id: str
    snapshot_id: str
    category: str
    significance: str
    kind: str
    reference_id: str | None = None
    details: dict[str, Any] = {}
    created_at: datetime


class ChangeList(BaseModel):
    items: list[ChangeOut]
    total: int


class CompareRequest(BaseModel):
    previous_snapshot_id: str
    current_snapshot_id: str
