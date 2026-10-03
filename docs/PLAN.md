# Ehnglish — Plan

Status: **built through M5 (dashboard + export) and live at english.bo-bob.com; M6 calibration is
next.** §12 is the build log. The sections below are the spec as planned.

Two tools, built in order:

1. **Assessment** (this plan). A standardized 30-minute monthly English test whose job is to
   **collect objective data** and turn it into a dashboard and a machine-readable record.
2. **Trainer** (later, out of scope here). A practice app that reads the Assessment data and plans
   what to practise. Her courses, textbooks and helpers are inputs to the Trainer only; the
   Assessment does not use them.

---

## 0. Decisions so far

| Topic | Decision |
|---|---|
| Hosting | Owner's server (specs are in the owner's existing server documentation; **no GPU**), reached through Cloudflare Tunnel, with login by Cloudflare Access. Private. |
| Domain / login emails | To be supplied at build time. |
| Speech services | **Direct** Deepgram account and **direct** Azure Speech account. Paid APIs are fine. |
| LLM | Anthropic API, `claude-opus-5-5`. The owner has a Max plan; see the note in §9 about API billing. |
| Test length | **One 30-minute sitting per month**: a ~22 min core plus a ~9 min rotating module. |
| Baseline | A one-time baseline in the first week: 3 sittings of about 30 minutes. |
| Korean tasks | Baseline only. |
| Official tests | She will take TOEFL or IELTS herself later. The dashboard shows **estimated TOEFL and IELTS equivalents** in the meantime. |
| Medical focus | **Mostly patient-side language**: appointments, symptoms, pharmacy, insurance, instructions. |
| Accents | US English, **Northeast** emphasis. |
| Phone task | A scripted, standardized phone call. **No live AI caller.** |
| Device | Laptop, USB headset or Blue Yeti microphone, and headphones. |
| Audience | Both of them view the dashboard, a private web page. **Everything is bilingual, English and Korean.** |
| Output style | **Objective data, full detail by default. No coaching or feedback layer.** The main consumer is the Trainer. |
| Native anchor | The husband. Possibly also one advanced Korean–English bilingual friend. |
| Transcript review | **None by humans.** The app has to produce trustworthy transcripts on its own (§5). |
| Data sharing | Sending recordings to Deepgram, Azure and Anthropic is fine. |
| Sermons | Taken from the family's existing sermon-fetching app. |

---

## 1. Learner profile

- Native Korean speaker. About 11 years of English: roughly 4 in school, then about 8 of self-study
  that was mostly reading and listening, with almost no speaking partners.
  Now in the US. Takes prep courses and did well in a community college class.
- **Weak spots she reports:**
  - **Speaking confidence and overload.** She has to retrieve the word, the grammar and the
    pronunciation all at once.
  - **Professional and service vocabulary.** Reservations, tickets, doctor visits.
  - **Fast, abstract talk between colleagues**, including puns.
  - **Listening in hard conditions.** Phone audio, unclear voices, sermons.
- **Doing fine:** casual conversation.
- **Goals:** undergraduate-level English, then master's level. She will need a TOEFL or IELTS score,
  and she plans a career in medical illustration.

What the test must show: the gap between *knowing* English (receptive vocabulary, reading) and
*using it in real time* (speaking speed and pauses, how fast she answers, word recognition in
degraded audio).

---

## 2. Design principles

1. **This is data, not feedback.** The tool measures and records. Every number is shown with its
   definition, its uncertainty, and a comparison with the native anchor. There is no motivational
   framing and no advice; that belongs to the Trainer.
2. **Validated instruments carry most of the weight.** Established task types and measures from the
   research literature form the core. Custom tasks (the phone call, patient-side vocabulary, the
   sermon clips) are fewer and clearly labelled as custom.
3. **Deterministic code produces the numbers.** Claude does judgment tasks only (minimal error
   correction, idea units, checklist and rubric scoring). It returns structured JSON, scored 3 times
   with the median kept and the spread recorded.
