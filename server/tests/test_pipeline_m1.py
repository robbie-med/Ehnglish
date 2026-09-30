"""M1: language metrics, engine payload parsers, rhythm, and the process_take orchestration with
all engines mocked (no keys needed)."""

from __future__ import annotations

import hashlib
from datetime import UTC
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import processing, worker
from app.engines import azure, deepgram, whisper
from app.engines.base import Transcript, TWord
from app.models import ProcessingResult
from app.pipeline import lexical, rhythm, syntax

from .conftest import make_wav


# ------------------------------------------------------------------ pure metrics
def test_lexical_bands_and_mtld() -> None:
    words = (
        "the nurse said the pharmacy would refill the prescription after the doctor approved it um "
        "so i asked whether the insurance covers the generic version"
    ).split()
    r = lexical.analyze(words)
    assert r.fillers == 1 and r.tokens == len(words) - 1
    assert r.band_shares["1k"] < r.band_shares["5k"] <= 1.0
    assert r.medical_tokens >= 6 and "pharmacy" in r.medical_types
    assert r.mtld is not None and r.mtld > 20
    assert lexical.analyze([]).tokens == 0
    assert lexical.mtld(["a"] * 5) is None


def test_syntax_complexity() -> None:
    simple = syntax.analyze("I called the clinic. The nurse answered.")
    complex_ = syntax.analyze(
        "Although the office was closed, the nurse who answered said that I should call back tomorrow."
    )
    assert simple.sentences == 2 and simple.subordinate_clauses == 0
    assert complex_.subordinate_clauses >= 2
    assert complex_.mean_clause_len is not None and complex_.subordination_ratio > 0


def test_errant_classification() -> None:
    r = syntax.classify_errors(
        "she go to the doctor yesterday and take two pill",
        "she went to the doctor yesterday and took two pills",
    )
    types = set(r.by_type)
    assert any(t.endswith("VERB:TENSE") or t.endswith("VERB:SVA") for t in types)
    assert any("NOUN" in t for t in types)
    assert r.per_100_words > 0
    assert syntax.classify_errors("all good here", "all good here").edits == []


def test_rhythm_from_phones() -> None:
    phones = [
        ("DH", 0.0, 0.05),
        ("AH", 0.05, 0.12),
        ("N", 0.12, 0.18),
        ("ER", 0.18, 0.30),
        ("S", 0.30, 0.40),
        ("sil", 0.40, 0.7),
        ("K", 0.7, 0.76),
        ("AO", 0.76, 0.9),
        ("L", 0.9, 0.98),
    ]
    r = rhythm.analyze(phones)
    assert r.n_vocalic == 3 and r.n_consonantal == 5
    assert 30 < r.percent_v < 70
    assert r.npvi_v is not None and r.delta_c_ms is not None


# ------------------------------------------------------------------ engine payload parsers
def test_deepgram_parse() -> None:
    payload = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "um the nurse",
                            "confidence": 0.93,
                            "words": [
                                {"word": "um", "start": 0.1, "end": 0.3, "confidence": 0.7},
                                {"word": "the", "start": 0.4, "end": 0.5, "confidence": 0.99},
                            ],
                        }
                    ]
                }
            ]
        }
    }
    t = deepgram.parse(payload)
    assert t.engine == "deepgram" and t.words[0].word == "um" and t.words[1].conf == 0.99


def test_whisper_parse() -> None:
    t = whisper.parse(
        {
            "text": "The nurse.",
            "words": [
                {"word": " The", "start": 0.0, "end": 0.2},
                {"word": " nurse.", "start": 0.2, "end": 0.5},
            ],
        }
    )
    assert [w.word for w in t.words] == ["The", "nurse."]


def test_azure_parse_and_pron_merge() -> None:
    t = azure.parse_stt(
        {
            "combinedPhrases": [{"text": "The nurse called."}],
            "phrases": [
                {
                    "text": "The nurse called.",
                    "confidence": 0.9,
                    "words": [
                        {"text": "The", "offsetMilliseconds": 100, "durationMilliseconds": 200}
                    ],
                }
            ],
        }
    )
    assert t.text == "The nurse called." and t.words[0].start == 0.1 and t.words[0].end == 0.3
    seg = {
        "NBest": [
            {
                "PronunciationAssessment": {
                    "AccuracyScore": 80,
                    "FluencyScore": 90,
                    "CompletenessScore": 100,
                    "ProsodyScore": 70,
                    "PronScore": 85,
                },
                "Words": [
                    {
                        "Word": "pharmacy",
                        "Offset": 1_000_000,
                        "Duration": 5_000_000,
                        "PronunciationAssessment": {
                            "AccuracyScore": 60,
                            "ErrorType": "Mispronunciation",
                        },
                        "Phonemes": [
                            {"Phoneme": "f", "PronunciationAssessment": {"AccuracyScore": 40}}
                        ],
                    }
                ],
            }
        ]
    }
    seg2 = {
        "NBest": [
            {
                "PronunciationAssessment": {
                    "AccuracyScore": 100,
                    "FluencyScore": 100,
                    "CompletenessScore": 100,
                    "ProsodyScore": 100,
                    "PronScore": 100,
                },
                "Words": [
                    {
                        "Word": "lab",
                        "PronunciationAssessment": {"AccuracyScore": 100, "ErrorType": "None"},
                    }
                ]
                * 3,
            }
        ]
    }
    r = azure.merge_pron_results([seg, seg2])
    assert r.accuracy == 95.0  # (1*80 + 3*100) / 4
    assert (
        r.words[0].error_type == "Mispronunciation"
        and r.words[0].start == 0.1
        and r.words[0].end == 0.6
    )
    assert r.words[1].error_type is None
    assert azure.merge_pron_results([]).accuracy is None


