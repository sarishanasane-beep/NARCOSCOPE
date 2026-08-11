from app.database.session import get_db

# Default reviewer identity (no authentication in Phase 1).
DEFAULT_USER = "reviewer"


def current_user() -> str:
    """Placeholder for future authentication."""
    return DEFAULT_USER
