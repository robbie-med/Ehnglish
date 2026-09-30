"""Runtime settings. Every value comes from the environment (prefix EHNGLISH_) or a .env file.

Secrets never live in the repo: on the server they sit in deploy/.env, which is gitignored.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EHNGLISH_", env_file=".env", extra="ignore")

    # dev | test | prod. Only dev/test honour dev_email; prod requires Cloudflare Access.
    env: str = "dev"
    database_url: str = "postgresql+psycopg://ehnglish:ehnglish@127.0.0.1:3607/ehnglish"

    # Raw-data store (WAVs, keystroke logs). Never deleted by the app.
    raw_dir: Path = Path("../data/raw")
    content_dir: Path = Path("../content")
    # Built PWA to serve at "/". None = API only (Vite dev server serves the UI).
    web_dist: Path | None = None

    # Identity. In dev/test a fixed email stands in for Cloudflare Access.
    dev_email: str | None = None
    # Cloudflare Access: team domain "myteam" -> https://myteam.cloudflareaccess.com
    cf_access_team_domain: str | None = None
    cf_access_aud: str | None = None
    # Optional belt-and-braces allow list (comma separated). Empty = trust Access alone.
    allowed_emails: str = ""

    # Stamped on every processing result. Bump when any metric code changes.
    pipeline_version: str = "m0.0.1"
    chunk_max_bytes: int = 4 * 1024 * 1024
    worker_poll_s: float = 2.0

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
