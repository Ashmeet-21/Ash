"""Runtime settings, read from environment variables (prefix JOBMATCH_) or a .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOBMATCH_", env_file=".env", extra="ignore")

    # PostgreSQL in production (postgresql+psycopg://...); SQLite works for local dev and tests.
    database_url: str = f"sqlite:///{BACKEND_DIR / 'jobmatch.db'}"

    # Single source of truth for what you can claim. Falls back to the example file.
    facts_path: Path = DATA_DIR / "facts.yaml"
    watchlist_path: Path = DATA_DIR / "watchlist.yaml"
    regions_path: Path = DATA_DIR / "regions.yaml"
    # Built DOCX/PDF resumes.
    output_dir: Path = DATA_DIR / "output"

    # Optional bearer token. When set, every endpoint except /health requires it.
    api_token: str | None = None
    cors_origins: str = "http://localhost:3000"

    # Claude is optional: without a key the deterministic extractor and template tailor are used.
    use_llm: bool = True
    extract_model: str = "claude-haiku-5-5"
    draft_model: str = "claude-sonnet-5-5"
    max_redrafts: int = 3

    # Aggregator keys (Adzuna is free for personal evaluation; attribution required).
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None

    # Daily ingest inside the API process. Off by default; a cron hitting POST /jobs/ingest works too.
    scheduler: bool = False
    ingest_cron_hour: int = 7

    # Jobs scoring at or above this are reported as new matches after ingest.
    alert_min_score: int = 70


@lru_cache
def get_settings() -> Settings:
    return Settings()


def resolve_data_file(path: Path) -> Path:
    """Use the real file if present, else the committed `.example` twin."""
    if path.exists():
        return path
    example = path.with_name(path.stem + ".example" + path.suffix)
    return example