4. **Everything scorable avoids transcription errors where possible.** Tasks with a known target
   (read-aloud, sentence repetition, dictation, C-test, vocabulary, multiple choice) make up most of
   the scoring. Free-speech transcripts come from several engines voting, and any uncertain stretch
   is excluded from counts (§5).
5. **Standardized and comparable.** Parallel test versions rotate. The audio is identical every
   time. Setup is logged each session: microphone, noise floor, time of day, sleep, stress.
6. **Keep all raw data and re-score it.** Every recording and keystroke log is kept. Every metric
   carries its pipeline version. When the pipeline improves, all past sessions are re-scored so
   trends never mix measurement methods.
7. **Honest uncertainty.** Each score has a confidence interval. Changes inside the measurement noise
   are labelled "no detectable change".

---

## 3. Architecture

```
 Laptop browser (PWA)                            Owner's server (Cloudflare Tunnel + Access)
 ┌──────────────────────────────┐   HTTPS   ┌──────────────────────────────────────────────┐
 │ Vite + TypeScript + React    │──────────▶│ FastAPI (Python) + Postgres                  │
 │ i18n: English / 한국어         │           │ Raw store: WAV + keystroke logs (+R2 backup) │
 │ AudioWorklet → 16-bit WAV    │           │ Job queue → CPU workers:                     │
 │ Keystroke logger             │           │   Deepgram · Azure (pron + STT) · Whisper API│
 │ Timed task runner            │           │   MFA alignment · Praat/parselmouth          │
 │ Offline upload queue (IDB)   │           │   wav2vec2 phoneme model (CPU) · spaCy · ERRANT│
 │ Dashboard                    │           │   Claude (judgment tasks) · scoring · export │
 └──────────────────────────────┘           └──────────────────────────────────────────────┘
```

- **No GPU is needed.** MFA, Praat, spaCy, ERRANT and a small phoneme model all run on CPU as a
  background job after each sitting. Results are ready within minutes.
- **Recording:** an AudioWorklet writes lossless 16-bit PCM, avoiding MediaRecorder's lossy codecs.
  Each take gets a quality check (clipping, loudness, signal-to-noise ratio) with an immediate
  re-record option.
- **Microphone:** use one mic and one room every month.
  - With the Blue Yeti: cardioid mode, a fixed distance of about 15–20 cm, gain set once and kept.
  - **Headphones are required** so test audio doesn't leak into the recording. They can plug into
    the Yeti.
- **Repo layout:**
  ```
  web/       PWA frontend (bilingual)
  server/    FastAPI app + processing pipeline
  content/   item bank (YAML), audio build scripts, frequency lists, scoring specs
  docs/      this plan, metric definitions, export schema
  ```

---

## 4. The battery

### 4.1 Schedule

| | Contents | Length |
|---|---|---|
| **Baseline week** (once) | Day 1: profile + Korean baseline. Day 2: core + writing. Day 3: vocabulary, reading and listening modules | 3 × ~30 min |
| **Monthly** | Core + one rotating module | ~30 min |
| **Rotation** | R1 Vocabulary → R2 Reading & grammar → R3 Listening depth → R4 Writing → repeat | Each module 3× per year |

**Why this is enough:** short, dense, automated speaking tests reach good reliability in under 20
minutes; the Versant English test is the model here. The measures that change month to month are
speaking fluency, response speed and listening under hard conditions, and those are in the core.
Vocabulary size, reading and writing change more slowly, so measuring them every 4 months fits
their pace.

### 4.2 Monthly core (~22 min)

