# Ehnglish

Private monthly English assessment for one learner (bilingual English/한국어). The plan is
[docs/PLAN.md](docs/PLAN.md); this repo is at milestone **M0 (Skeleton)**.

```
web/       Vite + React + TypeScript PWA. AudioWorklet → 16-bit WAV, quality check, resumable upload queue, timed task runner.
server/    FastAPI + Postgres (SQLAlchemy 2, Alembic). Chunked uploads, raw store on disk, Postgres job queue + worker.
content/   Item bank as YAML (content/forms/*.yaml), validated by content/lint.py.
deploy/    Dockerfile, docker-compose.yml, Cloudflare scripts, .env.example.
docs/      PLAN.md (spec), DEPLOY.md, SERVER.md.
```

## Run locally

Requirements: Docker, uv, Node 22+ (`~/.nvm/versions/node/v24.16.0` on the owner's PC; the Makefile adds it to PATH).

```bash
make setup      # uv sync, npm ci, playwright chromium
make dev-api    # starts the throwaway Postgres (127.0.0.1:3607) and the API on 127.0.0.1:3305 as dev@example.com
make dev-web    # Vite on http://127.0.0.1:3914 (proxies /api)
make dev-worker # optional: processes queued jobs
```

Open http://127.0.0.1:3914. Add `?quick=1` to the setup URL to record 1 s of silence instead of 10 s.

## Tests

```bash
make test       # pytest (needs Docker for the test Postgres) + vitest
make e2e        # Playwright: fake microphone → real recorder → upload → WAV verified on the server → worker
make lint       # ruff, content lint, tsc, oxlint
```

## Deploy

See [docs/DEPLOY.md](docs/DEPLOY.md). Short version: `deploy/.env`, `deploy/cf-access-app.sh`,
`deploy/tunnel-add-ingress.sh`, `make up`.

## API (M0)

All under `/api`, identity from Cloudflare Access (or `EHNGLISH_DEV_EMAIL` in dev/test):

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/me` | liveness; who am I |
| GET | `/forms`, `/forms/{id}` | item bank |
| POST/GET/PATCH | `/sessions`, `/sessions/{id}` | a sitting; `setup` carries C0 covariates |
| POST | `/sessions/{id}/takes` | start a take (audio or typed); a new attempt supersedes the old |
| PUT | `/takes/{id}/chunks/{n}` | resumable chunk upload |
| GET | `/takes/{id}/upload-status` | which chunks arrived |
| POST | `/takes/{id}/finalize` | assemble, verify sha256 + WAV header, store, enqueue `wav_probe` |
| POST | `/takes/{id}/typed` | text + keystroke log (JSONL on disk) |
| POST | `/takes/{id}/events` | client timeline (`prompt_end`, `record_start`, …) |
| GET | `/takes/{id}`, `/takes/{id}/audio` | take with results; the WAV |

Every `processing_results` row carries `pipeline_version` (`EHNGLISH_PIPELINE_VERSION`).
