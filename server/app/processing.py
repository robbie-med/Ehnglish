"""M1 processing orchestration: one `process_take` job walks the steps for the take's task type.

Each step writes a ProcessingResult row (kind + pipeline_version) and is skipped on re-run when a
row for the current version already exists, so a retried job resumes where it failed. Raw files
are never modified. Engines that are not configured are skipped and recorded as such.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .content import Form, Item, Task, get_forms
from .engines import azure, deepgram, google, mfa, whisper
from .engines import phonemes as phoneme_engine
from .engines.base import EngineError, Transcript
from .engines.claude import minimal_correction
from .models import ProcessingResult, SessionResult, Take, TestSession
from .pipeline import (
    checklist,
    dictation,
    ei,
    ideas,
    items,
    lexical,
    lextale,
    phonemes,
    praat,
    rhythm,
    syntax,
    typing,
    vote,
)
from .pipeline.text import normalize

log = logging.getLogger("processing")


class Ctx:
    def __init__(self, db: Session, take: Take, job_id: uuid.UUID | None):
        self.db = db
        self.take = take
        self.job_id = job_id
        self.settings = get_settings()
        self.path: Path = self.settings.raw_dir / (take.wav_path or "")
        session = db.get(TestSession, take.session_id)
        assert session is not None
        self.form: Form = get_forms(str(self.settings.content_dir))[session.form_id]
        self.task: Task = next(t for t in self.form.tasks if t.id == take.task_id)
        self.item: Item = next(i for i in self.task.items if i.id == take.item_id)
        self.language = "ko" if self.item.target.get("language") == "ko" else "en"

    # ------------------------------------------------------------------ result store
    def existing(self, kind: str) -> dict | None:
        row = self.db.scalar(
            select(ProcessingResult)
            .where(
                ProcessingResult.take_id == self.take.id,
                ProcessingResult.kind == kind,
                ProcessingResult.pipeline_version == self.settings.pipeline_version,
            )
            .order_by(ProcessingResult.created_at.desc())
        )
        return row.result if row else None

    def save(self, kind: str, result: dict) -> dict:
        self.db.add(
            ProcessingResult(
                take_id=self.take.id,
                job_id=self.job_id,
                kind=kind,
                pipeline_version=self.settings.pipeline_version,
                result=result,
            )
        )
        self.db.commit()
        return result

    def step(self, kind: str, fn: Callable[[], dict]) -> dict:
        got = self.existing(kind)
        if got is not None:
            return got
        return self.save(kind, fn())


# ---------------------------------------------------------------------- steps
ENGINES: dict[str, Callable[..., Transcript]] = {
    "deepgram": deepgram.transcribe,
    "azure": azure.transcribe,
    "whisper": whisper.transcribe,
    "google": google.transcribe,  # optional; skipped unless EHNGLISH_GOOGLE_CREDENTIALS is set
}


def step_asr(ctx: Ctx) -> dict[str, dict]:
    """Every configured engine; unconfigured ones are recorded as skipped."""
    out: dict[str, dict] = {}
    for name, fn in ENGINES.items():
        kind = f"asr:{name}"

        def run(fn=fn, name=name) -> dict:
            try:
                return fn(ctx.path, language=ctx.language).to_dict()
            except EngineError as e:
                if "not set" in str(e) or "not enabled" in str(e):
                    log.info("%s skipped: %s", name, e)
                    return {"engine": name, "skipped": True, "reason": str(e)}
                raise

        out[name] = ctx.step(kind, run)
    return out


def step_vote(ctx: Ctx, asr: dict[str, dict]) -> dict:
    def run() -> dict:
        engines: dict[str, list[vote.Word]] = {}
        for name in ("deepgram", "whisper", "azure", "google"):  # backbone first: most verbatim
            t = asr.get(name)
            if not t or t.get("skipped"):
                continue
            engines[name] = [
                vote.Word(w["word"], w.get("start"), w.get("end"), w.get("conf"))
                for w in t.get("words", [])
            ] or [vote.Word(w) for w in t.get("text", "").split()]
        r = vote.vote(engines)
        return {
            "text": r.text,
            "confident_text": r.confident_text,
            "agreement": r.agreement,
            "uncertain_share": r.uncertain_share,
            "n_engines": r.n_engines,
            "words": [
                {
                    "text": w.text,
                    "votes": w.votes,
                    "uncertain": w.uncertain,
                    "start": w.start,
                    "end": w.end,
                    "candidates": w.candidates,
                }
                for w in r.words
            ],
        }

    return ctx.step("transcript", run)


def step_timing(ctx: Ctx) -> dict:
    return ctx.step("timing", lambda: praat.analyze(ctx.path).to_dict())


def step_latency(ctx: Ctx, timing: dict) -> dict:
    def run() -> dict:
        events = {e.name: e.t_client_ms for e in ctx.take.events}
        prompt_to_record = None
        if "prompt_end" in events and "record_start" in events:
            prompt_to_record = round(events["record_start"] - events["prompt_end"], 1)
        onset = timing.get("onset_s")
        return {
            "onset_s": onset,
            "prompt_to_record_ms": prompt_to_record,
            "latency_ms": round(1000 * onset + (prompt_to_record or 0), 1)
            if onset is not None
            else None,
        }

    return ctx.step("latency", run)


def step_pron(ctx: Ctx) -> dict:
    def run() -> dict:
        try:
            return azure.pronunciation_assessment(ctx.path, ctx.item.text or "").to_dict()
        except EngineError as e:
            if "not set" in str(e):
                return {"skipped": True, "reason": str(e)}
            raise

    return ctx.step("pron", run)


def step_phonemes(ctx: Ctx) -> dict:
    """Phoneme recognizer vs the expected phones of the target text (read-aloud)."""

    def run() -> dict:
        try:
            ipa = phoneme_engine.recognize(ctx.path)
        except EngineError as e:
            if "not set" in str(e) or "not installed" in str(e):
                return {"skipped": True, "reason": str(e)}
            raise
        expected = phonemes.expected_ipa(ctx.item.text or "")
        rep = phonemes.compare(expected, phonemes.tokenize_ipa(ipa)).to_dict()
        rep["raw"] = ipa
        return rep

    return ctx.step("phonemes", run)


def step_alignment(ctx: Ctx, transcript: dict) -> dict:
    def run() -> dict:
        text = transcript.get("text", "")
        if not ctx.settings.mfa_url or not text:
            return {"skipped": True, "reason": "no MFA url or empty transcript"}
        res = mfa.align(ctx.path, text)
        if not res.get("unaligned") and res.get("phones"):
            res["rhythm"] = rhythm.analyze(
                [(p["phone"], p["start"], p["end"]) for p in res["phones"]]
            ).to_dict()
        return res

    return ctx.step("alignment", run)


def step_ei(ctx: Ctx, transcript: dict) -> dict:
    def run() -> dict:
        s = ei.score_repetition(ctx.item.text or "", transcript.get("text", ""))
        return {
            "target_words": s.target_words,
            "target_syllables": s.target_syllables,
            "words_correct": s.words_correct,
            "syllables_correct": s.syllables_correct,
            "pct_syllables": s.pct_syllables,
            "exact": s.exact,
            "alignment": [{"target": a, "response": b, "credit": c} for a, b, c in s.alignment],
        }

    return ctx.step("ei", run)


def step_language(ctx: Ctx, transcript: dict) -> dict:
    """Lexical + syntactic complexity on the confident transcript; accuracy via Claude + ERRANT."""
    confident = transcript.get("confident_text", "")
    lex = ctx.step(
        "lexical", lambda: lexical.analyze(normalize(confident, drop_fillers=False)).to_dict()
    )
    syn = ctx.step(
        "syntax",
        lambda: (
            syntax.analyze(confident).to_dict()
            if confident
            else syntax.SyntaxReport(0, 0, 0, 0, None, None, None, None, None).to_dict()
        ),
    )

    def correction() -> dict:
        if not confident:
            return {"skipped": True, "reason": "empty transcript"}
        marked = " ".join(
            ("[uncertain] " + w["text"]) if w["uncertain"] else w["text"]
            for w in transcript.get("words", [])
        )
        try:
            return minimal_correction(marked).to_dict()
        except EngineError as e:
            if "not set" in str(e):
                return {"skipped": True, "reason": str(e)}
            raise

    corr = ctx.step("correction", correction)

    def errors() -> dict:
        if corr.get("skipped"):
            return {"skipped": True, "reason": corr.get("reason")}
        clean = corr["corrected"].replace("[uncertain] ", "")
        return syntax.classify_errors(transcript.get("text", ""), clean).to_dict()

    err = ctx.step("errors", errors)
    return {"lexical": lex, "syntax": syn, "correction": corr, "errors": err}


def step_language_text(ctx: Ctx, text: str) -> dict:
    """Language metrics on a typed text (dictation excluded): same steps as speech, no voting."""
    transcript = {
        "text": text,
        "confident_text": text,
        "words": [{"text": w, "uncertain": False} for w in text.split()],
    }
    return step_language(ctx, transcript)


def step_dictation(ctx: Ctx) -> dict:
    typed = ctx.take.typed.text if ctx.take.typed else ""
    cond = str(ctx.item.target.get("condition", "clear"))
    return ctx.step("wer", lambda: dictation.score(ctx.item.text or "", typed, cond).to_dict())


def _phone_turns(ctx: Ctx) -> list[dict]:
    """Caller line + learner transcript for every turn of this task in the session, in item order.
    Learner text comes from each take's voted transcript (current pipeline version)."""
    takes = ctx.db.scalars(
        select(Take)
        .where(
            Take.session_id == ctx.take.session_id,
            Take.task_id == ctx.task.id,
            Take.status != "rejected",
        )
        .options(selectinload(Take.results))
        .execution_options(populate_existing=True)
    ).all()
    by_item: dict[str, Take] = {}
    for t in takes:
        prev = by_item.get(t.item_id)
        if prev is None or t.attempt > prev.attempt:
            by_item[t.item_id] = t
    turns = []
    for it in ctx.task.items:
        t = by_item.get(it.id)
        learner = ""
        if t is not None:
            rows = [
                r
                for r in t.results
                if r.kind == "transcript" and r.pipeline_version == ctx.settings.pipeline_version
            ]
            if rows:
                words = rows[-1].result.get("words", [])
                learner = " ".join(
                    ("[uncertain] " + w["text"]) if w.get("uncertain") else w["text"] for w in words
                )
        turns.append({"item": it.id, "caller": it.text or "", "learner": learner})
    return turns


