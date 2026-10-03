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
    # Who is the learner (the dashboard's subject) and who are native/advanced anchors (plan §7).
    learner_email: str | None = None
    anchor_emails: str = ""

    # External engines (plan §9). Read at call time; missing keys make that step skip, not crash.
    deepgram_api_key: str | None = None
    azure_speech_key: str | None = None
    azure_speech_region: str | None = None  # e.g. eastus
    whisper_base_url: str = "https://api.groq.com/openai/v1"  # or https://api.openai.com/v1
    whisper_api_key: str | None = None
    whisper_model: str = "whisper-large-v3"  # OpenAI: whisper-1
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    # CPU phoneme recognizer (optional extra `phonemes`). Off by default so dev installs stay small.
    phonemes_enabled: bool = False
    phoneme_threads: int = 4
    # Montreal Forced Aligner HTTP shim (deploy/docker-compose.yml service `mfa`). None = skip.
    mfa_url: str | None = None

    # Stamped on every processing result. Bump when any metric code changes.
    pipeline_version: str = "m1.0.0"
    chunk_max_bytes: int = 4 * 1024 * 1024
    worker_poll_s: float = 2.0

    @property
    def anchor_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.anchor_emails.split(",") if e.strip()}

    def role_for(self, email: str) -> str:
        e = email.lower()
        if e in self.anchor_email_set:
            return "anchor"
        if self.learner_email and e == self.learner_email.lower():
            return "learner"
        return "learner" if not self.learner_email else "other"

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
