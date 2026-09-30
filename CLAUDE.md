# Ehnglish

A private English assessment tool (Tool 1), followed later by a practice app (Tool 2), for one
learner: a Korean native speaker working toward undergraduate- and then master's-level English,
with a focus on patient-side medical language.

**Read `docs/PLAN.md` before doing anything.** Section 0 lists every decision the owner has already
made. Section 10 lists what is still open.

Key points:
- The Assessment collects **objective data**, not feedback. The dashboard shows full detail, in
  English and Korean. The versioned JSON export is the contract with Tool 2.
- A 30-minute monthly test (~22 min core plus a ~9 min rotating module), and a one-time baseline
  week of 3 × 30 min.
- Hosted on the owner's server (no GPU) through Cloudflare Tunnel, with Cloudflare Access for login.
  Private.
- Frontend: Vite, TypeScript, React, PWA. Audio is recorded with an AudioWorklet as lossless WAV.
- Backend: Python (FastAPI) and Postgres, with a CPU job queue for processing.
- **No human transcript review.** Tasks with a known target carry most of the scoring. Free speech is
  transcribed by 3 engines that vote (Deepgram, Azure, Whisper), and uncertain stretches are
  excluded from counts. Then MFA alignment and Praat analysis via parselmouth.
- Code computes every metric. Claude (`claude-opus-5-5`) handles only judgment tasks, with
  structured output and 3 scoring runs (median kept).
- Keep all raw recordings, and tag every metric with the pipeline version that produced it.
- Do not build Tool 2 until the Assessment works.

## Working in this repo (M0 onward)

- Local dir on the owner's PC: `/home/user/Projects/ultimate_english` (GitHub `robbie-med/ehnglish`).
- `make help` lists everything: `make dev-api` / `make dev-web` for local dev, `make test`, `make e2e`,
  `make lint`, `make up` to deploy. See `README.md` and `docs/DEPLOY.md`.
- Ports are registered in `/home/user/Projects/PORTS.md` (3305 api, 3914 vite, 3607 test db). Do not
  bind others without claiming them.
- Item bank: `content/forms/*.yaml`, schema in `server/app/content.py`. Run `content/lint.py` after edits.
- New processing steps go in `server/app/worker.py` as job handlers writing `ProcessingResult` rows
  stamped with `EHNGLISH_PIPELINE_VERSION`. Bump the version whenever metric code changes.
- Secrets: only `deploy/.env` on the server (gitignored). Cloudflare API token for scripts lives outside
  the repo (`CLOUDFLARE_API_TOKEN_FILE`).
- Live: https://english.bo-bob.com (Cloudflare Access, team `sikoraweb`).