def step_phone(ctx: Ctx, transcript: dict) -> dict:
    """Fixed phrases for this turn (code) and the goal checklist over all turns so far (Claude).
    The checklist on the last turn is the one that counts; earlier ones show progress."""
    phrases = list(ctx.task.target.get("phrases", [])) + list(ctx.item.target.get("phrases", []))
    ctx.step("phrases", lambda: checklist.phrase_use(phrases, transcript.get("text", "")))

    def goals() -> dict:
        turns = _phone_turns(ctx)
        try:
            res = checklist.score_goals(list(ctx.task.target.get("goals", [])), turns).to_dict()
        except EngineError as e:
            if "not set" in str(e):
                return {"skipped": True, "reason": str(e), "turns": turns}
            raise
        res["turns"] = turns
        res["is_last_turn"] = ctx.item.id == ctx.task.items[-1].id
        return res

    return ctx.step("checklist", goals)


def step_lexical_decision(ctx: Ctx) -> dict:
    def run() -> dict:
        answer = (ctx.take.typed.text if ctx.take.typed else "").strip().lower() or None
        events = {e.name: e.t_client_ms for e in ctx.take.events}
        shown = events.get("prompt_end", events.get("item_shown"))
        answered = events.get("answer")
        rt = round(answered - shown, 1) if shown is not None and answered is not None else None
        is_word = bool(ctx.item.target.get("is_word"))
        return {
            "item": ctx.item.text,
            "is_word": is_word,
            "answer": answer,
            "correct": (answer == "yes") == is_word if answer in ("yes", "no") else None,
            "rt_ms": rt,
            "practice": bool(ctx.item.target.get("practice")),
        }

    return ctx.step("lexical_decision", run)


