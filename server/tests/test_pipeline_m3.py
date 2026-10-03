"""M3: LexTALE, typing metrics, idea units / expression gap, baseline processing and the
session summary job."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import processing, worker
from app.engines.base import Transcript, TWord
from app.pipeline import ideas, lextale, typing

from .conftest import make_wav
from .test_pipeline_m1 import _drain, _kinds
from .test_pipeline_m2 import _typed_take


# ------------------------------------------------------------------ pure
def test_lextale_scoring() -> None:
    items = lextale.ITEMS
    assert len(items) == 63 and sum(1 for w, _ in items[3:] if w) == 40
    # Answer "yes" to everything: words 100%, nonwords 0% → 50
    resp = [
        {"is_word": w, "answer": "yes", "rt_ms": 800.0, "practice": i < 3}
        for i, (w, _) in enumerate(items)
    ]
    s = lextale.score(resp)
    assert s.n_words == 40 and s.n_nonwords == 20 and s.score == 50.0 and s.mean_rt_ms == 800.0
    # Perfect
    resp = [
        {"is_word": w, "answer": "yes" if w else "no", "rt_ms": None, "practice": i < 3}
        for i, (w, _) in enumerate(items)
    ]
    assert lextale.score(resp).score == 100.0
    # Two unanswered nonwords
    resp[5]["answer"] = None
    resp[10]["answer"] = None
    s = lextale.score(resp)
    assert s.unanswered == 2 and s.score < 100.0


def test_typing_metrics() -> None:
    keys = []
    t = 0.0
    text = "hello world"
    for i, ch in enumerate(text):
        t += 150 if i != 6 else 2600  # one long pause before "world"
        keys.append({"t": t, "type": "down", "key": ch, "code": "Key"})
        keys.append({"t": t + 1, "type": "input", "len": i + 1})
    keys.append({"t": t + 50, "type": "down", "key": "Backspace", "code": "Backspace"})
    r = typing.analyze(keys, text, reference="hello world")
    assert r.chars == 11 and r.keystrokes == 12 and r.backspaces == 1
    assert r.pauses == 1 and r.bursts == 2 and r.mean_burst_chars == 5.5
    assert r.accuracy == 1.0 and r.chars_per_min is not None and r.chars_per_min > 100
    r2 = typing.analyze([], "", reference="abc")
    assert r2.chars_per_min is None and r2.accuracy == 0.0
    assert typing.analyze([], "hello wrld", reference="hello world").accuracy == round(
        1 - 1 / 11, 4
    )


def test_ideas_extract_and_coverage(monkeypatch) -> None:
    outs = iter(
        [{"units": ["a", "b", "c"]}, {"units": ["a", "b"]}, {"units": ["a", "b", "c", "d"]}]
    )
    monkeypatch.setattr(ideas, "structured", lambda *a, **k: next(outs))
    u = ideas.extract("some text", "ko")
    assert u.units == ["a", "b", "c"] and u.runs == [3, 2, 4] and u.spread == 2
    covs = iter(
        [
            {"covered": [True, False, True], "extra": ["x"]},
            {"covered": [True, False, False], "extra": []},
            {"covered": [True, True, True], "extra": ["y"]},
        ]
    )
    monkeypatch.setattr(ideas, "structured", lambda *a, **k: next(covs))
    c = ideas.coverage(["a", "b", "c"], "retelling")
    assert c.covered_flags == [True, False, True] and c.coverage == round(2 / 3, 3)


# ------------------------------------------------------------------ processing
def _audio_take(client: TestClient, sid: str, task: str, item: str, events=True) -> str:
    data = make_wav(0.6, sample_rate=16000)
    tid = client.post(
        f"/api/sessions/{sid}/takes",
        json={
            "task_id": task,
            "item_id": item,
            "kind": "audio",
            "sample_rate": 16000,
            "channels": 1,
        },
    ).json()["id"]
    client.put(f"/api/takes/{tid}/chunks/0", content=data).raise_for_status()
    if events:
        client.post(
            f"/api/takes/{tid}/events",
            json=[
                {"name": "prompt_end", "t_client_ms": 100.0},
                {"name": "record_start", "t_client_ms": 101.0},
            ],
        )
    client.post(
        f"/api/takes/{tid}/finalize",
        json={"sha256": hashlib.sha256(data).hexdigest(), "chunk_count": 1},
    ).raise_for_status()
    return tid


@pytest.fixture
def baseline_engines(monkeypatch):
    def fake(text):
        return lambda path, *, language="en", **_: Transcript(
            "x",
            f"{text} [{language}]".replace(" [en]", "").replace(" [ko]", ""),
            [TWord(w) for w in text.split()],
            language,
        )

    seen_lang: list[str] = []

    def dg(path, *, language="en", **_):
        seen_lang.append(language)
        return Transcript(
            "deepgram",
            "나는 의료 삽화가가 되고 싶다"
            if language == "ko"
            else "I want to become a medical illustrator",
            [],
            language,
        )

    monkeypatch.setitem(processing.ENGINES, "deepgram", dg)
    monkeypatch.setitem(processing.ENGINES, "azure", dg)
    monkeypatch.setitem(processing.ENGINES, "whisper", dg)
    monkeypatch.setattr(
        ideas, "extract", lambda text, lang, **_: ideas.IdeaUnits([text], [1, 1, 1], 0)
    )
    monkeypatch.setattr(
        ideas,
        "coverage",
        lambda units, retelling, **_: ideas.Coverage(
            len(units), 1, 1.0, [True] * len(units), [], 3
        ),
    )
    from app.engines.claude import Correction

    monkeypatch.setattr(
        processing,
        "minimal_correction",
        lambda text, **_: Correction(text, [text] * 3, [0, 0, 0], 0),
    )
    return seen_lang


def test_baseline_korean_and_expression_gap(client: TestClient, db, baseline_engines) -> None:
    sid = client.post("/api/sessions", json={"form_id": "baseline-day1"}).json()["id"]
    ko = _audio_take(client, sid, "B2", "B2-topic")
    en = _audio_take(client, sid, "B3", "B3-topic")
    _drain(db)
    k_ko, k_en = _kinds(db, ko), _kinds(db, en)
    assert "ko" in baseline_engines and "en" in baseline_engines
    assert "lexical" not in k_ko and "ideas" in k_ko  # no English metrics on Korean speech
    assert (
        k_en["expression_gap"]["coverage"] == 1.0
        and k_en["expression_gap"]["source_item"] == "B2-topic"
    )
    assert "speech_rate_ratio" in k_en["expression_gap"]  # None here: a sine has no syllables
    assert "lexical" in k_en


def test_expression_gap_waits_for_source(client: TestClient, db, baseline_engines) -> None:
    sid = client.post("/api/sessions", json={"form_id": "baseline-day1"}).json()["id"]
    _audio_take(client, sid, "B2", "B2-topic")
    en = _audio_take(client, sid, "B3", "B3-topic")
    # Simulate the Korean take's processing lagging: drop its process_take job after the probes.
    probes = [j for j in db.scalars(select(worker.Job)).all() if j.type == "wav_probe"]
    for _ in probes:
        worker.run_once(db)
    ko_job = next(
        j
        for j in db.scalars(select(worker.Job)).all()
        if j.type == "process_take" and j.payload["take_id"] != en
    )
    db.delete(ko_job)
    db.commit()
    _drain(db)
    job = db.scalar(select(worker.Job).where(worker.Job.type == "process_take"))
    assert job.status == "queued" and "waiting for source" in job.last_error
    assert "expression_gap" not in _kinds(db, en)


def test_expression_gap_without_source_is_skipped(client: TestClient, db, baseline_engines) -> None:
    sid = client.post("/api/sessions", json={"form_id": "baseline-day1"}).json()["id"]
    en = _audio_take(client, sid, "B3", "B3-topic")  # no Korean take at all
    _drain(db)
    gap = _kinds(db, en)["expression_gap"]
    assert gap["skipped"] is True and "not found" in gap["reason"]
    assert db.scalar(select(worker.Job).where(worker.Job.type == "process_take")).status == "done"


def test_lexical_decision_typing_and_session_summary(
    client: TestClient, db, baseline_engines
) -> None:
    sid = client.post("/api/sessions", json={"form_id": "baseline-day1"}).json()["id"]
    # LexTALE: practice + 2 scored items, with reaction times from events
    for item, answer, rt in (("L-00", "no", 900), ("L-03", "yes", 1200), ("L-04", "yes", 700)):
        r = client.post(
            f"/api/sessions/{sid}/takes", json={"task_id": "B4", "item_id": item, "kind": "typed"}
        )
        tid = r.json()["id"]
        client.post(
            f"/api/takes/{tid}/events",
            json=[
                {"name": "prompt_end", "t_client_ms": 1000.0},
                {"name": "answer", "t_client_ms": 1000.0 + rt},
            ],
        )
        client.post(
            f"/api/takes/{tid}/typed", json={"text": answer, "keystrokes": []}
        ).raise_for_status()
    # copy typing with a keystroke log
    keys = [{"t": 10 + i * 100, "type": "input", "len": i + 1} for i in range(20)]
    tid = client.post(
        f"/api/sessions/{sid}/takes", json={"task_id": "B5", "item_id": "B5-en", "kind": "typed"}
    ).json()["id"]
    client.post(
        f"/api/takes/{tid}/typed", json={"text": "The clinic called this", "keystrokes": keys}
    ).raise_for_status()
    # ratings incl. a reverse-keyed one
    _typed_take(client, sid, "B6", "S-anx-1", "8")
    _typed_take(client, sid, "B6", "S-anx-5", "2")  # reverse → 8
    _typed_take(client, sid, "B6", "S-cando-phone", "3")
    client.patch(f"/api/sessions/{sid}", json={"status": "done"}).raise_for_status()
    _drain(db)
    res = client.get(f"/api/sessions/{sid}/results").json()
    assert set(res) >= {"lextale", "typing", "ratings", "completion"}
    lt = res["lextale"]["result"]
    assert (
        lt["n_words"] == 1
        and lt["n_nonwords"] == 1
        and lt["words_correct"] == 1
        and lt["nonwords_correct"] == 0
    )
    assert lt["score"] == 50.0 and lt["mean_rt_ms"] == 950.0  # practice excluded
    assert (
        res["typing"]["result"]["en"]["chars"] == 22
        and res["typing"]["result"]["en"]["accuracy"] < 1
    )
    assert (
        res["ratings"]["result"]["anxiety"]["mean"] == 8.0
        and res["ratings"]["result"]["cando"]["mean"] == 3.0
    )
    assert res["completion"]["result"]["items_done"] == 7
    # Re-running the summary updates in place rather than duplicating.
    from app.models import SessionResult, TestSession

    session = db.get(TestSession, __import__("uuid").UUID(sid))
    processing.summarize_session(db, session)
    assert (
        db.scalar(
            select(__import__("sqlalchemy").func.count(SessionResult.id)).where(
                SessionResult.kind == "lextale"
            )
        )
        == 1
    )


def test_summary_waits_for_processing(client: TestClient, db, monkeypatch) -> None:
    sid = client.post("/api/sessions", json={"form_id": "core-A"}).json()["id"]
    _typed_take(client, sid, "C6", "C6-01", "x")
    client.patch(f"/api/sessions/{sid}", json={"status": "done"}).raise_for_status()
    # Make process_take fail once so the summary has to wait.
    calls = {"n": 0}
    orig = processing.process_take

    def flaky(db_, take, job_id=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return orig(db_, take, job_id)

    monkeypatch.setattr(processing, "process_take", flaky)
    jobs = {j.type: j for j in db.scalars(select(worker.Job)).all()}
    assert set(jobs) == {"process_take", "session_summary"}
    while worker.run_once(db):
        pass
    jobs = {j.type: j for j in db.scalars(select(worker.Job)).all()}
    assert jobs["process_take"].status == "queued"
    assert (
        jobs["session_summary"].status == "queued"
        and "still processing" in jobs["session_summary"].last_error
    )
    from datetime import UTC, datetime

    for j in jobs.values():
        j.run_after = datetime.now(UTC)
    db.commit()
    while worker.run_once(db):
        pass
    jobs = {j.type: j for j in db.scalars(select(worker.Job)).all()}
    assert jobs["process_take"].status == "done" and jobs["session_summary"].status == "done"
    assert "dictation" in client.get(f"/api/sessions/{sid}/results").json()