# ------------------------------------------------------------------ orchestration (mocked engines)
def _fake_transcript(engine: str, text: str, conf: float = 0.9) -> Transcript:
    words = [TWord(w, i * 0.3, i * 0.3 + 0.25, conf) for i, w in enumerate(text.split())]
    return Transcript(engine, text, words)


@pytest.fixture
def mocked_engines(monkeypatch):
    calls: dict[str, int] = {"deepgram": 0, "azure": 0, "whisper": 0, "claude": 0, "pron": 0}

    def mk(engine: str, text: str):
        def fn(path: Path, *, language: str = "en", **_):
            calls[engine] += 1
            return _fake_transcript(engine, text)

        return fn

    monkeypatch.setitem(
        processing.ENGINES, "deepgram", mk("deepgram", "the pharmacy closes at nine")
    )
    monkeypatch.setitem(processing.ENGINES, "azure", mk("azure", "the pharmacy closes at night"))
    monkeypatch.setitem(processing.ENGINES, "whisper", mk("whisper", "the pharmacy closes at nine"))

    def fake_pron(path, reference_text, **_):
        calls["pron"] += 1
        return azure.merge_pron_results([])

    monkeypatch.setattr(processing.azure, "pronunciation_assessment", fake_pron)

    def fake_correction(text, **_):
        calls["claude"] += 1
        from app.engines.claude import Correction

        return Correction(text.replace("[uncertain] ", ""), [text] * 3, [0, 0, 0], 0)

    monkeypatch.setattr(processing, "minimal_correction", fake_correction)
    return calls


