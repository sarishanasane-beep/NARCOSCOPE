from typing import Any

from pydantic import BaseModel


class PriorityOut(BaseModel):
    entity_id: str
    total: float
    breakdown: dict[str, dict[str, Any]]
    disclaimer: str
