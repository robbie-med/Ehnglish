"""Plain-text summary of a session's processing results, for checking M1 numbers before the
dashboard exists (M5). `python -m app.report <session_id>` or `python -m app.report --latest`."""

from __future__ import annotations

import argparse
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .db import get_sessionmaker
from .models import Take, TestSession


def _fmt(v: object) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def summarize(db: Session, session_id: uuid.UUID) -> list[str]:
    s = db.scalar(
        select(TestSession)
        .where(TestSession.id == session_id)
        .options(selectinload(TestSession.takes).selectinload(Take.results))
    )
    if s is None:
        return [f"session {session_id} not found"]
    lines = [
        f"session {s.id}  form {s.form_id} v{s.form_version}  status {s.status}  started {s.started_at:%Y-%m-%d %H:%M}"
    ]
    setup = s.setup or {}
    nf = (setup.get("noise_floor") or {}).get("rms_dbfs")
    hp = (setup.get("headphones") or {}).get("leak_db")
    lines.append(
        f"setup: noise floor {_fmt(nf)} dBFS · headphone leak {_fmt(hp)} dB · sleep {setup.get('sleep_h')} h · stress {setup.get('stress')} · mood {setup.get('mood')}"
    )
    for t in s.takes:
        if t.status == "rejected":
            continue
        res = {r.kind: r.result for r in t.results}
        head = (
            f"\n{t.task_id}/{t.item_id} a{t.attempt}  {t.kind}  {t.status}  {_fmt(t.duration_s)} s"
        )
        versions = sorted({r.pipeline_version for r in t.results})
        lines.append(head + (f"  [pipeline {', '.join(versions)}]" if versions else ""))
        if t.kind == "typed" and t.typed:
            lines.append(f"  text: {t.typed.text[:120]!r}  keystrokes {t.typed.keystroke_count}")
        q = t.quality or {}
        if q:
            lines.append(
                f"  quality: rms {_fmt(q.get('rms_dbfs'))} dBFS · snr {_fmt(q.get('snr_db'))} dB · clip {q.get('clip_count', 0)} · flags {q.get('flags') or []}"
            )
        tr = res.get("transcript")
        if tr:
            lines.append(
                f"  transcript ({tr.get('n_engines')} engines, agreement {_fmt(tr.get('agreement'))}, uncertain {_fmt(tr.get('uncertain_share'))}): {tr.get('text', '')[:160]!r}"
            )
        for name in ("deepgram", "azure", "whisper"):
            a = res.get(f"asr:{name}")
            if a and a.get("skipped"):
                lines.append(f"  asr:{name}: skipped ({a.get('reason')})")
        tm = res.get("timing")
        if tm:
            lines.append(
                f"  timing: {tm.get('n_syllables')} syl · speech {_fmt(tm.get('speech_rate_syl_per_s'))}/s · artic {_fmt(tm.get('articulation_rate_syl_per_s'))}/s · "
                f"pauses {tm.get('n_pauses')} (mean {_fmt(tm.get('mean_pause_s'))} s) · MLR {_fmt(tm.get('mean_length_of_run_syl'))} · onset {_fmt(tm.get('onset_s'))} s · f0 {_fmt(tm.get('pitch_median_hz'))} Hz"
            )
        lat = res.get("latency")
        if lat:
            lines.append(
                f"  latency: {_fmt(lat.get('latency_ms'))} ms (onset {_fmt(lat.get('onset_s'))} s + prompt→record {_fmt(lat.get('prompt_to_record_ms'))} ms)"
            )
        e = res.get("ei")
        if e:
            lines.append(
                f"  repetition: {e.get('pct_syllables')}% syllables · {e.get('words_correct')}/{e.get('target_words')} words · exact {e.get('exact')}"
            )
        p = res.get("pron")
        if p:
            lines.append(
                "  pron: skipped"
                if p.get("skipped")
                else f"  pron: accuracy {_fmt(p.get('accuracy'))} · fluency {_fmt(p.get('fluency'))} · prosody {_fmt(p.get('prosody'))} · errors {sum(1 for w in p.get('words', []) if w.get('error_type'))}"
            )
        ph = res.get("phonemes")
        if ph:
            lines.append(
                "  phonemes: skipped"
                if ph.get("skipped")
                else f"  phonemes: accuracy {_fmt(ph.get('phone_accuracy'))} · PER {_fmt(ph.get('per'))} · contrasts {ph.get('contrast_errors')} · extra vowels {ph.get('extra_vowels')}"
            )
        al = res.get("alignment")
        if al:
            rh = al.get("rhythm") or {}
            lines.append(
                "  alignment: skipped"
                if al.get("skipped")
                else f"  alignment: {len(al.get('words', []))} words · %V {_fmt(rh.get('percent_v'))} · ΔC {_fmt(rh.get('delta_c_ms'))} ms · nPVI-V {_fmt(rh.get('npvi_v'))}"
            )
        lx, sy, er = res.get("lexical"), res.get("syntax"), res.get("errors")
        if lx:
            lines.append(
                f"  lexical: {lx.get('tokens')} tokens · MTLD {_fmt(lx.get('mtld'))} · ≤2k {_fmt((lx.get('band_shares') or {}).get('2k'))} · medical {lx.get('medical_tokens')}"
            )
        if sy:
            lines.append(
                f"  syntax: {sy.get('clauses')} clauses · sub. ratio {_fmt(sy.get('subordination_ratio'))} · clause len {_fmt(sy.get('mean_clause_len'))}"
            )
        if er:
            lines.append(
                "  errors: skipped"
                if er.get("skipped")
                else f"  errors: {_fmt(er.get('per_100_words'))}/100 words · error-free clauses {_fmt(er.get('error_free_clause_share'))} · {er.get('by_type')}"
            )
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_id", nargs="?")
    ap.add_argument("--latest", action="store_true")
    args = ap.parse_args()
    with get_sessionmaker()() as db:
        if args.latest or not args.session_id:
            s = db.scalar(select(TestSession).order_by(TestSession.started_at.desc()))
            if s is None:
                raise SystemExit("no sessions")
            sid = s.id
        else:
            sid = uuid.UUID(args.session_id)
        print("\n".join(summarize(db, sid)))


if __name__ == "__main__":
    main()