| # | Task | What she does | Main measures | Basis |
|---|---|---|---|---|
| C0 | Setup | Mic check, 10 s of silence to record the noise floor, sleep/stress/mood sliders | Quality flags, covariates | — |
| C1 | **Read-aloud** (2 min) | One ~80-word paragraph plus 10 target words: Korean-L1 contrasts (r/l, f/p, v/b, z/dʒ, θ/s, i/ɪ, final consonants) and patient-side medical words | Pronunciation (phoneme accuracy, specific substitutions and extra vowels), word stress, prosody, reading-aloud rate | Azure Pronunciation Assessment, validated against human raters, plus a phoneme recognizer |
| C2 | **Sentence repetition** (elicited imitation) (6 min) | 20 sentences of 6–24 syllables, each heard once, then repeated after a tone | % of syllables correct, the longest length she repeats correctly, response onset time | Ortega et al.-style EI. A meta-analysis (Yan et al., 2016) found that it reliably separates proficiency levels |
| C3 | **Quick answers** (2 min) | 6 simple spoken questions | **Response latency**, fluency | Versant-style short-answer task |
| C4 | **Scripted phone call** (3 min) | A pre-recorded caller heard through a simulated phone line, about 6 turns, with fixed goals (e.g., "reschedule your appointment to next Tuesday afternoon and ask whether you need to fast"). Scenarios are mostly patient-side: scheduling, triage nurse, pharmacy refill, insurance, lab results, plus some general service | Goal-completion checklist, latency per turn, fluency, fixed phrases used | Custom task, standardized |
| C5 | **Describe, then give an opinion** (3.5 min) | A picture or process description (90 s), then an opinion question with 30 s of preparation and 90 s of speaking | Free-speech fluency (speed, breakdown, repair), syntactic complexity, lexical diversity and sophistication, accuracy | Standard fluency framework; a meta-analysis (Suzuki, Kormos & Uchihara, 2021) found speed and mid-clause pauses track proficiency best |
| C6 | **Dictation** in 4 conditions (4 min) | 12 sentences typed after hearing them: 3 clear, 3 fast, **3 through a phone line**, 3 in background noise at a fixed noise level | Word error rate per condition, **phone penalty** (phone WER minus clear WER), noise penalty | Dictation is a long-established integrated proficiency measure |
| C7 | Confidence (1 min) | Sliders for confidence on the phone, at the doctor, with colleagues, at church, in class | Self-rating trends | Can-do style |

This produces about 6 minutes of her speech every month. Tasks run from single words up to 90-second
monologues.

### 4.3 Rotating modules (~9 min each)

| Module | Contents | Measures |
|---|---|---|
| **R1 Vocabulary** | A section of the Updated Vocabulary Levels Test / Vocabulary Size Test (a different form each time, sampled across frequency bands), plus patient-side medical and service vocabulary items | Estimated vocabulary size by frequency band; domain coverage |
| **R2 Reading & grammar** | One timed passage (alternating patient information and general academic), plus a **C-test** (2 short texts in which words are partly deleted) | Words per minute, comprehension %, effective reading speed (wpm × accuracy), C-test score (an established overall proficiency and grammar measure) |
| **R3 Listening depth** | A ~2 min **sermon clip** (from the church app), plus a colleague-style conversation or mini-lecture clip with multiple-choice questions and a spoken retell, plus AXB sound discrimination on Korean-L1 contrasts | Comprehension by genre, idea units recalled in the retell, discrimination accuracy (perception vs production) |
| **R4 Writing** | A patient-side functional email (8 min, e.g., asking a clinic about test results and rescheduling), plus a 30 s typing check and a short speaking-anxiety scale | Checklist completion, accuracy by error type, complexity, keystroke measures (typing bursts, pauses, revisions), anxiety score |

### 4.4 Baseline-only tasks (Day 1, ~30 min)

- **Korean writing** (6 min): her goals, her interests, and a topic she knows well. Also gives a
  Korean typing speed.
- **Korean speaking** (5 min): goals (2 min), then the favorite topic (2 min). This establishes her
  **Korean fluency baseline**, so English fluency can be expressed relative to her own speaking style.
- **The same topic in English** (2 min). Gives the **expression gap**: the share of idea units she
  expressed in Korean that she also conveys in English, and the English/Korean speech-rate ratio.
- **LexTALE** (5 min). A validated vocabulary-based proficiency proxy. It has one fixed word list,
  so it is used at baseline only, never monthly.
