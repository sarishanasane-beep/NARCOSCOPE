from pathlib import Path

from app.config.settings import settings
from app.database.base import Base
from app.database.session import engine

# Importing the models package registers every table on Base.metadata.
import app.models  # noqa: F401  (side-effect import)


def ensure_directories() -> None:
    base = Path(settings.upload_directory)
    for sub in ("original", "extracted"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    Path(settings.upload_directory).parent.joinpath("demo", "generated").mkdir(
        parents=True, exist_ok=True
    )


def init_db() -> None:
    ensure_directories()
    Base.metadata.create_all(bind=engine)
