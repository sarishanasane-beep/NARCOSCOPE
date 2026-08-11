from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.case import Case
from app.schemas.cases import CaseCreate, CaseList, CaseOut, CaseUpdate
from app.services.audit.service import log_action
from app.utils.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=CaseList)
def list_cases(
    q: str | None = None, limit: int = 100, offset: int = 0, db: Session = Depends(get_db)
) -> CaseList:
    query = db.query(Case).order_by(Case.created_at.desc())
    if q:
        query = query.filter(
            Case.case_name.ilike(f"%{q}%") | Case.official_case_number.ilike(f"%{q}%")
        )
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return CaseList(items=[CaseOut.model_validate(c) for c in items], total=total)


@router.post("", response_model=CaseOut, status_code=201)
def create_case(payload: CaseCreate, db: Session = Depends(get_db)) -> CaseOut:
    import uuid

    from app.utils.text import normalize_case_number

    if payload.official_case_number:
        normalized = normalize_case_number(payload.official_case_number)
        existing = db.query(Case).all()
        for case in existing:
            if case.official_case_number and normalize_case_number(case.official_case_number) == normalized:
                raise ValidationError("A case with this official case number already exists.")
    case = Case(
        case_id=str(uuid.uuid4()),
        official_case_number=payload.official_case_number,
        case_name=payload.case_name,
        operation_name=payload.operation_name,
        category=payload.category,
        jurisdiction=payload.jurisdiction,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=payload.status,
        description=payload.description,
    )
    db.add(case)
    db.flush()
    log_action(
        db, action="CREATE", object_type="case", object_id=case.case_id,
        new_value={"official_case_number": case.official_case_number, "case_name": case.case_name},
        reason="case created via API",
    )
    db.commit()
    return CaseOut.model_validate(case)


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: str, db: Session = Depends(get_db)) -> CaseOut:
    case = db.get(Case, case_id)
    if case is None:
        raise NotFoundError("Case not found.")
    return CaseOut.model_validate(case)


@router.put("/{case_id}", response_model=CaseOut)
def update_case(case_id: str, payload: CaseUpdate, db: Session = Depends(get_db)) -> CaseOut:
    case = db.get(Case, case_id)
    if case is None:
        raise NotFoundError("Case not found.")
    previous = CaseOut.model_validate(case).model_dump()
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(case, field, value)
    db.flush()
    log_action(
        db, action="UPDATE", object_type="case", object_id=case.case_id,
        previous_value=previous, new_value=CaseOut.model_validate(case).model_dump(),
        reason="case updated via API",
    )
    db.commit()
    return CaseOut.model_validate(case)
