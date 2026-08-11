from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.evidence import EvidenceOut
from app.services.evidence.service import get_evidence

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/{evidence_id}", response_model=EvidenceOut)
def get_one_evidence(evidence_id: str, db: Session = Depends(get_db)) -> EvidenceOut:
    return EvidenceOut.model_validate(get_evidence(db, evidence_id))
