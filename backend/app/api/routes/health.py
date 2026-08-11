from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.session import get_db
from app.services.ai.service import get_ai_service

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    database = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        database = "disconnected"
    ai = get_ai_service()
    return {
        "status": "ok",
        "database": database,
        "ai_enabled": ai.ai_enabled,
        "ai_provider": ai.provider.name,
        "version": settings.version,
    }
