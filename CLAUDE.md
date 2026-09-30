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
