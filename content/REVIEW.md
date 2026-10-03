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
| Monthly core A–F | `forms/core-A.yaml` … `core-F.yaml` | 54 each | C1 paragraph ≈80 words and 10 contrast words; C2 20 sentences 6–24 syllables (syllable counts auto-computed); C3 6 answerable questions; C4 six caller turns + goals + phrases ring true on the phone; C5 prompts; C6 12 dictation sentences, 3 per condition; C7 sliders |
| Baseline day 1 | `forms/baseline-day1.yaml` | 84 | Korean prompts (`ko`) natural; LexTALE list is the published one (do not edit); typing passages; can-do and anxiety statements |
| Vocabulary A, B, C | `forms/rotating-R1-{A,B,C}.yaml` | 40 each | Definitions unambiguous; distractors plausible; bands roughly right; medical items patient-side |
| Reading & grammar A, B, C | `forms/rotating-R2-{A,B,C}.yaml` | 9 each | A/C: patient leaflets, B: general academic (dual coding); 6 questions answerable from the text only; C-test deletions follow "second half of every second word" |
| Listening A, B, C | `forms/rotating-R3-{A,B,C}.yaml` | 31 / 26 / 26 | Conversation sounds like colleagues (slang, speed); lecture clear; AXB pairs are true minimal pairs; **A has a real sermon clip** (20 Sep 2026 Durham AM service, 26:26–28:26, Genesis 15) with four Claude-drafted questions to check; B and C deliberately have no sermon task (owner's call: keep the sermon part basic) |
| Writing A, B, C | `forms/rotating-R4-{A,B,C}.yaml` | 8 each | Email task realistic; 6 goals scoreable; typing sentence |

## Audio
- Prompt audio is Azure neural TTS (Andrew for prompts, Ava for the caller). The plan prefers
  **recorded** caller turns (C4) and conversation clips for natural speech: record them with the same
  text, save as 16 kHz mono WAV at the paths in the YAML, and they will be used as-is.
- Phone-line and noise conditions are applied by `content/build_audio.py` (G.711 + hiss; babble at
  +5 dB SNR). Listen to one of each once.

## Still open from plan §10
- Sermon clip: one basic clip is in R3-A; no more planned unless wanted.
- Whether the bilingual friend takes part (adds an "advanced learner" anchor: list the email in
  `EHNGLISH_ANCHOR_EMAILS`).
- Anchor sittings: all six core forms, the rotating forms, and one test–retest
  pair for the learner in the calibration week.