- **Typing baseline** in English and Korean (3 min). Separates writing fluency from typing speed.
- **Self-report** (5 min): can-do statements and a speaking-anxiety scale.

### 4.5 Item bank, parallel forms, audio
- **6 parallel forms of the core**, so any one form comes back only every 6 months. Rotating modules
  get 3 forms each. Items are stored as YAML in `content/`, with their target properties
  (syllable count, word frequency band, structure).
- Claude drafts items to specification; the husband reviews them once as the native-speaker editor.
- **Audio:**
  - Recorded by the husband where natural speech matters (phone caller, conversation).
  - Otherwise neural text-to-speech with US voices, weighted toward a **Northeast** accent where
    voices are available.
  - Everything is generated once and stored, so the audio is identical each time.
- **Phone line:** real telephone codecs (8 kHz G.711 / AMR-NB via ffmpeg), line noise, and a fixed
  noise level.
- **Sermon clips** come from the existing church app, are transcribed once, and each is fixed to a
  specific form.

---

## 5. Processing pipeline (automated, no human review)

### 5.1 Tasks with a known target
Read-aloud, sentence repetition, dictation, C-test, vocabulary and multiple choice are scored against
the key. Specifically:
- **Sentence repetition:** her response is transcribed *without* giving the recognizer the target
  sentence, so it can't bias the transcript toward correct. It is then aligned to the target to
  score syllables. The phoneme recognizer provides a second opinion on each syllable.
- **Read-aloud:** Azure Pronunciation Assessment in scripted mode, plus wav2vec2 phoneme recognition
  to list the phonemes she actually produced vs the expected ones.

### 5.2 Free speech: transcription by vote
1. Three independent engines transcribe it:
   - **Deepgram Nova-3**: verbatim, filler words kept, no auto-formatting, a confidence per word.
   - **Azure Speech-to-Text**.
   - **Whisper large-v3** through a hosted API.
2. The three outputs are aligned word by word (ROVER), and a **majority vote** decides each word.
3. Stretches with no majority, or very low confidence, are marked **uncertain**. They are excluded
   from grammar and vocabulary counts but kept for timing.
4. Each task reports a **transcript agreement %** as a data-quality metric, so a low-confidence month
   is visible rather than hidden.
5. Korean audio at baseline goes to Deepgram (Korean) and Whisper.

### 5.3 Timing and acoustics
- **Montreal Forced Aligner** on the voted transcript gives word and phoneme timings. Alignment
  tolerates a few uncertain words.
- **Praat (parselmouth):**
  - Syllable-nucleus detection (De Jong & Wempe), which measures speech rate **independently of
    transcription**.
  - Pitch and intensity.
  - Rhythm measures (%V, ΔC, nPVI), for syllable-timed vs stress-timed rhythm.

### 5.4 Metrics
- **Fluency:**
  - Speed: speech rate, articulation rate (excluding pauses), mean length of run.
  - Breakdown: pauses ≥250 ms per minute, mean pause length, **share of pauses mid-clause vs at
    clause boundaries**, filled pauses, response latency.
  - Repair: repetitions, self-corrections, false starts.
- **Lexical:** MTLD (vocabulary diversity), frequency profile (SUBTLEX-US / NGSL bands), academic and
  medical coverage.
- **Syntactic:** clause length, subordination, phrase complexity (from spaCy parses).
- **Accuracy:** Claude makes a minimal correction; **ERRANT** classifies each edit (article,
  preposition, tense, agreement, …). Result: errors per 100 words by type, and % of error-free
  clauses.
- **Ideas:** Claude extracts idea units; code computes coverage (the baseline expression gap and the
  R3 retell).
- **Phone-call and email checklists:** Claude checks each goal item against the transcript or text,
  3 runs, median kept.

### 5.5 Scales and estimates
- Each metric is shown **raw**, then as a **% of the native anchor on the same form**, then as a
  0–100 domain scale, with a bootstrapped 95% confidence interval.
