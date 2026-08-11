"""Application configuration.

NARCOSCOPE runs fully in deterministic (non-AI) mode when no AI key is
configured. All settings can be overridden through environment variables
or a ``.env`` file placed at the project root (see ``.env.example``).
"""

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config/settings.py -> config -> app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "NARCOSCOPE"
    version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # AI (optional — the application must work without it)
    ai_enabled: bool = False
    ai_provider: str = ""
    ai_api_key: str = ""

    # Database
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'database' / 'narcoscope.db'}"

    # Storage
    upload_directory: str = str(PROJECT_ROOT / "data" / "documents")
    max_upload_size: int = 25 * 1024 * 1024  # 25 MiB

    # Processing
    process_on_upload: bool = True

    @model_validator(mode="after")
    def _resolve_relative_paths(self) -> "Settings":
        # Resolve relative sqlite paths against the project root so the app
        # behaves the same regardless of the current working directory.
        if self.database_url.startswith("sqlite:///./"):
            rel = self.database_url[len("sqlite:///./") :]
            self.database_url = f"sqlite:///{PROJECT_ROOT / rel}"
        if self.upload_directory.startswith("./"):
            self.upload_directory = str(PROJECT_ROOT / self.upload_directory[2:])
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
