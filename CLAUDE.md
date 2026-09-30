# Ehnglish

A private English assessment tool (Tool 1), followed later by a learning tool (Tool 2), for one
learner: a Korean native speaker working toward undergraduate- and then master's-level English,
with a focus on medical terminology.

**Read `docs/PLAN.md` before doing anything.** It holds the learner profile, design principles,
architecture, test battery, processing pipeline, milestones (M0–M6) and open questions.

Key decisions already made:
- Hosted privately on the owner's server through Cloudflare Tunnel, with Cloudflare Access for
  login. Not public, and not GitHub Pages.
- Frontend: Vite, TypeScript, React, installable PWA. Audio is recorded with an AudioWorklet as
  lossless WAV.
- Backend: Python (FastAPI) and Postgres, with a job queue for processing.
- Accuracy first: several speech engines (Deepgram and Whisper), a human review step to produce the
  final transcript, forced alignment (MFA), and acoustic analysis in Praat via parselmouth.
- Code computes every metric. Claude (`claude-opus-5-5`) handles only judgment tasks, with
  structured output and repeated scoring runs.
- Keep all raw recordings, and tag every metric with the pipeline version that produced it.
- Build Tool 2 only after Tool 1 works.

Before starting M0, check section 9 of `docs/PLAN.md` for open questions the owner may since have
answered.