- **Estimated CEFR level by skill.** These are then mapped to **estimated TOEFL iBT section scores
  and IELTS bands** using the official CEFR concordance tables from ETS and IELTS. They are clearly
  labelled as estimates, and are recalibrated once she has a real TOEFL or IELTS score.

---

## 6. Outputs

### 6.1 Dashboard (bilingual toggle, full detail by default)
- **Per-domain panels:**
  - Speaking: fluency, pronunciation, complexity, accuracy, lexis, phone task, latency.
  - Listening: by condition (clear / fast / phone / noise) and by genre (sermon / conversation /
    lecture), plus sound discrimination.
  - Reading.
  - Writing.
  - Vocabulary: size by band and domain coverage.
  - Self-ratings.
- **Each metric shows:** its current value, the native anchor, a trend line with confidence band, and
  a one-line definition in both languages.
- **Estimated TOEFL / IELTS equivalents** per skill, clearly marked as estimates.
- **Session quality panel:** noise floor, clipping, transcript agreement, completion, and
  sleep/stress covariates.
- **Recording viewer:** any recording can be played with word-level timing, pauses shown as gaps, and
  phoneme mismatches marked. This is for checking the data, not coaching.

### 6.2 Machine-readable export
- `assessment_result.v1.json` (versioned schema) with every metric, confidence interval, item-level
  response, pipeline version and quality flag. **This is the contract with the Trainer.**

---

## 7. Validation and calibration

- **Native anchor:** the husband takes **every core form once** (6 × ~22 min, which can be spread
  out) plus the rotating forms. That anchors every form and lets forms be equated. If the bilingual
  friend takes part, they add an "advanced learner" reference point.
- **One native speaker is a thin norm.** It is supplemented with published native-speaker values
  where they exist, such as typical native speech rates and near-ceiling sentence-repetition scores.
- **Test–retest:** during calibration she takes the same core twice within one week. The difference
  measures the noise floor that decides what counts as "detectable change".
- **External calibration:** when she takes TOEFL or IELTS, the estimate mapping is refit.

---

## 8. Build milestones

| Milestone | Scope |
|---|---|
| **M0 Skeleton** | Repo, FastAPI + Postgres, Tunnel + Access, bilingual PWA shell, lossless recorder + upload queue, mic/noise check, item bank format, task runner |
| **M1 Speaking core** | C0–C3 and C5. Three-engine speech recognition with voting, MFA, Praat, Azure pronunciation, phoneme model, sentence-repetition scoring, fluency and language metrics |
| **M2 Phone + dictation** | Audio build pipeline (recording, TTS, phone codec, noise), C4, C6, C7, checklist scoring |
| **M3 Baseline tasks** | Korean writing and speaking, English comparison, idea-unit extraction, LexTALE, typing, self-report |
| **M4 Rotating modules** | R1–R4, keystroke logging, sermon clip import from the church app |
| **M5 Dashboard + export** | Scales, confidence intervals, trends, quality panel, recording viewer, TOEFL/IELTS estimates, JSON export |
| **M6 Calibration** | Native anchor on all forms, test–retest, then her baseline week |

**Rough running cost:** well under $2 per month. That covers about 6–15 minutes of audio through 3
speech engines, pronunciation scoring, and a few dozen Claude calls. There is a one-time cost of a
few dollars for text-to-speech when building the items.

---

## 9. Accounts and services to set up

- **Deepgram:** direct account (English and Korean speech-to-text).
- **Azure Speech:** direct account (pronunciation assessment and speech-to-text). Check whether the
  free tier covers the monthly volume.
- **Hosted Whisper large-v3:** e.g., the Groq or OpenAI API. This is the third voting engine.
- **Anthropic API key** from the Claude Console. **A Max plan does not include API usage**; the API
  is billed separately to a Console account.
- **Text-to-speech for item audio:** Azure neural voices and/or ElevenLabs (direct or via ppq.ai).
- **Cloudflare:** Tunnel, Access application, and optionally R2 for backups.

