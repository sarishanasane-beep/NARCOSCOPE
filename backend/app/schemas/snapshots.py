from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SnapshotCreate(BaseModel):
    label: str | None = None
    created_by: str | None = None


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot_id: str
    version: int
    label: str | None = None
    graph_hash: str
    node_count: int
    edge_count: int
    created_at: datetime


class SnapshotList(BaseModel):
    items: list[SnapshotOut]
    total: int
