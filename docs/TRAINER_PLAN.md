# Ehnglish Trainer — Plan (Tool 2)

Status: **design, nothing built.** Depends on the Assessment (Tool 1, built through M5) producing
`assessment_result.v1.json` exports. Decisions inherited from the Assessment plan (§0 there) are not
reopened: same learner, same server, same login, bilingual, Claude for judgment only, deterministic
code for numbers, everything versioned.

The Trainer's job is the one the Assessment deliberately refuses: **decide what she should practise
this week, make the practice, run it, and check whether it moved the needle.**

---

## 0. Decisions proposed here (confirm before T0)

| Topic | Proposal |
|---|---|
| Where it lives | Same monorepo, new `trainer/` (web + server), its own Postgres database, same Docker host, published as `train.bo-bob.com` behind the same Cloudflare Access app. Scoring code (`server/app/pipeline`) is shared as a package, not copied. |
| Separation from the test | **Firewall.** Trainer items may never be Assessment items. Assessment forms are listed in a blocklist the Trainer's content generator checks; the Trainer never shows sentence-repetition sentences, dictation sentences, C-texts, AXB pairs or phone scripts that appear in any `content/forms/*.yaml`. Otherwise the monthly test measures memorisation of the test. |
| Feedback | Yes, here. Immediate, specific, bilingual, tied to a named Assessment metric. Still no motivational theatre: no streaks, no badges, no "great job". |
| Daily budget | Default 20 minutes on weekdays, one 40-minute session at the weekend with the husband. Adjustable; the planner fills whatever budget it is given. |
| Live AI partner | Allowed **in training** (the Assessment forbids it for standardisation). A simulated receptionist / pharmacist / colleague for role-play, built from TTS + STT + Claude, with the same phone-line audio effect. |
| Her materials | Course syllabus, textbook chapters, class handouts are inputs: uploaded as PDF/photos, OCR'd, and used as a vocabulary and topic source for drills. Not used for scoring anything. |
| LLM | `claude-opus-5-5` for drill generation and explanations; a cheaper model is acceptable for bulk generation if the owner wants (not a quality-critical judgment). |

---

## 1. What the Assessment hands over

Per sitting, `assessment_result.v1.json` contains every metric with a CI, the item-level
responses, and the session rollups. The Trainer reads these through the Assessment API
(`GET /api/sessions/{id}/export`, owner or learner token) and keeps a local copy.

The signals the planner uses, grouped by what they say about her:

| Signal (metric ids) | What it means for practice |
|---|---|
| `ei_pct_syllables`, `ei_longest` | Real-time chunking capacity: how long a sentence she can hold and reproduce. Low → fluency and working-memory drills (shadowing, elicited imitation with length ramps). |
| `response_latency_ms` | Retrieval speed. High → rapid-retrieval drills on formulaic phrases, timed quick answers. |
| `speech_rate`, `articulation_rate`, `mean_length_of_run`, `pauses_per_min`, `fillers_per_100` | Fluency profile. Short runs with many pauses → task repetition (4/3/2), chunk rehearsal. |
| `errors_per_100`, `error_free_clauses_pct`, ERRANT `by_type` | Accuracy, by error type (articles, prepositions, tense, agreement…). → targeted form-focused drills on the top two error types only. |
| `subordination_ratio`, `mean_clause_len`, `mtld`, `beyond_2k_pct` | Complexity and lexical range. → sentence combining, upgrade-the-word drills. |
| `pron_accuracy`, `contrast_errors_per_100`, phoneme confusions, `axb_pct` by contrast | Which contrasts she cannot hear vs cannot produce. Perception-first: AXB high-variability training on the weak contrast, then production with pronunciation feedback. |
| `wer_clear/fast/phone/noise`, `phone_penalty`, `noise_penalty` | Listening under degradation. → adaptive degraded-audio dictation (phone line, babble at adaptive SNR). |
| `comp_conversation`, `comp_lecture`, `retell_units` | Comprehension by genre. → genre-specific listening with retell. |
| `phone_goal_completion`, `phone_phrases_pct` | Transactional competence. → scripted and then live role-plays. |
| `vocab_size`, `by_band`, `vocab_medical_pct`, `lextale` | Size and domain coverage. → spaced repetition fed by the bands with the lowest hit rate and by the patient-side list. |
| `email_goal_completion`, `email_errors_per_100` | Functional writing. → email drills with checklists. |
| `confidence`, `anxiety`, `cando` | Which situations she avoids. → role-play topics follow the lowest confidence items. |
| Quality panel, `retest_noise` | Which changes are real. The planner **never reacts to a change the Assessment labels "no detectable change"**. |