---

## 10. Still open (to settle at build time)

1. Domain or subdomain, and the login email addresses.
2. How to pull sermon audio from the existing church app (API, files, or database?).
3. Whether the bilingual friend takes part.
4. The husband's time for anchoring: all 6 core forms, about 2–2.5 hours in total, spread out.
5. The date of the first baseline week.
6. The server documentation location, to be linked or copied into `docs/` for the build session.

---

## 11. Tool 2 (Trainer): not planned here

It will be designed after the Assessment produces data. Its inputs will be the
`assessment_result.v1.json` history plus her courses, books, audio and people.

---

## 12. Build log (added during M0–M5, 2026-09-30 → 2026-10-03)

Decisions and deviations made while building, for the record. None reopens a §0 decision.

| Topic | What was built | Why / note |
|---|---|---|
| Hosting | This PC (`PC`, no GPU), four containers (api, worker, Postgres 16, Montreal Forced Aligner) on `127.0.0.1:3305`, published as `english.bo-bob.com` through the shared `diet-loggers` tunnel with Cloudflare Access (team `sikoraweb`). | §0 Hosting; the Hetzner VPS is too small and has no tunnel. |
| Login | Cloudflare Access JWT verified server-side; allow list of the two emails; learner/anchor roles from env. | §0 Domain/login emails, §7 anchors. |
| Whisper host | Groq (`whisper-large-v3`), switchable to OpenAI by env. | §9 "e.g. Groq or OpenAI". |
| Claude calls | `claude-opus-5-5` via the Anthropic SDK; forced tool choice and `temperature` are not accepted by this model, so calls ask for a tool and fall back to JSON in text. 3 runs, median kept, spread stored. | §2.3. |
| Headphone check | Objective: a 1 kHz tone is played during a short recording; leak > 12 dB over the silence reference blocks the sitting. | §3 "Headphones are required". |
| Noise floor | 10 s silence at setup (quality covariate) **and** C0 as a real stored take in every core form. | §4.2 C0. |
| Latency | Client events (`prompt_end`, `record_start`) plus Praat voice onset; never server clocks. | §4.2 C3. |
| Prompt audio | Azure neural TTS (Andrew; Ava as the phone caller), built once and committed; phone line = G.711 μ-law 8 kHz round trip + band-limited hiss; noise = seeded babble at +5 dB SNR; fast = TTS rate +35 %. Recorded human audio can replace any file at the same path. | §4.5. |
| Korean | Deepgram/Azure/Whisper in `ko`; normalisation keeps Hangul; English-only metrics skipped; idea units and coverage via Claude. | §4.4, §5.2.5. |
| Multiple choice | Keys kept at index 0 in YAML; options shuffled per (session, item) on the client; the original index is stored. | Keeps YAML readable without leaking positions. |
| LexTALE | Published 60-item list + 3 practice, F/J keys, reaction time recorded, `%correct_av`. | §4.4. |
| Scales | Bootstrapped 95 % CI over items; % of native anchor and 0–100 scale when anchor sittings exist on the same form; trends flagged by the test–retest noise floor (pairs of the same form within 10 days) or CI overlap. | §5.5, §7. |
| Estimates | CEFR per skill from labelled heuristic thresholds (median over indicators), mapped with the official ETS/IELTS concordances; refit by level offset once `content/calibration.yaml` has a real score. | §0 Official tests, §5.5. |
| Export | `assessment_result.v1.json` = session, setup, every take with item-level responses and results, session rollups, metrics with CIs, estimates, pipeline versions. | §6.2. |
| Pipeline versions | `m0.0.1` … `m5.0.0`; every result row carries the version that produced it; re-scoring appends rows. | §2.6. |
| Not yet | Core forms B–F and rotating forms B–C (content); the sermon clip task (needs a clip chosen); recorded caller audio; mid-clause vs boundary pause share (needs alignment + clause boundaries, M6 follow-up). | — |