def _keystrokes(ctx: Ctx) -> list[dict]:
    rel = ctx.take.typed.keystroke_log_path if ctx.take.typed else None
    if not rel:
        return []
    path = ctx.settings.raw_dir / rel
    if not path.exists():
        return []
    import json

    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def step_typing(ctx: Ctx, reference: str | None) -> dict:
    text = ctx.take.typed.text if ctx.take.typed else ""
    return ctx.step("typing", lambda: typing.analyze(_keystrokes(ctx), text, reference).to_dict())


def step_ideas(ctx: Ctx, transcript: dict) -> dict:
    """Idea units of this take; for a paired retelling, coverage of the source take's units."""

    def extract() -> dict:
        text = transcript.get("text", "")
        if not text:
            return {"skipped": True, "reason": "empty transcript"}
        try:
            return ideas.extract(text, ctx.language).to_dict()
        except EngineError as e:
            if "not set" in str(e):
                return {"skipped": True, "reason": str(e)}
            raise

    mine = ctx.step("ideas", extract)
    pair = ctx.item.target.get("pairs_with")
    if not pair:
        return mine

    def gap() -> dict:
        source = ctx.db.scalar(
            select(Take)
            .where(
                Take.session_id == ctx.take.session_id,
                Take.item_id == pair,
                Take.status != "rejected",
            )
            .order_by(Take.attempt.desc())
            .options(selectinload(Take.results))
            .execution_options(populate_existing=True)
        )
        if source is None:
            return {"skipped": True, "reason": f"source take {pair} not found"}
        res = {
            r.kind: r.result
            for r in source.results
            if r.pipeline_version == ctx.settings.pipeline_version
        }
        src_ideas = res.get("ideas")
        if src_ideas is None:
            return {"skipped": True, "reason": "source not processed yet", "retry": True}
        if src_ideas.get("skipped"):
            return {"skipped": True, "reason": f"source ideas skipped: {src_ideas.get('reason')}"}
        try:
            cov = ideas.coverage(src_ideas["units"], transcript.get("text", "")).to_dict()
        except EngineError as e:
            if "not set" in str(e):
                return {"skipped": True, "reason": str(e)}
            raise
        my_t = ctx.existing("timing") or {}
        src_t = res.get("timing") or {}
        ratio = None
        if my_t.get("speech_rate_syl_per_s") and src_t.get("speech_rate_syl_per_s"):
            ratio = round(my_t["speech_rate_syl_per_s"] / src_t["speech_rate_syl_per_s"], 3)
        cov.update(
            {
                "source_item": pair,
                "source_take": str(source.id),
                "speech_rate_ratio": ratio,
                "source_units": src_ideas["units"],
            }
        )
        return cov

    out = ctx.step("expression_gap", gap)
    if out.get("retry"):
        # Source not processed yet (jobs run in parallel): let the queue retry this take later.
        ctx.db.execute(
            ProcessingResult.__table__.delete().where(
                ProcessingResult.take_id == ctx.take.id,
                ProcessingResult.kind == "expression_gap",
                ProcessingResult.pipeline_version == ctx.settings.pipeline_version,
            )
        )
        ctx.db.commit()
        raise RuntimeError(f"waiting for source take {pair} to be processed")
    return out


