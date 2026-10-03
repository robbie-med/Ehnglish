# Ehnglish

Private monthly English assessment for one learner (bilingual English/한국어). The plan is
[docs/PLAN.md](docs/PLAN.md); this repo is at milestone **M4 (Rotating modules)**: the monthly core, the baseline day and the four rotating modules (R1–R4, form A) all record and are scored. Next: M5 dashboard + export.

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

## Processing pipeline (M1)

After a take is finalized the worker runs `wav_probe` and then `process_take`, which walks the steps
for the take's task type (`server/app/processing.py`). Each step is one `processing_results` row and
is skipped on retry if already present for the current pipeline version.

| Step (kind) | What | Needs |
|---|---|---|
| `asr:deepgram`, `asr:azure`, `asr:whisper` | three transcripts with word timings | API keys (each optional; skipped if blank) |
| `transcript` | ROVER-style majority vote, uncertain words marked, agreement % | — |
| `timing` | Praat syllable nuclei, pauses ≥250 ms, speech/articulation rate, MLR, onset, pitch | — |
| `latency` | response latency from `prompt_end`/`record_start` events + voice onset | — |
| `ei` | sentence-repetition syllable credit, exact match | — |
| `pron` | Azure pronunciation assessment (scripted, phoneme level, prosody) | Azure key |
| `phonemes` | wav2vec2 IPA recognizer vs expected phones; contrast tallies (r/l, f/p, …) | `--extra phonemes`, `EHNGLISH_PHONEMES_ENABLED` |
| `alignment` | Montreal Forced Aligner words/phones + rhythm (%V, ΔC, nPVI) | `mfa` container |
| `lexical`, `syntax` | MTLD, frequency bands, medical coverage; clauses, subordination, NP length | — |
| `correction`, `errors` | Claude minimal correction (3 runs, median) → ERRANT error types | Anthropic key |
| `wer` | dictation word error rate vs the key, tagged with the condition (clear/fast/phone/noise) | — |
| `phrases` | fixed phrases used in a phone turn (fuzzy match) | — |
| `checklist` | phone-call goal checklist over all turns so far (Claude, 3 runs, majority per goal) | Anthropic key |
| `lexical_decision` | LexTALE answer, correctness and reaction time | — |
| `typing` | keystroke measures: chars/min, bursts, pauses, revisions, copy accuracy | — |
| `ideas`, `expression_gap` | idea units (Claude) and Korean→English coverage + speech-rate ratio | Anthropic key |
| `mc` | multiple-choice answer, band/genre, reaction time | — |
| `reading` | words, reading time, words per minute (from the Done event) | — |
| `ctest` | C-test blanks, exact-match score | — |
| `axb` | AXB discrimination answer by contrast | — |

Task → steps: silence: probe only · read_aloud: asr, vote, timing, pron, phonemes, alignment ·
sentence_repeat: asr, vote, timing, latency, ei · quick_answer: asr, vote, timing, latency, language ·
describe_opinion: asr, vote, timing, alignment, language (English) or ideas (Korean baseline) · phone_call
(per turn): asr, vote, timing, latency, language, phrases, checklist · dictation (typed): wer ·
typed_response: typing + language (English) · lexical_decision: lexical_decision · copy_typing: typing ·
rating: stored only · multiple_choice: mc · reading_passage: reading · c_test: ctest · axb: axb ·
typed_response with goals (R4 email): typing, language, checklist.

**Session level.** When a sitting is marked done, a `session_summary` job (which waits for every take to
finish) writes `session_results` rows: `dictation` (mean WER per condition, phone/noise/fast penalties),
`lextale`, `typing` (per language), `ratings` (per scale, reverse-keyed items flipped), `phone_call`
(final checklist), `expression_gap`, `vocabulary` (size estimate by band, medical %), `comprehension` (per
question task, with genre), `reading` (wpm, comprehension, effective wpm), `c_test`, `axb` (by contrast),
`retell`, `email`, `completion`. `GET /api/sessions/{id}/results` returns them.

Forms: `core-A` (monthly core), `baseline-day1` (Korean writing/speaking, English retelling, LexTALE,
typing baselines, self-report), `rotating-R1-A` (vocabulary by band + medical), `rotating-R2-A` (timed
patient-information passage, questions, C-test), `rotating-R3-A` (conversation clip + questions + retell,
mini-lecture + questions, AXB on Korean-L1 contrasts; sermon clip task added via
`content/import_sermon_clip.py`), `rotating-R4-A` (clinic email with goal checklist, typing check, anxiety
scale), plus `dummy-v0`/`e2e-core` for tests (hidden in production). Multiple-choice options are shuffled
per session on the client; the YAML keeps the key at index 0.

Prompt audio effects (`fx:` on an item, rendered once by `content/build_audio.py`): `voice`, `rate`
(TTS prosody, e.g. "+35%" for the fast condition), `phone` (300–3400 Hz band, 8 kHz G.711 μ-law round
trip, band-limited hiss), `noise_snr_db` + `noise_kind` (pink or babble at a fixed SNR, seeded).

Prompt audio for real forms is built once with `content/build_audio.py` (Azure TTS) and committed.
