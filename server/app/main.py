from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .content import get_forms
from .routers import forms, sessions, system, takes

log = logging.getLogger("ehnglish")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    forms_loaded = get_forms(str(settings.content_dir))
    log.info("loaded %d forms: %s", len(forms_loaded), sorted(forms_loaded))
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Ehnglish assessment API", version="0.0.1", lifespan=lifespan)
    app.include_router(system.router, prefix="/api")
    app.include_router(forms.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(takes.router, prefix="/api")

    dist = settings.web_dist
    if dist and Path(dist).is_dir():
        index = Path(dist) / "index.html"
        app.mount("/assets", StaticFiles(directory=Path(dist) / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str, request: Request):
            candidate = Path(dist) / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index)

    return app


app = create_app()