def step_mc(ctx: Ctx) -> dict:
    def run() -> dict:
        r = items.score_mc(
            ctx.take.typed.text if ctx.take.typed else None,
            int(ctx.item.target["answer"]),
            ctx.item.options or [],
        )
        r["band"] = ctx.item.target.get("band")
        r["genre"] = ctx.task.target.get("genre")
        events = {e.name: e.t_client_ms for e in ctx.take.events}
        if "prompt_end" in events and "submit" in events:
            r["rt_ms"] = round(events["submit"] - events["prompt_end"], 1)
        return r

    return ctx.step("mc", run)


def step_reading(ctx: Ctx) -> dict:
    def run() -> dict:
        events = {e.name: e.t_client_ms for e in ctx.take.events}
        return items.reading_speed(
            ctx.item.text or "",
            events.get("prompt_end", events.get("item_shown")),
            events.get("submit"),
        ).to_dict()

    return ctx.step("reading", run)


def step_ctest(ctx: Ctx) -> dict:
    def run() -> dict:
        raw = ctx.take.typed.text if ctx.take.typed else ""
        answers = raw.split("\u241f") if raw else []  # ␟ unit separator between blanks
        return items.score_ctest(ctx.item.text or "", answers)

    return ctx.step("ctest", run)


def step_axb(ctx: Ctx) -> dict:
    def run() -> dict:
        r = items.score_axb(
            ctx.take.typed.text if ctx.take.typed else None,
            str(ctx.item.target["answer"]),
            ctx.item.target.get("contrast"),
        )
        events = {e.name: e.t_client_ms for e in ctx.take.events}
        if "prompt_end" in events and "answer" in events:
            r["rt_ms"] = round(events["answer"] - events["prompt_end"], 1)
        return r

    return ctx.step("axb", run)


