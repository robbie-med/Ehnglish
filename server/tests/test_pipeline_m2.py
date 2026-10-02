"""M2: audio effects, dictation WER, phone checklist/phrases, and processing of typed takes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import processing, worker
from app.models import ProcessingResult
from app.pipeline import audiofx, checklist, dictation
from app.wav import read_samples, write_wav

from .test_pipeline_m1 import _drain, _finalized_take, _kinds


# ------------------------------------------------------------------ audio effects
@pytest.fixture
def speech_wav(tmp_path: Path) -> Path:
    sr = 16000
    t = np.arange(int(2.0 * sr)) / sr
    env = np.where((t > 0.4) & (t < 1.6), 1.0, 0.0) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t) ** 2)
    x = 0.2 * env * np.sin(2 * np.pi * 180 * t) * (1 + 0.5 * np.sin(2 * np.pi * 900 * t))
    p = tmp_path / "speech.wav"
    write_wav(p, x.astype(np.float32), sr)
    return p


def test_add_noise_hits_target_snr_and_is_deterministic(speech_wav: Path, tmp_path: Path) -> None:
    out1 = tmp_path / "n1.wav"
    out2 = tmp_path / "n2.wav"
    a1 = audiofx.add_noise(speech_wav, out1, snr_db=5, kind="babble")
    audiofx.add_noise(speech_wav, out2, snr_db=5, kind="babble")
    assert abs(a1 - 5) < 0.6
    assert out1.read_bytes() == out2.read_bytes()
    x, info = read_samples(out1)
    assert info.sample_rate == 16000 and abs(info.duration_s - 2.3) < 0.01  # 0.3 s lead-in
    # noise is present before speech starts
    lead = x[: int(0.25 * 16000), 0]
    assert float(np.sqrt(np.mean(lead**2))) > 0.005
    pink = audiofx.add_noise(speech_wav, tmp_path / "p.wav", snr_db=0, kind="pink")
    assert abs(pink - 0) < 0.6


@pytest.mark.skipif(not audiofx.have_ffmpeg(), reason="ffmpeg not installed")
def test_phone_line_bandlimits(speech_wav: Path, tmp_path: Path) -> None:
    out = tmp_path / "phone.wav"
    audiofx.phone_line(speech_wav, out)
    x, info = read_samples(out)
    assert info.sample_rate == 16000
    spec = np.abs(np.fft.rfft(x[:, 0]))
    freqs = np.fft.rfftfreq(len(x), 1 / 16000)
    in_band = spec[(freqs > 300) & (freqs < 3400)].sum()
    high = spec[freqs > 4500].sum()
    assert high < 0.05 * in_band  # nothing above the phone band except hiss
    audiofx.speed(speech_wav, tmp_path / "fast.wav", factor=1.3)
    _, fi = read_samples(tmp_path / "fast.wav")
    assert abs(fi.duration_s - 2.0 / 1.3) < 0.05


# ------------------------------------------------------------------ dictation
def test_wer_and_condition_summary() -> None:
    r = dictation.score(
        "Your prescription will be ready in twenty minutes.",
        "your prescription will be ready in 20 minutes",
        "clear",
    )
    assert r.exact and r.wer == 0.0
    r2 = dictation.score(
        "The nurse asked me to bring my insurance card.",
        "the nurse ask me to bring insurance cards",
        "phone",
    )
    assert r2.substitutions == 2 and r2.deletions == 1 and r2.wer == round(3 / 9, 4)
    ops = [a["op"] for a in r2.alignment]
    assert ops.count("sub") == 2 and ops.count("del") == 1
    summary = dictation.condition_summary([r, r2, dictation.score("a b c", "a b", "noise")])
    assert summary["mean_wer"]["clear"] == 0.0 and summary["phone_penalty"] == r2.wer
    assert summary["noise_penalty"] == round(1 / 3, 4) and summary["fast_penalty"] is None


# ------------------------------------------------------------------ phone call
def test_phrase_use_fuzzy() -> None:
    r = checklist.phrase_use(
        ["I'd like to reschedule", "do I need to fast", "thank you"],
        "hi um i would like to reschedule my checkup thanks a lot",
    )
    used = {p["phrase"]: p["used"] for p in r["phrases"]}
    assert used["I'd like to reschedule"] is True
    assert used["do I need to fast"] is False
    assert r["total"] == 3


def test_score_goals_majority(monkeypatch) -> None:
    answers = iter(
        [
            {
                "goals": [
                    {"index": 0, "done": True, "evidence": "a"},
                    {"index": 1, "done": False, "evidence": ""},
                ]
            },
            {
                "goals": [
                    {"index": 0, "done": True, "evidence": "b"},
                    {"index": 1, "done": True, "evidence": "x"},
                ]
            },
            {
                "goals": [
                    {"index": 0, "done": False, "evidence": ""},
                    {"index": 1, "done": False, "evidence": ""},
                ]
            },
        ]
    )
    monkeypatch.setattr(checklist, "structured", lambda *a, **k: next(answers))
    r = checklist.score_goals(["g0", "g1"], [{"caller": "hi", "learner": "hello"}])
    assert [g["done"] for g in r.goals] == [True, False]
    assert r.goals[0]["votes"] == 2 and r.done == 1 and r.completion == 0.5


# ------------------------------------------------------------------ processing
def _typed_take(client: TestClient, sid: str, task: str, item: str, text: str) -> str:
    r = client.post(
        f"/api/sessions/{sid}/takes", json={"task_id": task, "item_id": item, "kind": "typed"}
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = client.post(f"/api/takes/{tid}/typed", json={"text": text, "keystrokes": []})
    assert r.status_code == 200, r.text
    return tid


def test_dictation_and_rating_processing(client: TestClient, db) -> None:
    sid = client.post("/api/sessions", json={"form_id": "core-A"}).json()["id"]
    t1 = _typed_take(
        client, sid, "C6", "C6-01", "your prescription will be ready in twenty minutes"
    )
    t2 = _typed_take(
        client, sid, "C6", "C6-07", "the pharmacy on main street closes at six on saturday"
    )
    t3 = _typed_take(client, sid, "C7", "C7-phone", "4")
    _drain(db)
    k1, k2, k3 = _kinds(db, t1), _kinds(db, t2), _kinds(db, t3)
    assert k1["wer"]["exact"] is True and k1["wer"]["condition"] == "clear"
    assert k2["wer"]["condition"] == "phone" and k2["wer"]["substitutions"] == 1
    assert k3 == {}  # ratings are stored, not processed
    assert all(j.status == "done" for j in db.scalars(select(worker.Job)).all())


def test_typed_response_language_metrics(client: TestClient, db, monkeypatch) -> None:
    from app.engines.claude import Correction

    monkeypatch.setattr(
        processing,
        "minimal_correction",
        lambda text, **_: Correction(text, [text] * 3, [0, 0, 0], 0),
    )
    sid = client.post("/api/sessions", json={"form_id": "dummy-v0"}).json()["id"]
    tid = _typed_take(
        client,
        sid,
        "D2",
        "D2-01",
        "Hi, I would like to reschedule my appointment because I have a fever.",
    )
    _drain(db)
    k = _kinds(db, tid)
    assert k["lexical"]["tokens"] > 8 and k["syntax"]["clauses"] >= 2 and k["errors"]["edits"] == []


def test_phone_call_turns_accumulate_checklist(client: TestClient, db, monkeypatch) -> None:
    from app.engines.base import Transcript, TWord

    def fake(text):
        return lambda path, *, language="en", **_: Transcript(
            "x", text, [TWord(w) for w in text.split()]
        )

    monkeypatch.setitem(
        processing.ENGINES, "deepgram", fake("hi this is Mina I'd like to reschedule my checkup")
    )
    monkeypatch.setitem(
        processing.ENGINES, "azure", fake("hi this is Mina I'd like to reschedule my checkup")
    )
    monkeypatch.setitem(
        processing.ENGINES, "whisper", fake("hi this is Mina I'd like to reschedule my checkup")
    )
    seen: list[list[dict]] = []

    def fake_goals(goals, turns, **_):
        seen.append(turns)
        return checklist.ChecklistResult(
            [{"goal": g, "done": i == 0, "votes": 3, "evidence": []} for i, g in enumerate(goals)],
            1,
            len(goals),
            round(1 / len(goals), 3),
            3,
        )

    monkeypatch.setattr(checklist, "score_goals", fake_goals)
    monkeypatch.setattr(
        processing,
        "minimal_correction",
        lambda text, **_: __import__("app.engines.claude", fromlist=["Correction"]).Correction(
            text, [text] * 3, [0, 0, 0], 0
        ),
    )
    t1 = _finalized_take(client, "core-A", "C4", "C4-01")
    _drain(db)
    k = _kinds(db, t1)
    assert k["phrases"]["used"] == 1  # "I'd like to reschedule"
    assert k["checklist"]["done"] == 1 and k["checklist"]["is_last_turn"] is False
    turns = seen[-1]
    assert (
        turns[0]["item"] == "C4-01"
        and "reschedule" in turns[0]["learner"]
        and turns[1]["learner"] == ""
    )
    # Second turn sees the first turn's transcript.
    sid = client.get(f"/api/takes/{t1}").json()["session_id"]
    import hashlib

    from .conftest import make_wav

    data = make_wav(0.5, sample_rate=16000)
    r = client.post(
        f"/api/sessions/{sid}/takes",
        json={
            "task_id": "C4",
            "item_id": "C4-02",
            "kind": "audio",
            "sample_rate": 16000,
            "channels": 1,
        },
    )
    t2 = r.json()["id"]
    client.put(f"/api/takes/{t2}/chunks/0", content=data).raise_for_status()
    client.post(
        f"/api/takes/{t2}/finalize",
        json={"sha256": hashlib.sha256(data).hexdigest(), "chunk_count": 1},
    ).raise_for_status()
    _drain(db)
    assert "reschedule" in seen[-1][0]["learner"] and "reschedule" in seen[-1][1]["learner"]
    assert (
        len(db.scalars(select(ProcessingResult).where(ProcessingResult.kind == "checklist")).all())
        == 2
    )
