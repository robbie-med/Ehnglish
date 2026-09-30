"""Test setup: env vars first (settings are cached), then migrate the throwaway DB.

Needs the test Postgres: `docker compose -f deploy/docker-compose.test.yml up -d --wait`.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("EHNGLISH_ENV", "test")
os.environ.setdefault("EHNGLISH_DEV_EMAIL", "tester@example.com")
os.environ.setdefault("EHNGLISH_CONTENT_DIR", str(Path(__file__).resolve().parents[2] / "content"))
os.environ.setdefault(
    "EHNGLISH_DATABASE_URL", "postgresql+psycopg://ehnglish:ehnglish@127.0.0.1:3607/ehnglish"
)
os.environ.setdefault("EHNGLISH_PIPELINE_VERSION", "test.0.1")

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402

TABLES = [
    "processing_results",
    "jobs",
    "take_events",
    "typed_responses",
    "upload_chunks",
    "takes",
    "sessions",
    "users",
]


@pytest.fixture(scope="session", autouse=True)
def _migrate(tmp_path_factory: pytest.TempPathFactory) -> None:
    os.environ["EHNGLISH_RAW_DIR"] = str(tmp_path_factory.mktemp("raw"))
    get_settings.cache_clear()
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    with get_engine().begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(TABLES) + " CASCADE"))


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def db():
    with get_sessionmaker()() as s:
        yield s


def make_wav(
    seconds: float = 1.0, sample_rate: int = 48000, freq: float = 440.0, amp: float = 0.5
) -> bytes:
    n = int(seconds * sample_rate)
    t = np.arange(n) / sample_rate
    x = amp * np.sin(2 * np.pi * freq * t)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(pcm))
    return header + pcm