---

## 2. Design principles

1. **Practise the measured gap, not the syllabus.** Every drill is tagged with the Assessment metric it targets. If a metric is not weak, the Trainer does not spend time on it.
2. **Evidence-based drill families only.** Each family below cites the effect it relies on. No drill is included because it is fun to build.
3. **Retrieval and spacing before exposure.** Reviews are scheduled with FSRS (a modern spaced-repetition scheduler); new material is introduced only when the review queue is under control.
4. **Perception before production** for pronunciation: she must hear a contrast before being asked to produce it.
5. **Task repetition with shrinking time** for fluency (the 4/3/2 technique): the same monologue three times, 4, 3 and 2 minutes.
6. **Code scores, Claude explains.** Scoring reuses the Assessment pipeline (EI syllable credit, WER, Praat timing, pronunciation assessment, ERRANT). Claude writes the one-paragraph bilingual explanation and generates drill content to a spec; it never decides a score.
7. **Closed loop.** The monthly Assessment is the only judge of whether training works. The Trainer reports, per metric it targeted, what it predicted and what happened.

---

## 3. Drill families

| Family | Targets | What she does | Scored by | Evidence |
|---|---|---|---|---|
| **SRS vocabulary** | `vocab_*`, `beyond_2k_pct`, medical coverage, her course vocabulary | Cards with the word in a patient-side or course context; recall the word from a definition/gap, then say it aloud; cards come from Assessment misses, weak bands, her materials, and words she looked up | Exact/fuzzy match; pronunciation accuracy on the spoken half | Spaced retrieval practice (Cepeda et al. 2006; Karpicke & Roediger 2008); FSRS scheduling |
| **Shadowing** | `speech_rate`, `mean_length_of_run`, prosody | Listen-and-repeat simultaneously with a 30–60 s clip (TTS or husband-recorded), then alone from memory | Praat rate/pauses vs the model; `pron_prosody` | Shadowing improves fluency and prosody in L2 (Hamada 2016; Foote & McDonough 2017) |
| **EI ladder** | `ei_pct_syllables`, `ei_longest` | Sentence repetition that ramps length around her current ceiling (±2 syllables); non-test sentences | Syllable credit (shared scorer) | Elicited imitation tracks implicit knowledge and improves with practice (Yan et al. 2016) |
| **Rapid retrieval** | `response_latency_ms`, `phone_phrases_pct` | Timed cue → fixed phrase ("I'd like to reschedule…"), 3 s window, dozens per session | Onset latency, exact phrase | Formulaic sequences lower processing load (Wray; Boers et al. 2006) |
| **4/3/2** | `speech_rate`, `pauses_per_min`, `fillers_per_100` | Same topic three times with shrinking time; topics from her life and medical illustration | Praat fluency across the three runs | Task repetition with time pressure (Nation 1989; de Jong & Perfetti 2011) |
| **Form focus** | top two ERRANT error types | Short rule in both languages, then 10 transformation/gap items, then produce 3 sentences aloud using it | ERRANT on the minimal correction | Focus on form within meaning (Ellis; Norris & Ortega 2000) |
| **Sentence combining** | `subordination_ratio`, `mean_clause_len` | Combine 2–3 simple sentences into one; speak it | spaCy clause analysis | Sentence combining improves syntactic complexity (Graham & Perin 2007) |
| **HVPT perception** | `axb_pct` by contrast, `contrast_errors` | AXB / identification on the weakest contrast, many voices (TTS voices + husband), feedback per trial, adaptive difficulty | Accuracy by contrast | High-variability phonetic training transfers to production (Bradlow et al. 1997; Thomson 2018) |
| **Production with feedback** | `pron_accuracy`, phoneme confusions | Minimal pairs and target words, immediate per-phoneme score, replay her take vs model | Azure pronunciation assessment + phoneme recognizer | Immediate feedback on pronunciation (Thomson & Derwing 2015) |
| **Degraded dictation** | `wer_phone`, `wer_noise`, `wer_fast` | Dictation with phone line / babble at an SNR that keeps her near 80 % correct; sentences from her domain | WER (shared scorer) | Adaptive difficulty keeps training in the zone that transfers (Van Engen & Bradlow 2007 on noise training) |
| **Listening deep-dive** | `comp_*`, `retell_units` | Weekly 2–3 minute clip (sermon from the church app, podcast, lecture): listen once, retell, answer, then read the transcript and listen again | Idea-unit coverage; comprehension | Retell + transcript-supported relistening (Vandergrift & Goh 2012) |
| **Role-play (scripted)** | `phone_goal_completion` | Same structure as the test's phone task but with new scenarios; goals on screen | Checklist (Claude judge, 3 runs) | Transactional task rehearsal |
| **Role-play (live)** | `phone_goal_completion`, `confidence` | A simulated receptionist/pharmacist/colleague improvises within a scenario; phone-line audio; 5–8 turns; afterwards a bilingual debrief | Checklist + latency per turn | Interaction with feedback (Long's interaction hypothesis; Mackey & Goo 2007) |
| **Email drill** | `email_goal_completion`, `email_errors_per_100` | Write to a brief with a checklist; then compare with a model email | Checklist + ERRANT | Genre-based writing with models (Hyland) |
| **Husband session** | everything spoken | A weekly 30–40 min script the app prepares: a role-play, a 4/3/2 topic, five minimal pairs to say back to her, and the week's five vocabulary items in conversation | Not scored; logged | Interlocutor practice, no measurement pressure |

---

## 4. The planner

Every day the planner composes one session from the budget:

```
warm-up   5 min   SRS reviews due today (always first)
focus    10 min   one drill from the highest-priority family
routine   5 min   a fluency routine (shadowing, 4/3/2 or EI ladder), rotating
```

Priority of a family, recomputed after every Assessment sitting and nudged by daily practice:

```
priority = gap × goal_weight × expected_gain_per_minute × staleness
```

- `gap`: distance of the metric from the native anchor (the Assessment's 0–100 scale), or from an
  absolute target when there is no anchor yet. Only metrics whose latest change is **not** inside the
  test–retest noise count as moved.
- `goal_weight`: from her goals — TOEFL/IELTS sections she needs, patient-side situations, medical
  illustration vocabulary — set once in a short questionnaire, editable.
- `expected_gain_per_minute`: a prior per family (perception and SRS move fast; complexity moves
  slowly), updated from her own history once there are two Assessment sittings.
- `staleness`: a family not practised for a week gets a boost; a family practised daily for two
  weeks without Assessment movement gets a cut (the planner must not chase its tail).

Within a family, **difficulty is adaptive**: the EI ladder sits at her ceiling ±2 syllables, the
degraded dictation picks the SNR that keeps her near 80 % correct, HVPT advances to a new voice when
she clears 90 %. Interleaving: never the same family two days running unless it is the only gap.

Weekly, the planner writes a one-screen bilingual plan: "This week: r/l perception (AXB 71 % last
month), long-sentence repetition (ceiling 15 syllables), phone-line dictation (WER 28 %). Not this
week: vocabulary (size 6,100, at anchor)."

---

## 5. Content generation (with the firewall)

- Drill content is generated by Claude **to a spec** (syllable range, target structure, contrast,
  domain, CEFR band) from a short catalogue of topics: patient-side situations, her course topics
  (from uploaded materials), medical illustration, church/community life, colleague talk.
- Every generated item is checked by code before use: syllable count, presence of the target
  phoneme/structure, word-frequency band, length — the same validators the Assessment uses.
- **Firewall check:** no generated sentence may match (normalised, ≥ 85 % similarity) any item in the
  Assessment forms, and no Assessment prompt audio is reused. Violations are discarded and logged.
- Audio: TTS with several voices for HVPT (variety is the point); husband-recorded clips when he
  has time; sermon/podcast clips through the same importer as the Assessment.
- Her materials: PDFs and photos are OCR'd (the receipt-ledger project's Google Vision setup can
  be reused), chunked, and used as a retrieval source for vocabulary and topic prompts. Nothing
  from them is graded.

