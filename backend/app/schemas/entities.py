from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class EntityOut(ORMModel):
    entity_id: str
    entity_type: str
    canonical_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    # Structured-source semantics preserved at confirmation (role, status,
    # mention_context, investigative_status, evidence_snippet).
    structured_metadata: dict | None = None
    document_id: str | None = None
    # Deduplication state (canonical / merged / superseded): set only by
    # an explicit human-approved merge or case reconciliation.
    merged_into_id: str | None = None
    merged_into_case_id: str | None = None


class PersonCreate(BaseModel):
    canonical_name: str
    aliases: list[str] = []
    public_identifiers: list[str] = []
    notes: str | None = None


class PersonOut(ORMModel):
    person_id: str
    entity_id: str
    canonical_name: str
    aliases: list = []
    public_identifiers: list = []
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class OrganizationCreate(BaseModel):
    canonical_name: str
    aliases: list[str] = []
    organization_type: str = "ORGANIZATION"
    notes: str | None = None


class OrganizationOut(ORMModel):
    organization_id: str
    entity_id: str
    canonical_name: str
    aliases: list = []
    organization_type: str
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class LocationCreate(BaseModel):
    canonical_name: str
    location_type: str = "OTHER"
    parent_location_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class LocationOut(ORMModel):
    location_id: str
    entity_id: str
    canonical_name: str
    location_type: str
    parent_location_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    created_at: datetime
    updated_at: datetime


class EntityDetail(ORMModel):
    """Entity plus its specialized record, when present."""

    entity_id: str
    entity_type: str
    canonical_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    structured_metadata: dict | None = None
    document_id: str | None = None
    merged_into_id: str | None = None
    merged_into_case_id: str | None = None
    person: PersonOut | None = None
    organization: OrganizationOut | None = None
    location: LocationOut | None = None


class EntityList(BaseModel):
    items: list[EntityOut]
    total: int = 0


class PersonList(BaseModel):
    items: list[PersonOut]
    total: int = 0


class OrganizationList(BaseModel):
    items: list[OrganizationOut]
    total: int = 0


class LocationList(BaseModel):
    items: list[LocationOut]
    total: int = 0