def step_email_checklist(ctx: Ctx, text: str) -> dict:
    """R4 functional email: goal checklist over the written text (same judge as the phone call)."""

    def run() -> dict:
        goals = list(ctx.task.target.get("goals", [])) + list(ctx.item.target.get("goals", []))
        if not goals:
            return {"skipped": True, "reason": "no goals defined"}
        try:
            return checklist.score_goals(
                goals, [{"caller": ctx.item.prompt.en if ctx.item.prompt else "", "learner": text}]
            ).to_dict()
        except EngineError as e:
            if "not set" in str(e):
                return {"skipped": True, "reason": str(e)}
            raise

    return ctx.step("checklist", run)


# ---------------------------------------------------------------------- per task type
def process_take(db: Session, take: Take, job_id: uuid.UUID | None = None) -> str:
    ctx = Ctx(db, take, job_id)
    t = ctx.task.type
    if take.kind == "typed":
        if t == "dictation":
            step_dictation(ctx)
            return "dictation done"
        if t == "lexical_decision":
            step_lexical_decision(ctx)
            return "lexical_decision done"
        if t == "copy_typing":
            step_typing(ctx, ctx.item.text)
            return "copy_typing done"
        if t == "typed_response":
            text = ctx.take.typed.text if ctx.take.typed else ""
            step_typing(ctx, None)
            if ctx.language == "en":
                step_language_text(ctx, text)
                if ctx.task.target.get("goals") or ctx.item.target.get("goals"):
                    step_email_checklist(ctx, text)
            return "typed_response done"
        if t == "multiple_choice":
            step_mc(ctx)
            return "multiple_choice done"
        if t == "reading_passage":
            step_reading(ctx)
            return "reading_passage done"
        if t == "c_test":
            step_ctest(ctx)
            return "c_test done"
        if t == "axb":
            step_axb(ctx)
            return "axb done"
        return f"no processing for typed {t}"
    if t == "silence":
        return "silence: wav_probe only"
    if t == "read_aloud":
        asr = step_asr(ctx)
        tr = step_vote(ctx, asr)
        step_timing(ctx)
        step_pron(ctx)
        step_phonemes(ctx)
        step_alignment(ctx, tr)
        return "read_aloud done"
    if t == "sentence_repeat":
        asr = step_asr(ctx)
        tr = step_vote(ctx, asr)
        timing = step_timing(ctx)
        step_latency(ctx, timing)
        step_ei(ctx, tr)
        return "sentence_repeat done"
    if t == "quick_answer":
        asr = step_asr(ctx)
        tr = step_vote(ctx, asr)
        timing = step_timing(ctx)
        step_latency(ctx, timing)
        step_language(ctx, tr)
        return "quick_answer done"
    if t == "phone_call":
        asr = step_asr(ctx)
        tr = step_vote(ctx, asr)
        timing = step_timing(ctx)
        step_latency(ctx, timing)
        step_language(ctx, tr)
        step_phone(ctx, tr)
        return "phone_call turn done"
    if t == "describe_opinion":
        asr = step_asr(ctx)
        tr = step_vote(ctx, asr)
        step_timing(ctx)
        if ctx.language == "en":
            step_alignment(ctx, tr)
            step_language(ctx, tr)
        if ctx.form.kind == "baseline" or ctx.item.target.get("stage") == "retell":
            step_ideas(ctx, tr)
        return "describe_opinion done"
    return f"no processing for {t}"


