from pathlib import Path

from sqlalchemy import inspect, text

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


def _migrate() -> None:
    """Idempotent additive migrations for pre-existing databases.

    ``create_all`` only creates missing tables; databases created before a
    column was added keep their old schema. Each step below checks the
    live schema and applies the smallest ALTER needed — no data is ever
    dropped or reset.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    def _add_column(table: str, column: str, definition: str) -> None:
        columns = {c["name"] for c in inspector.get_columns(table)}
        if column not in columns:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))

    if "entities" in tables:
        _add_column("entities", "structured_metadata", "JSON")
        _add_column("entities", "document_id", "VARCHAR(36)")
        _add_column("entities", "merged_into_id", "VARCHAR(36)")
        _add_column("entities", "merged_into_case_id", "VARCHAR(36)")
    if "events" in tables:
        _add_column("events", "event_time", "VARCHAR(20)")
        _add_column("events", "document_id", "VARCHAR(36)")
        _add_column("events", "evidence_id", "VARCHAR(36)")
        _add_column("events", "structured_metadata", "JSON")
    if "documents" in tables:
        _add_column("documents", "case_id", "VARCHAR(36)")
        _add_column("documents", "structured_validation", "JSON")
    if "cases" in tables:
        _add_column("cases", "merged_into_id", "VARCHAR(36)")


def init_db() -> None:
    ensure_directories()
    Base.metadata.create_all(bind=engine)
    _migrate()
