# Native-speaker review checklist (plan §4.5: "Claude drafts items; the husband reviews once")

Everything below was drafted to the plan's specifications and has **not** been read by a native
speaker yet. Review once, edit the YAML directly, bump the form's `version`, delete any audio file
whose text changed (the builder regenerates only missing files), run `content/lint.py`, rebuild audio,
commit. Item ids must stay stable; change text, not ids.

## What to check in every form
- Natural, American, patient-side English. Nothing a Northeast clinic receptionist would not say.
- Difficulty ladder preserved where there is one (C2 sentences get longer; vocabulary bands ascend).
- Keys are right (`target.answer`, C-test solutions, AXB `answer`, dictation sentences).
- Nothing offensive, nothing that depends on culture she would not know.
- Bilingual instructions: the Korean (`ko`) should read naturally, not like a translation.

## Forms
| Form | File | Items | Specific checks |
|---|---|---|---|
| Monthly core A | `forms/core-A.yaml` | 54 | C1 paragraph ≈80 words and 10 contrast words; C2 20 sentences 6–24 syllables (syllable counts auto-computed); C3 6 answerable questions; C4 six caller turns + goals + phrases ring true on the phone; C5 prompts; C6 12 dictation sentences, 3 per condition; C7 sliders |
| Baseline day 1 | `forms/baseline-day1.yaml` | 84 | Korean prompts (`ko`) natural; LexTALE list is the published one (do not edit); typing passages; can-do and anxiety statements |
| Vocabulary A | `forms/rotating-R1-A.yaml` | 40 | Definitions unambiguous; distractors plausible; bands roughly right; medical items patient-side |
| Reading & grammar A | `forms/rotating-R2-A.yaml` | 9 | Passage reads like a real prep leaflet; 6 questions answerable from the text only; C-test deletions follow "second half of every second word" |
| Listening A | `forms/rotating-R3-A.yaml` | 26 | Conversation sounds like colleagues (slang, speed); lecture clear; AXB pairs are true minimal pairs; **sermon task still to add** (`content/import_sermon_clip.py`) |
| Writing A | `forms/rotating-R4-A.yaml` | 8 | Email task realistic; 6 goals scoreable; typing sentence |

## Audio
- Prompt audio is Azure neural TTS (Andrew for prompts, Ava for the caller). The plan prefers
  **recorded** caller turns (C4) and conversation clips for natural speech: record them with the same
  text, save as 16 kHz mono WAV at the paths in the YAML, and they will be used as-is.
- Phone-line and noise conditions are applied by `content/build_audio.py` (G.711 + hiss; babble at
  +5 dB SNR). Listen to one of each once.

## Still open from plan §10
- Sermon clip for R3 (which sermon, which 2 minutes).
- Whether the bilingual friend takes part (adds an "advanced learner" anchor: list the email in
  `EHNGLISH_ANCHOR_EMAILS`).
- Anchor sittings: all six core forms (B–F still to draft), the rotating forms, and one test–retest
  pair for the learner in the calibration week.