# ---------------------------------------------------------------------- session level
def _take_results(db: Session, session: TestSession, version: str) -> list[tuple[Take, dict]]:
    takes = db.scalars(
        select(Take)
        .where(Take.session_id == session.id, Take.status != "rejected")
        .options(selectinload(Take.results), selectinload(Take.typed))
        .execution_options(populate_existing=True)
    ).all()
    return [
        (t, {r.kind: r.result for r in t.results if r.pipeline_version == version}) for t in takes
    ]


def items_map_stage(
    items_mod: object, item_id: str
) -> str | None:  # pragma: no cover - tiny helper
    return _STAGE.get(item_id)


_STAGE: dict[str, str | None] = {}


def summarize_session(db: Session, session: TestSession, job_id: uuid.UUID | None = None) -> dict:
    """Cross-take summaries. Written as session_results rows, one per kind, idempotent per version."""
    settings = get_settings()
    form = get_forms(str(settings.content_dir))[session.form_id]
    tasks = {t.id: t for t in form.tasks}
    items_by_id = {i.id: (t, i) for t in form.tasks for i in t.items}
    _STAGE.clear()
    _STAGE.update({i.id: i.target.get("stage") for t in form.tasks for i in t.items})
    rows = _take_results(db, session, settings.pipeline_version)
    out: dict[str, dict] = {}

    # dictation
    wers = [dictation.WerReport(**r["wer"]) for _, r in rows if "wer" in r]
    if wers:
        out["dictation"] = dictation.condition_summary(wers)
    # LexTALE
    lex = [r["lexical_decision"] for _, r in rows if "lexical_decision" in r]
    if lex:
        out["lextale"] = lextale.score(lex).to_dict()
    # typing baselines, per language
    for t, r in rows:
        if "typing" in r and t.task_id in tasks and tasks[t.task_id].type == "copy_typing":
            lang = items_by_id[t.item_id][1].target.get("language", "en")
            out.setdefault("typing", {})[lang] = r["typing"]
    # ratings by scale name (reverse-keyed items flipped)
    scales: dict[str, dict] = {}
    for t, _r in rows:
        if (
            t.item_id not in items_by_id
            or items_by_id[t.item_id][0].type != "rating"
            or not t.typed
        ):
            continue
        task, item = items_by_id[t.item_id]
        try:
            v = float(t.typed.text)
        except ValueError:
            continue
        name = str(item.target.get("scale_name", task.id))
        if item.target.get("reverse") and item.scale:
            v = item.scale.max + item.scale.min - v
        scales.setdefault(name, {"items": {}, "mean": None})["items"][item.id] = v
    for sc in scales.values():
        vals = list(sc["items"].values())
        sc["mean"] = round(sum(vals) / len(vals), 2) if vals else None
    if scales:
        out["ratings"] = scales
    # phone call: the last turn's checklist
    for _t, r in rows:
        if "checklist" in r and r["checklist"].get("is_last_turn"):
            out["phone_call"] = {k: v for k, v in r["checklist"].items() if k != "turns"}
    # expression gap
    for _t, r in rows:
        if "expression_gap" in r and not r["expression_gap"].get("skipped"):
            out["expression_gap"] = r["expression_gap"]
    # vocabulary / comprehension (multiple choice), by task
    mc_rows = [(t, r["mc"]) for t, r in rows if "mc" in r]
    if mc_rows:
        vocab = [m for t, m in mc_rows if m.get("band")]
        if vocab:
            out["vocabulary"] = items.vocabulary_summary(vocab)
        comp: dict[str, list[dict]] = {}
        for t, m in mc_rows:
            if not m.get("band"):
                comp.setdefault(t.task_id, []).append(m)
        if comp:
            out["comprehension"] = {
                tid: {
                    **items.comprehension_summary(v),
                    "genre": tasks[tid].target.get("genre") if tid in tasks else None,
                }
                for tid, v in comp.items()
            }
    # reading: wpm from the passage take, effective speed with the matching comprehension task
    for t, r in rows:
        if "reading" in r:
            rd = dict(r["reading"])
            task = tasks.get(t.task_id)
            qtask = task.target.get("questions") if task else None
            comp_pct = (
                out.get("comprehension", {}).get(qtask or "", {}).get("pct") if qtask else None
            )
            rd["comprehension_pct"] = comp_pct
            rd["effective_wpm"] = items.effective_reading_speed(rd.get("wpm"), comp_pct)
            out.setdefault("reading", {})[t.item_id] = rd
    ct = [r["ctest"] for _t, r in rows if "ctest" in r]
    if ct:
        n = sum(c["n"] for c in ct)
        c = sum(c["correct"] for c in ct)
        out["c_test"] = {
            "n": n,
            "correct": c,
            "pct": round(100 * c / n, 1) if n else None,
            "texts": ct,
        }
    ax = [r["axb"] for _t, r in rows if "axb" in r]
    if ax:
        out["axb"] = items.axb_summary(ax)
    # retells: idea units per retell take
    for t, r in rows:
        if "ideas" in r and items_map_stage(items, t.item_id) == "retell":
            out.setdefault("retell", {})[t.item_id] = {
                "units": len(r["ideas"].get("units", [])),
                "skipped": r["ideas"].get("skipped", False),
            }
    # email checklist (typed)
    for t, r in rows:
        if "checklist" in r and t.kind == "typed":
            out["email"] = {k: v for k, v in r["checklist"].items() if k != "turns"}
    # completeness
    expected = sum(len(t.items) for t in form.tasks)
    done_items = {t.item_id for t, _ in rows if t.status in ("finalized", "processed")}
    out["completion"] = {
        "items_expected": expected,
        "items_done": len(done_items),
        "share": round(len(done_items) / expected, 3) if expected else None,
    }

    for kind, result in out.items():
        existing = db.scalar(
            select(SessionResult).where(
                SessionResult.session_id == session.id,
                SessionResult.kind == kind,
                SessionResult.pipeline_version == settings.pipeline_version,
            )
        )
        if existing is not None:
            existing.result = result
            existing.job_id = job_id
        else:
            db.add(
                SessionResult(
                    session_id=session.id,
                    job_id=job_id,
                    kind=kind,
                    pipeline_version=settings.pipeline_version,
                    result=result,
                )
            )
    db.commit()
    return out