def _finalized_take(
    client: TestClient, form: str, task: str, item: str, seconds: float = 1.0
) -> str:
    sid = client.post("/api/sessions", json={"form_id": form}).json()["id"]
    r = client.post(
        f"/api/sessions/{sid}/takes",
        json={
            "task_id": task,
            "item_id": item,
            "kind": "audio",
            "sample_rate": 16000,
            "channels": 1,
        },
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    data = make_wav(seconds, sample_rate=16000)
    client.put(f"/api/takes/{tid}/chunks/0", content=data).raise_for_status()
    client.post(
        f"/api/takes/{tid}/events",
        json=[
            {"name": "prompt_end", "t_client_ms": 1000.0},
            {"name": "record_start", "t_client_ms": 1004.0},
        ],
    ).raise_for_status()
    r = client.post(
        f"/api/takes/{tid}/finalize",
        json={"sha256": hashlib.sha256(data).hexdigest(), "chunk_count": 1},
    )
    assert r.status_code == 200, r.text
    return tid


def _drain(db) -> int:
    n = 0
    while worker.run_once(db):
        n += 1
    return n


def _kinds(db, tid: str) -> dict[str, dict]:
    rows = db.scalars(select(ProcessingResult).where(ProcessingResult.take_id == tid)).all()
    return {r.kind: r.result for r in rows}


def test_sentence_repeat_pipeline(client: TestClient, db, mocked_engines) -> None:
    tid = _finalized_take(client, "core-A", "C2", "C2-01")
    assert _drain(db) == 2  # wav_probe then process_take
    k = _kinds(db, tid)
    assert {
        "wav_probe",
        "asr:deepgram",
        "asr:azure",
        "asr:whisper",
        "transcript",
        "timing",
        "latency",
        "ei",
    } <= set(k)
    assert (
        k["transcript"]["text"] == "the pharmacy closes at nine"
    )  # majority beats azure's "night"
    assert k["transcript"]["n_engines"] == 3 and k["transcript"]["agreement"] == 0.8
    assert k["ei"]["exact"] is True and k["ei"]["pct_syllables"] == 100.0
    assert k["latency"]["prompt_to_record_ms"] == 4.0
    assert all(r.pipeline_version == "test.0.1" for r in db.scalars(select(ProcessingResult)).all())
    # Re-running is idempotent: nothing is recomputed, no engine is called again.
    before = dict(mocked_engines)
    from app.models import Take as T

    processing.process_take(db, db.get(T, tid))
    assert mocked_engines == before
    assert len(_kinds(db, tid)) == len(k)


def test_describe_opinion_runs_language_steps(client: TestClient, db, mocked_engines) -> None:
    tid = _finalized_take(client, "core-A", "C5", "C5-describe")
    _drain(db)
    k = _kinds(db, tid)
    assert {"lexical", "syntax", "correction", "errors", "alignment"} <= set(k)
    assert k["alignment"]["skipped"] is True  # no MFA url in tests
    assert mocked_engines["claude"] == 1
    assert k["lexical"]["tokens"] == 5


def test_read_aloud_calls_pronunciation(client: TestClient, db, mocked_engines) -> None:
    tid = _finalized_take(client, "core-A", "C1", "C1-para")
    _drain(db)
    assert mocked_engines["pron"] == 1
    assert "pron" in _kinds(db, tid)


def test_silence_take_only_probes(client: TestClient, db, mocked_engines) -> None:
    tid = _finalized_take(client, "core-A", "C0", "C0-silence")
    _drain(db)
    assert set(_kinds(db, tid)) == {"wav_probe"}
    assert mocked_engines["deepgram"] == 0


def test_unconfigured_engine_is_skipped_not_fatal(client: TestClient, db, monkeypatch) -> None:
    from app.engines.base import EngineError

    def boom(path, *, language="en", **_):
        raise EngineError("EHNGLISH_DEEPGRAM_API_KEY not set")

    monkeypatch.setitem(processing.ENGINES, "deepgram", boom)
    monkeypatch.setitem(
        processing.ENGINES,
        "azure",
        lambda path, *, language="en", **_: _fake_transcript("azure", "take one tablet"),
    )
    monkeypatch.setitem(
        processing.ENGINES,
        "whisper",
        lambda path, *, language="en", **_: _fake_transcript("whisper", "take one tablet"),
    )
    tid = _finalized_take(client, "core-A", "C2", "C2-06")
    _drain(db)
    k = _kinds(db, tid)
    assert k["asr:deepgram"]["skipped"] is True
    assert k["transcript"]["n_engines"] == 2 and k["transcript"]["text"] == "take one tablet"
    job_states = [j.status for j in db.execute(select(worker.Job)).scalars()]
    assert job_states.count("done") == 2


def test_engine_failure_retries_and_keeps_partial_results(
    client: TestClient, db, monkeypatch
) -> None:
    from app.engines.base import EngineError

    n = {"calls": 0}

    def flaky(path, *, language="en", **_):
        n["calls"] += 1
        if n["calls"] == 1:
            raise EngineError("whisper 503: overloaded")
        return _fake_transcript("whisper", "please bring your insurance card")

    monkeypatch.setitem(
        processing.ENGINES,
        "deepgram",
        lambda path, *, language="en", **_: _fake_transcript(
            "deepgram", "please bring your insurance card"
        ),
    )
    monkeypatch.setitem(
        processing.ENGINES,
        "azure",
        lambda path, *, language="en", **_: _fake_transcript(
            "azure", "please bring your insurance card"
        ),
    )
    monkeypatch.setitem(processing.ENGINES, "whisper", flaky)
    tid = _finalized_take(client, "core-A", "C2", "C2-02")
    _drain(db)
    k = _kinds(db, tid)
    assert "asr:deepgram" in k and "asr:whisper" not in k  # partial progress kept
    job = db.scalar(select(worker.Job).where(worker.Job.type == "process_take"))
    assert job.status == "queued" and job.attempts == 1
    from datetime import datetime

    job.run_after = datetime.now(UTC)
    db.commit()
    _drain(db)
    k = _kinds(db, tid)
    assert "asr:whisper" in k and "ei" in k and n["calls"] == 2


# ------------------------------------------------------------------ phoneme comparison (pure)
def test_phoneme_expectations_and_comparison() -> None:
    from app.pipeline import phonemes as ph

    exp = ph.expected_ipa("pharmacy lab")
    assert exp[0][:2] == ["f", "ɑ"] and exp[1] == ["l", "æ", "b"]
    # She says "parmacy rab" with an extra vowel after the final b: f→p, l→ɹ, +ʌ
    produced = ph.tokenize_ipa("p ɑ ɹ m ʌ s i ɹ æ b ʌ")
    r = ph.compare(exp, produced)
    assert r.substitutions == 2 and r.insertions == 1 and r.deletions == 0
    assert r.contrast_errors == {"f/p": 1, "r/l": 1}
    assert r.extra_vowels == 1
    assert r.phone_accuracy == round((r.n_expected - 2) / r.n_expected, 4)
    assert ph.tokenize_ipa("ðʌ") == ["ð", "ʌ"] and ph.tokenize_ipa("t ʃ aɪ") == ["tʃ", "aɪ"]
    assert ph.compare(ph.expected_ipa("lab"), ph.tokenize_ipa("l æ b")).per == 0.0


def test_report_summarizes_session(client: TestClient, db, mocked_engines) -> None:
    from app import report

    tid = _finalized_take(client, "core-A", "C2", "C2-01")
    _drain(db)
    sid = client.get(f"/api/takes/{tid}").json()["session_id"]
    import uuid as _uuid

    lines = report.summarize(db, _uuid.UUID(sid))
    text = "\n".join(lines)
    assert "core-A" in text and "C2/C2-01" in text
    assert "repetition: 100.0% syllables" in text
    assert "transcript (3 engines" in text
    assert "not found" in report.summarize(db, _uuid.uuid4())[0]
