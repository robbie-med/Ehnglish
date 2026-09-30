# Ehnglish — Plan

Status: **planning only, nothing built yet.**
Two tools, built in order:

1. **Assessment** (build first). A monthly, standardized English test that collects objective data
   and turns it into a dashboard she can track over time.
2. **Trainer** (build after the Assessment works). A learning tool that reads the Assessment results
   plus an inventory of her books, audio, courses and people, and plans evidence-based practice
   aimed at her weakest areas.

---

## 1. Learner profile (what the design is built around)

- Native Korean speaker. About 11 years of English: roughly 4 in school, then about 8 of self-study
  that was mostly reading and listening, with almost no speaking partners.
  Now living in the US. Takes prep courses and did well in a community college class.
- **What she says is hard:**
  - **Speaking.** Low confidence, and **cognitive overload**: she has to retrieve the word, the
    grammar and the pronunciation all at once while speaking.
  - **Register.** She lacks the vocabulary for professional conversations and for service tasks
    (reservations, tickets, phone calls, doctor's appointments).
  - **High-level talk.** Colleague conversations with fast, abstract, pun-heavy language.
  - **Listening under hard conditions.** Phone audio, unclear voices, and long monologues such as
    sermons.
  - **Medical terminology.** She needs it as a patient, and it is core to her goal of becoming a
    medical illustrator.
- **What she says is fine:** casual conversation, which is improving.
- **Goals:** undergraduate-level discussion first, then master's level in a few years.

This profile points to what the test must separate: *knowing* English (large receptive vocabulary,
good reading) versus *using it in real time* (speech rate, pauses, how fast she recognizes words in
degraded audio). Her reading and writing likely run well ahead of her speaking and listening. The
test has to measure that gap precisely, because the Trainer's priorities depend on it.

---

## 2. Design principles

1. **Numbers come from deterministic code. The LLM does not produce the numbers.**
   Speech rate, pauses, word error rates, vocabulary size, reading speed and item scores are
   computed by code. Claude does judgment tasks only: idea-unit extraction, error correction,
   rubric scoring and the narrative report. Every judgment call is structured JSON, run several
   times, and averaged, and we record how much the runs disagree.
2. **The transcript has to be verbatim, not "cleaned up".** Speech recognition quietly fixes
   learner errors: she says "he go yesterday" and the transcript says "he went yesterday". It also
   drops "um" and "uh". Either would corrupt the data, so we use an ensemble of engines, flag
   disagreements, and add a short human verification step (see §5.2).
3. **The test is standardized, so months can be compared.** It uses a fixed item bank with
   **parallel forms** that rotate each month to avoid practice effects. The pre-recorded audio is
   identical every time, the instructions are the same, and the setup is logged (microphone, room
   noise, time of day, sleep and stress self-rating).
4. **Keep the raw data forever.** Every recording and keystroke log is stored. Every metric carries
   the version of the pipeline that produced it. When better models arrive, all past sessions are
   **re-scored** with the new pipeline, so trend lines never mix measurement methods.
5. **Anchor to native speakers.** You and one or two native-speaker friends take the same battery
   once. Her numbers are then shown against "a native speaker doing *this exact task*", which beats
   abstract scales.
6. **Honest uncertainty.** Every score gets a confidence band. A change smaller than the
   measurement noise is shown as "no clear change".
7. **Private.** The app is served only behind Cloudflare Access. Data lives on your server. Third
   parties (Deepgram, Azure, Anthropic) see only the audio or text sent for processing, with
   retention minimized where each vendor allows it.

---

## 3. Architecture

```
 Browser (PWA, laptop preferred)                Your server (via Cloudflare Tunnel)
 ┌──────────────────────────────┐   HTTPS   ┌─────────────────────────────────────────┐
 │ Vite + TypeScript + React    │──────────▶│ FastAPI (Python)                        │
 │ - AudioWorklet → lossless WAV│  (behind  │ - sessions, items, uploads, results API │
 │ - keystroke logger           │ Cloudflare│ Postgres (metadata, metrics, items)     │
 │ - timed task runner          │  Access)  │ Audio/keystroke store on disk (+R2 bkp) │
 │ - offline upload queue (IDB) │           │ Job queue → processing workers          │
 │ - dashboard (charts)         │           │   ASR ensemble · alignment · Praat ·    │
 └──────────────────────────────┘           │   NLP metrics · Claude scoring · report │
                                            └─────────────────────────────────────────┘
```

- **Frontend:** Vite, TypeScript, React, and `vite-plugin-pwa`. It is served from Cloudflare Pages
  or directly from the server, behind **Cloudflare Access** (email one-time-code login for her and
  for you). GitHub Pages is public, so it is not used.
- **Recording:** an `AudioWorklet` captures 16-bit PCM WAV. We avoid MediaRecorder because it gives
  Opus on Chrome and AAC on Safari, which would make results inconsistent across devices. Recordings
  upload in chunks, with a resume queue in IndexedDB so a flaky connection never loses a take.
  Each take is checked for clipping, loudness and signal-to-noise ratio, with an immediate retry if
  needed.
- **Backend:** FastAPI and Postgres. Workers use a Postgres-backed job queue (or Redis + RQ). One
  processing run per session, versioned.
- **Repo layout (proposed):**
  ```
  web/        PWA frontend
  server/     FastAPI app + processing pipeline (Python)
  content/    item bank (YAML), scripts to generate/record/degrade audio, frequency lists
  docs/       this plan, scoring spec, data schema
  ```

---

## 4. The assessment battery

**Total: about 80–90 minutes, split into two sittings** (A and B, which can be on different days
within one week). Instructions are bilingual (Korean and English). Each task ends with a one-tap
rating of mental effort ("how hard was that?", 1–9). Over time those ratings track the cognitive
overload she describes.

### Sitting A — Speaking & Listening (~45 min)

| # | Task | What she does | Why / key metrics |
|---|------|---------------|-------------------|
| A0 | Setup | Mic check, 10 s room silence, headphone check, sleep/stress/mood sliders | Measurement quality and covariates |
| A1 | **Korean writing** | Types her goals, interests, and a topic she knows well (≈5 min) | Profile for personalization; Korean typing speed baseline |
| A2 | **Korean speaking** | Talks about her goals (2 min) and a favorite topic (2 min) | **Her L1 fluency baseline**: speech rate, pause habits and idea density in Korean. English fluency is then reported *relative to her own Korean*, which removes personal style from the comparison |
| A3 | **Same topic in English** | Talks about the same favorite topic (2 min) | **"Expression gap"**: what share of the ideas she expressed in Korean she also gets across in English, plus the English/Korean speech-rate ratio |
| A4 | **Read-aloud** | Words (including minimal pairs and medical terms), then sentences, then a paragraph | The reference text is known, so pronunciation, prosody and stress can be scored exactly. Targets typical Korean-L1 patterns: r/l, f/p, v/b, z/dʒ, θ/s, i/ɪ, extra vowels after final consonants, final consonants that are held but not released, syllable-timed rhythm |
| A5 | **Sentence repetition** (elicited imitation) | Hears 24 sentences, from 6 up to 26 syllables, and repeats each exactly | A well-validated measure of overall oral proficiency that directly loads on real-time processing, her self-described bottleneck. Score: % of syllables correct by sentence length |
| A6 | **Quick answers** | 10 simple spoken questions ("What did you eat for breakfast?") | **Response latency** (ms from question end to speech start). Short sentences first, to build confidence |
| A7 | **Phone role-plays** | Audio through a simulated phone line: restaurant reservation, rescheduling a doctor's appointment, describing symptoms to a nurse, pharmacy, returning an item, a ticket problem | Task completion, the right fixed phrases ("I'd like to…", "Could you…"), politeness/register, latency, fluency. This is the register she worries about most |
| A8 | **Describe a process or image** | An anatomical illustration and a picture sequence | Descriptive and spatial language in her future field; picture tasks are highly comparable month to month |
| A9 | **Opinion** | 30 s to prepare, 90 s to speak (TOEFL-style) | Academic register: organization, linking words, complexity |
| A10 | **Listen and retell** | Hears a 90 s mini-lecture, then retells it | Integrated listening-to-speaking; share of idea units recalled |
| A11 | **Sound discrimination** | AXB minimal pairs (which of two sounds matches the third) | Whether she *hears* the contrasts she mispronounces (perception vs production) |
| A12 | **Dictation under conditions** | Types sentences heard as: clear, fast, **phone-band**, noisy, unfamiliar accent | **Word error rate for each condition**. The phone-band minus clear difference puts an exact number on her "phone penalty" |
| A13 | **Speech-in-noise threshold** | Adaptive sentences-in-noise test, **in English and in Korean** | The English-minus-Korean gap is the second-language penalty. If her Korean threshold is also poor, get a hearing test, since part of the phone problem may not be about language |
| A14 | **Listening comprehension** | Multiple choice after: a conversation, a voicemail, a lecture, a **sermon-style monologue**, and **colleague banter with idioms and puns**, at 0.9×, 1.0× and 1.2× speed | Comprehension for each genre and speed; pragmatic inference (did she get the joke or the implication?) |

A2–A10 give **about 12–15 minutes of her speech** (well above the 5-minute minimum), rising from
single words to 2-minute monologues so she is never dropped cold into free speech.

### Sitting B — Reading, Writing, Vocabulary (~40 min)

| # | Task | What she does | Metrics |
|---|------|---------------|---------|
| B1 | **Typing baseline** | Copies a short text in English and in Korean | Typing speed, so that writing fluency is not confused with motor speed |
| B2 | **Receptive vocabulary size** | Adaptive yes/no test with fake words mixed in, sampling frequency bands from 1k to 20k words | Estimated number of word families she knows, corrected for guessing using the fake words (the LexTALE / X-Lex approach) |
| B3 | **Domain vocabulary** | Short banked tests: academic word list, medical (word parts, anatomy, patient-side terms), service/transactional words, phrasal verbs and idioms, collocations | Coverage by domain |
| B4 | **Productive vocabulary** | Fill-in-the-blank with the first letters given (C-test / productive levels style) | Words she can *produce*, not only recognize; the receptive vs productive gap |
| B5 | **Timed reading** | 4 passages at graded levels: everyday/service, patient information (e.g., discharge instructions), general academic, anatomy/science | Words per minute read, comprehension %, and **effective reading speed** (wpm × accuracy) |
| B6 | **Sentence verification speed** | Rapid true/false sentences | Reading efficiency (how automatic reading is) |
| B7 | **Functional email** | 10 min: e.g., email a clinic to reschedule and ask about insurance | Task completion, register, accuracy |
| B8 | **Academic writing** | 20 min: short argument or explanation | Rubric score, complexity, accuracy, lexical sophistication |
| B9 | **Self-report** | Can-do statements by situation; a short speaking-anxiety scale; confidence per situation (phone, doctor, colleagues, church, class) | The affective side, tracked alongside skill |

Keystroke logging runs through B7 and B8: typing bursts, pause lengths, where pauses fall, and how
much she deletes and revises. Research on writing processes uses exactly these to separate "can't
find the words" from "is editing".

### Item bank and parallel forms
- Claude drafts the items at controlled difficulty. **You review them as the native-speaker
  editor.** Items are stored as YAML in `content/`.
- Each task has **at least 4 parallel forms**, rotated monthly. Item difficulty is re-estimated from
  her responses and the native baselines, so forms can be kept equivalent over time.
- Listening audio is generated once with high-quality neural voices across several accents. Where
  realism matters (banter, phone calls, sermon style), some items are **recorded by you and
  friends**. Phone-band versions are made with a real phone codec (8 kHz G.711 / AMR-NB through
  ffmpeg) plus a mild line-noise and babble layer, so they sound like an actual phone call.
- If you can get sermon recordings from her church, a few are used, with permission, as
  comprehension items.

---

## 5. Processing pipeline (Python, on your server)

### 5.1 Speech recognition
- **Korean speech:** Deepgram (Korean model) plus Whisper large-v3.
- **English speech:** Deepgram Nova-3 in verbatim mode (filler words on, word timestamps and
  confidences), plus Whisper large-v3 run locally through WhisperX if the server has a GPU, or via
  API otherwise. Optionally a third engine (Azure).
- The outputs are aligned word by word, ROVER-style. Any span where the engines disagree, or where
  confidence is low, is flagged.

### 5.2 Getting to a "gold" transcript
No speech recognizer is 100% accurate on accented learner speech, so we don't pretend one is.
Instead:
- A small **review screen** plays each flagged snippet. You pick the right version or type what she
  actually said, keeping her errors exactly as spoken. Expect about 5–10 minutes per session.
- For read-aloud and sentence repetition the target text is already known, so these tasks need no
  guessing.
- The result is a transcript that is effectively exact. It is the *only* input to the scoring.

### 5.3 Alignment and acoustics
- **Montreal Forced Aligner** on the gold transcript gives exact start and end times for every word
  and phoneme.
- **Praat (via parselmouth):** pitch contour, intensity, syllable-nucleus detection (the De Jong &
  Wempe method, which gives a speech rate that does not depend on speech recognition), and rhythm
  measures (%V, ΔC, nPVI), which capture the Korean syllable-timed vs English stress-timed contrast.
- **Pronunciation:**
  - Azure Pronunciation Assessment gives phoneme-level accuracy, fluency and prosody scores against
    the reference text.
  - A phoneme recognizer (wav2vec2 phoneme model) reports what she *actually* produced, compared
    with the expected phonemes. That shows specific substitutions and insertions (e.g., /r/→/l/,
    an extra vowel after a final consonant) rather than just a score.

### 5.4 Fluency (from the alignment), using the standard three-part framework
- **Speed:** speech rate (syllables/s), articulation rate (speech rate excluding pauses),
  mean length of run between pauses.
- **Breakdown:** silent pauses (≥250 ms) per minute, their mean length, and **where** they fall
  (mid-clause vs clause boundary). Mid-clause pausing is the signature of word-finding overload.
  Also filled pauses (um/uh) and response latency.
- **Repair:** repetitions, self-corrections, false starts.
- All of these are also reported as a **ratio to her own Korean baseline** and to the **native
  anchor**.

### 5.5 Language (from the gold transcripts and her writing)
- **Lexical:** diversity (MTLD, which does not depend on text length), sophistication (frequency
  profile against SUBTLEX-US and NGSL bands, academic word list coverage), and the share of
  multi-word chunks.
- **Syntactic complexity:** clause length, subordination, phrase complexity (computed from spaCy
  parses).
- **Accuracy:** Claude produces a *minimal* correction. **ERRANT** then classifies each edit
  deterministically (verb tense, article, preposition, agreement, …). That gives error rates per
  100 words by category, plus the share of error-free clauses. Articles and prepositions are
  expected to be the big categories for a Korean speaker.
- **Ideas:** Claude extracts idea units from the Korean and English versions of the same topic (A2
  vs A3) and from the lecture vs her retelling (A10). The code then computes coverage.

### 5.6 Rubric scoring (Claude)
- Model: `claude-opus-5-5`, with structured JSON output. Claude works on the gold transcripts and
  the computed metrics, not on raw audio.
- Rubrics are written out as descriptors with anchor examples. Each response is scored 3 times
  independently; the median is used and the spread is logged. If the spread is too large, the item
  is flagged for your review.
- Rubric dimensions: task completion, organization/coherence, register/politeness, lexical range,
  grammar range and accuracy. Each maps to CEFR-style bands.

### 5.7 Aggregation
- Each domain's raw metrics are converted to scales that are **anchored**:
  - 0 means the lowest plausible learner.
  - 100 means the native-anchor median on the same task.
- Each domain also gets an estimated CEFR band (A2 … C2), with a confidence interval computed by
  bootstrapping over items.
- **Optional one-time calibration:** she takes one external scored test around the first
  assessment, for example Pearson Versant (automated, and closest to this battery) or the Duolingo
  English Test. That maps our scales to a recognized reference point.

---

## 6. Dashboard

- **Top line:** one card per domain with the current band, the change since last month (only if
  larger than the noise), and a sparkline.
- **Domains and sub-scores:**
  - **Speaking.** Fluency (speed / breakdown / repair), pronunciation (segments, word stress,
    rhythm, intonation), complexity, accuracy, lexis, functional/phone tasks, and response latency.
  - **Listening.** By condition (clear / fast / phone / noise / accent), by genre (conversation /
    voicemail / lecture / sermon / banter), the speech-in-noise gap, and sound discrimination.
  - **Reading.** Effective reading speed and comprehension for each text type.
  - **Writing.** Rubric scores, accuracy by error type, complexity, and writing fluency.
  - **Vocabulary.** Estimated size (receptive and productive) and coverage by domain (academic /
    medical / service / idioms).
  - **Confidence and effort.** Self-rated confidence per situation, anxiety score, and mental-effort
    ratings per task type.
- **Drill-down:** listen to any take with the transcript highlighted word by word, pauses shown as
  gaps, and mispronounced phonemes marked. This is useful for her to *hear* her own patterns.
- **Priority map:** each weakness ranked by (how far below target) × (how much it matters for her
  goals). This is the handoff to the Trainer.
- **Report:** a narrative summary per assessment, generated in **Korean and English**, citing the
  numbers from the dashboard. It never invents numbers.
- **Export:** a versioned JSON schema (`assessment_result.v1.json`) that the Trainer, or a future
  Claude session, can read directly.

---

## 7. Build milestones (Tool 1)

| Milestone | Scope | Value on completion |
|-----------|-------|---------------------|
| **M0 Skeleton** | Repo structure, FastAPI + Postgres, Cloudflare Tunnel + Access, PWA shell, lossless recorder with upload queue, mic/SNR check | Can record securely |
| **M1 Profile + first speech data** | A1–A3, speech-recognition ensemble, review screen, alignment, fluency metrics, Korean-vs-English comparison | First objective fluency numbers and the expression-gap measure |
| **M2 Speaking ladder** | A4–A10, pronunciation pipeline, error annotation, rubric scoring | Full speaking profile |
| **M3 Listening** | A11–A14, audio generation and degradation scripts, dictation scoring, adaptive noise test | Phone penalty and genre-specific listening |
| **M4 Reading / Writing / Vocab** | B1–B9, keystroke logger, adaptive vocabulary test | Complete battery |
| **M5 Dashboard + report** | Scales, confidence intervals, trends, drill-down, bilingual report, JSON export | Usable monthly |
| **M6 Calibration** | Native-anchor sessions, a test-retest pilot (take it twice within a week to measure noise), optional external test mapping | Scores you can trust |

M1 is deliberately early: it measures her most important problem, speaking fluency, before
everything else is built.

**Rough running cost per assessment:** well under a few dollars in API usage (speech recognition
for about 20 minutes of audio, pronunciation scoring, and a few dozen Claude calls). It is less if
Whisper, MFA and the phoneme model run locally on a GPU.

---

## 8. Tool 2 — Trainer (preview only; designed after Tool 1 is working)

**Inputs:**
- The Assessment JSON history.
- A **resource inventory:**
  - Books and PDFs, audio files and courses (with syllabi), which are ingested, transcribed where
    needed, and profiled by level and vocabulary.
  - **People:** you, friends, classmates, church contacts, with availability and what each is good
    for (casual chat, professional role-play, medical vocabulary).

**Evidence-based methods matched to likely weaknesses:**
- **Speaking overload and confidence:**
  - Learn **fixed chunks and phrases** for target situations, so that sentences are retrieved whole
    rather than assembled word by word. This is the most direct fix for overload.
  - **4/3/2 technique** (tell the same story in 4, then 3, then 2 minutes).
  - Task repetition, with planning time gradually reduced.
  - Shadowing.
  - Rehearsed phone and doctor role-plays with an AI voice partner, then with real people.
- **Pronunciation and phone listening:**
  - High-variability phonetic training on the contrasts she confuses.
  - Dictation on phone-band audio, and speed ramps.
  - Narrow listening: many sermons from the same speaker, with transcripts.
- **Vocabulary:**
  - FSRS spaced repetition, with words drawn from *her own* resources and prioritized by frequency
    and gap.
  - Medical terms taught through word parts (cardi-, -itis, -ectomy …), which pays off for
    illustration work too.
- **Colleague-level talk:** idioms, puns and implied meaning, practised on real examples. You can
  record short clips of your own conversations (with colleagues' consent) as material.
- **Human scheduler:** short structured "missions" for you and friends. For example: "10 minutes:
  she describes a recent appointment, you ask 3 follow-up questions, and note any word she was
  missing."
- **The loop:** each monthly assessment re-ranks the priorities, and the plan adapts.

---

## 9. Open questions (answers change the build)

1. **Server:** OS, Docker available? **GPU?** A GPU means WhisperX, MFA and the phoneme model run
   locally (cheaper and more private); without one we lean on Deepgram and Azure.
2. **Paid APIs OK?** Deepgram, Azure Speech (pronunciation assessment) and Anthropic.
3. **Device:** laptop plus a USB headset microphone is strongly recommended, for consistent audio
   and for typing tasks. Will she also want to use her phone?
4. **Hosting:** Cloudflare Pages + Access, or serve everything from your server through the tunnel?
   Which domain or subdomain?
5. **Native anchor:** are you and 1–2 friends willing to take the battery once (about 90 min)?
6. **Length:** is 2 × ~45 min per month acceptable, or should it be shorter (with wider
   confidence bands)?
7. **Transcript review:** are you willing to do the ~5–10 min review per session, or should it be
   fully automatic (less exact)?
8. **Content:** church sermon recordings we could use? Any course materials she is using now?
9. **External calibration test:** one-time Versant or Duolingo English Test — yes or no?
