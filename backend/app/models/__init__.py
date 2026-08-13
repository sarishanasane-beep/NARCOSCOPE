"""All ORM models.

Importing this package registers every table on ``Base.metadata`` so
``Base.metadata.create_all`` works.
"""

from app.models.audit import ACTION_CONFIRM, ACTION_CREATE, ACTION_DELETE, ACTION_MERGE, ACTION_REJECT, ACTION_UNMERGE, ACTION_UPDATE, AuditLog
from app.models.candidate import (
    CANDIDATE_STATUS_CONFIRMED,
    CANDIDATE_STATUS_EDITED,
    CANDIDATE_STATUS_PENDING,
    CANDIDATE_STATUS_REJECTED,
    CANDIDATE_TYPE_CASE_MATCH,
    CANDIDATE_TYPE_ENTITY,
    CANDIDATE_TYPE_EVENT,
    CANDIDATE_TYPE_FACT,
    CANDIDATE_TYPE_LOCATION,
    CANDIDATE_TYPE_RELATIONSHIP,
    Candidate,
)
from app.models.case import Case
from app.models.claim import (
    CLAIM_STATUS_ALLEGED,
    CLAIM_STATUS_COURT_RECORDED,
    CLAIM_STATUS_OFFICIALLY_STATED,
    CLAIM_STATUS_REPORTED,
    CLAIM_STATUS_UNKNOWN,
    Claim,
)
from app.models.document import (
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_PROCESSED,
    STATUS_PROCESSING,
    STATUS_REVIEW_REQUIRED,
    STATUS_UPLOADED,
    Document,
)
from app.models.duplicate_decision import DECISION_KEEP_SEPARATE, DuplicateDecision
from app.models.entity import (
    ENTITY_STATUS_ACTIVE,
    ENTITY_STATUS_ARCHIVED,
    ENTITY_STATUS_MERGED,
    ENTITY_TYPE_AGENCY,
    ENTITY_TYPE_LOCATION,
    ENTITY_TYPE_ORGANIZATION,
    ENTITY_TYPE_OTHER,
    ENTITY_TYPE_PERSON,
    ENTITY_TYPE_PROPERTY,
    Entity,
)
from app.models.event import (
    DATE_PRECISION_DAY,
    DATE_PRECISION_MONTH,
    DATE_PRECISION_RANGE,
    DATE_PRECISION_UNKNOWN,
    DATE_PRECISION_YEAR,
    EVENT_TYPES,
    Event,
)
from app.models.evidence import Evidence
from app.models.bookmark import Bookmark
from app.models.fact import FACT_STATUS_CANDIDATE, FACT_STATUS_CONFIRMED, FACT_STATUS_REJECTED, Fact
from app.models.graph_change import GraphChange
from app.models.graph_snapshot import GraphSnapshot
from app.models.investigator_note import InvestigatorNote
from app.models.location import Location
from app.models.organization import Organization
from app.models.person import Person
from app.models.relationship import (
    CLASSIFICATION_CANDIDATE,
    CLASSIFICATION_DERIVED,
    CLASSIFICATION_DIRECT,
    RELATIONSHIP_TYPES,
    REL_STATUS_CANDIDATE,
    REL_STATUS_CONFIRMED,
    REL_STATUS_REJECTED,
    Relationship,
)
from app.models.saved_search import SavedSearch
from app.models.source import SOURCE_TYPES, SOURCE_TYPE_UNKNOWN, Source
from app.models.workspace import Workspace

__all__ = [
    "AuditLog",
    "Bookmark",
    "Candidate",
    "GraphChange",
    "GraphSnapshot",
    "InvestigatorNote",
    "Case",
    "Claim",
    "Document",
    "DuplicateDecision",
    "Entity",
    "Event",
    "Evidence",
    "Fact",
    "Location",
    "Organization",
    "Person",
    "Relationship",
    "SavedSearch",
    "Source",
    "Workspace",
    "STATUS_UPLOADED",
    "STATUS_PROCESSING",
    "STATUS_PROCESSED",
    "STATUS_REVIEW_REQUIRED",
    "STATUS_FAILED",
    "STATUS_DUPLICATE",
    "ENTITY_TYPE_PERSON",
    "ENTITY_TYPE_ORGANIZATION",
    "ENTITY_TYPE_AGENCY",
    "ENTITY_TYPE_LOCATION",
    "ENTITY_TYPE_PROPERTY",
    "ENTITY_TYPE_OTHER",
    "ENTITY_STATUS_ACTIVE",
    "ENTITY_STATUS_MERGED",
    "ENTITY_STATUS_ARCHIVED",
    "SOURCE_TYPES",
    "SOURCE_TYPE_UNKNOWN",
    "DATE_PRECISION_DAY",
    "DATE_PRECISION_MONTH",
    "DATE_PRECISION_YEAR",
    "DATE_PRECISION_RANGE",
    "DATE_PRECISION_UNKNOWN",
    "EVENT_TYPES",
    "RELATIONSHIP_TYPES",
    "CLASSIFICATION_DIRECT",
    "CLASSIFICATION_DERIVED",
    "CLASSIFICATION_CANDIDATE",
    "REL_STATUS_CANDIDATE",
    "REL_STATUS_CONFIRMED",
    "REL_STATUS_REJECTED",
    "FACT_STATUS_CANDIDATE",
    "FACT_STATUS_CONFIRMED",
    "FACT_STATUS_REJECTED",
    "CLAIM_STATUS_REPORTED",
    "CLAIM_STATUS_ALLEGED",
    "CLAIM_STATUS_OFFICIALLY_STATED",
    "CLAIM_STATUS_COURT_RECORDED",
    "CLAIM_STATUS_UNKNOWN",
    "CANDIDATE_TYPE_ENTITY",
    "CANDIDATE_TYPE_RELATIONSHIP",
    "CANDIDATE_TYPE_CASE_MATCH",
    "CANDIDATE_TYPE_EVENT",
    "CANDIDATE_TYPE_LOCATION",
    "CANDIDATE_TYPE_FACT",
    "CANDIDATE_STATUS_PENDING",
    "CANDIDATE_STATUS_CONFIRMED",
    "CANDIDATE_STATUS_REJECTED",
    "CANDIDATE_STATUS_EDITED",
    "DECISION_KEEP_SEPARATE",
    "ACTION_CREATE",
    "ACTION_UPDATE",
    "ACTION_CONFIRM",
    "ACTION_REJECT",
    "ACTION_MERGE",
    "ACTION_UNMERGE",
    "ACTION_DELETE",
]