---

## 6. Feedback and the loop

- After every drill: the number that was measured, in context ("12 of 15 syllables; your ceiling is
  15"), one sentence on what to change, in English and Korean. For pronunciation, her take and the
  model side by side with the mismatched phoneme marked.
- Weekly: what was practised, minutes per family, within-Trainer movement (clearly labelled as
  *practice* numbers, not test numbers).
- Monthly, after the Assessment sitting: a **prediction scorecard**. For each metric the Trainer
  targeted it had written down the expected direction; it now shows what the Assessment measured and
  whether the change was detectable. This is how we find out which families work for her, and the
  `expected_gain_per_minute` priors update from it.

---

## 7. Architecture

```
 Browser (PWA, bilingual)                       Same host, Cloudflare Tunnel + Access
 ┌────────────────────────────┐    HTTPS   ┌──────────────────────────────────────────┐
 │ Today / Week / Review      │──────────▶│ trainer-api (FastAPI) + trainer-db       │
 │ Drill runners (reuse the   │           │ planner · FSRS scheduler · content gen   │
 │ Assessment recorder,       │           │ firewall · materials ingest (OCR/RAG)    │
 │ upload queue, task runner) │           │ scoring via shared `ehnglish-pipeline`   │
 │ Live role-play (WebRTC-ish │           │ live partner: STT stream → Claude → TTS  │
 │ turn-taking, not duplex)   │           │ Assessment client (exports, forms list)  │
 └────────────────────────────┘           └──────────────────────────────────────────┘
```

- **Shared code:** `server/app/pipeline` becomes an installable package (`ehnglish-pipeline`) used
  by both apps; the Assessment's `content.py` validators and `audiofx` too. The web recorder, upload
  queue and runner machine move to a shared `web/packages/runner`.
- **Data:** separate database (`trainer`), tables for cards (FSRS state), drills, attempts with
  results, plans, predictions, materials. Raw audio kept, same policy as the Assessment.
- **Live partner:** turn-based, not full duplex: she speaks (VAD end-pointing), STT, Claude replies
  in character with the scenario's hidden goals, TTS through the phone-line effect. Latency target
  under 2 s per turn. Transcript and latencies logged like a phone task.
- **Costs:** same ledger; the live partner is the expensive drill (a 6-turn call ≈ 6 Claude calls +
  STT + TTS); budget shown to the owner only.

---

## 8. Milestones

| Milestone | Scope |
|---|---|
| **T0 Skeleton** | `trainer/` app, shared pipeline package, Assessment client pulling exports, planner v1 (priorities from the last sitting, daily session composer), SRS with FSRS, bilingual Today screen. Firewall in place from day one. |
| **T1 Sound** | HVPT perception drills with multi-voice TTS, production drills with pronunciation feedback and side-by-side replay. |
| **T2 Fluency** | Shadowing, EI ladder, rapid retrieval, 4/3/2 — all reusing the Assessment recorder and scorers. |
| **T3 Listening** | Adaptive degraded dictation, weekly listening deep-dive with retell and transcript relisten, sermon/podcast importer. |
| **T4 Talk and write** | Scripted role-plays, live simulated partner, email drills, the husband-session script generator. |
| **T5 Materials and goals** | Course material ingest (OCR + retrieval), goal questionnaire feeding `goal_weight`, form-focus and sentence-combining drills driven by her ERRANT profile. |
| **T6 Loop** | Prediction scorecard after each Assessment, prior updates, weekly plan page; first full month of use. |

Rough running cost: $5–15 per month, dominated by the live partner and Claude-generated content.

---

## 9. Risks and how the design handles them

- **Teaching to the test.** The firewall, and families that target the underlying skill rather than
  the test format (e.g. HVPT with many voices, not AXB with the test's voice).
- **Chasing noise.** The planner only reacts to detectable changes; practice numbers never override
  Assessment numbers.
- **Over-planning for a tired learner.** The budget is hers; a day with zero minutes is a day, not a
  failure, and the planner just re-fills tomorrow. No streaks.
- **Content quality.** Code validators on every generated item; a weekly batch of 20 items for the
  husband to skim; items with repeated confusion are retired automatically.
- **Live partner going off-script.** Scenario goals and a persona are fixed; the partner's replies are
  checked for staying in role and in CEFR range before being spoken; a "repeat / slower" button is
  always available.

---

## 10. Open questions for the owner

1. Daily minutes on weekdays, and whether the weekend husband session is realistic.
2. Which of her materials exist in digital form (course PDFs, textbook).
3. Whether she wants the live simulated partner at all, or scripted role-plays only.
4. Device for daily practice (iPad with headset, or the laptop with the Yeti).
5. Whether to start T0 now, in parallel with M6 calibration, or after her first two sittings.
