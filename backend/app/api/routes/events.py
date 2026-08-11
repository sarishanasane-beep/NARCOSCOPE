import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.event import Event
from app.schemas.cases import EventCreate, EventList, EventOut
from app.services.audit.service import log_action
from app.utils.errors import NotFoundError

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=EventList)
def list_events(
    event_type: str | None = None, limit: int = 200, offset: int = 0, db: Session = Depends(get_db)
) -> EventList:
    query = db.query(Event).order_by(Event.start_date.desc().nullslast())
    if event_type:
        query = query.filter(Event.event_type == event_type)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return EventList(items=[EventOut.model_validate(e) for e in items], total=total)


@router.post("", response_model=EventOut, status_code=201)
def create_event(payload: EventCreate, db: Session = Depends(get_db)) -> EventOut:
    event = Event(
        event_id=str(uuid.uuid4()),
        event_type=payload.event_type,
        title=payload.title,
        description=payload.description,
        start_date=payload.start_date,
        end_date=payload.end_date,
        date_precision=payload.date_precision,
        location_id=payload.location_id,
        case_id=payload.case_id,
    )
    db.add(event)
    db.flush()
    log_action(
        db, action="CREATE", object_type="event", object_id=event.event_id,
        new_value={"event_type": event.event_type, "title": event.title},
        reason="event created via API",
    )
    db.commit()
    return EventOut.model_validate(event)


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: str, db: Session = Depends(get_db)) -> EventOut:
    event = db.get(Event, event_id)
    if event is None:
        raise NotFoundError("Event not found.")
    return EventOut.model_validate(event)
