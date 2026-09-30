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
from sqlalchemy.orm import Session

from .config import get_settings
from .content import Form, Item, Task, get_forms
from .engines import azure, deepgram, mfa, whisper
from .engines import phonemes as phoneme_engine
from .engines.base import EngineError, Transcript
from .engines.claude import minimal_correction
from .models import ProcessingResult, Take, TestSession
from .pipeline import ei, lexical, phonemes, praat, rhythm, syntax, vote
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
                if "not set" in str(e):
                    log.info("%s skipped: %s", name, e)
                    return {"engine": name, "skipped": True, "reason": str(e)}
                raise

        out[name] = ctx.step(kind, run)
    return out


def step_vote(ctx: Ctx, asr: dict[str, dict]) -> dict:
    def run() -> dict:
        engines: dict[str, list[vote.Word]] = {}
        for name in ("deepgram", "whisper", "azure"):  # backbone first: the most verbatim engine
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


# ---------------------------------------------------------------------- per task type
def process_take(db: Session, take: Take, job_id: uuid.UUID | None = None) -> str:
    ctx = Ctx(db, take, job_id)
    t = ctx.task.type
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
    if t == "describe_opinion":
        asr = step_asr(ctx)
        tr = step_vote(ctx, asr)
        step_timing(ctx)
        step_alignment(ctx, tr)
        step_language(ctx, tr)
        return "describe_opinion done"
    return f"no processing for {t}"
