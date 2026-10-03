"""M5: metric evaluation, bootstrapped CIs, anchors and scales, trends, estimates, and the
dashboard / export / viewer endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import metrics, processing
from app.config import get_settings
from app.engines.base import Transcript, TWord
from app.pipeline import checklist

from .test_pipeline_m1 import _drain
from .test_pipeline_m2 import _typed_take


def test_bootstrap_and_trend() -> None:
    assert metrics.bootstrap_ci([1.0, 2.0]) is None
    lo, hi = metrics.bootstrap_ci([10.0] * 5 + [20.0] * 5)
    assert 10 <= lo <= 15 <= hi <= 20
    tr = metrics.trend(
        [
            {"session_id": "a", "started_at": "1", "value": 10.0, "ci95": (8.0, 12.0)},
            {"session_id": "b", "started_at": "2", "value": 11.0, "ci95": (9.0, 13.0)},
        ]
    )
    assert tr["change"] == 1.0 and tr["detectable"] is False
    tr2 = metrics.trend(
        [
            {"session_id": "a", "started_at": "1", "value": 10.0, "ci95": (8.0, 12.0)},
            {"session_id": "b", "started_at": "2", "value": 15.0, "ci95": (13.0, 17.0)},
        ]
    )
    assert tr2["detectable"] is True
    assert (
        metrics.trend([{"session_id": "a", "started_at": "1", "value": 1.0, "ci95": None}])[
            "change"
        ]
        is None
    )


def test_scales_and_estimates() -> None:
    vals = {
        "ei_pct_syllables": metrics.MetricValue("ei_pct_syllables", 80.0, 20, (75.0, 85.0)),
        "errors_per_100": metrics.MetricValue("errors_per_100", 5.0, 3, None),
        "response_latency_ms": metrics.MetricValue("response_latency_ms", 900.0, 6, None),
        "wer_clear": metrics.MetricValue("wer_clear", 10.0, 3, None),
    }
    metrics.apply_anchor(
        vals, {"ei_pct_syllables": 98.0, "errors_per_100": 2.0, "response_latency_ms": 450.0}
    )
    assert vals["ei_pct_syllables"].scale == round(100 * 80 / 98, 1)
    assert vals["errors_per_100"].scale == 40.0  # lower is better: anchor / value
    assert vals["response_latency_ms"].pct_of_anchor == 50.0
    assert vals["wer_clear"].scale is None  # no anchor
    sp = metrics.estimate_skill("speaking", vals)
    assert (
        sp["cefr"] == "B2"
        and sp["label"] == "estimate"
        and sp["toefl"] == (20, 24)
        and sp["ielts"] == (5.5, 6.5)
    )
    assert {b["metric"] for b in sp["based_on"]} == {
        "ei_pct_syllables",
        "errors_per_100",
        "response_latency_ms",
    }
    li = metrics.estimate_skill("listening", vals)
    assert li["cefr"] == "B2"
    assert metrics.estimate_skill("reading", vals)["cefr"] is None


def _fake_engines(monkeypatch, text="the pharmacy closes at nine"):
    def fn(path, *, language="en", **_):
        return Transcript(
            "x",
            text,
            [TWord(w, i * 0.3, i * 0.3 + 0.25, 0.9) for i, w in enumerate(text.split())],
            language,
        )

    for e in ("deepgram", "azure", "whisper"):
        monkeypatch.setitem(processing.ENGINES, e, fn)
    from app.engines.claude import Correction

    monkeypatch.setattr(
        processing, "minimal_correction", lambda t, **_: Correction(t, [t] * 3, [0, 0, 0], 0)
    )
    monkeypatch.setattr(
        checklist,
        "score_goals",
        lambda goals, turns, **_: checklist.ChecklistResult(
            [{"goal": g, "done": True, "votes": 3, "evidence": []} for g in goals],
            len(goals),
            len(goals),
            1.0,
            3,
        ),
    )


def _core_session(client: TestClient, db) -> str:
    import hashlib

    from .conftest import make_wav

    sid = client.post("/api/sessions", json={"form_id": "core-A"}).json()["id"]
    for item in ("C2-01", "C2-02", "C2-03"):
        data = make_wav(0.6, sample_rate=16000)
        tid = client.post(
            f"/api/sessions/{sid}/takes",
            json={
                "task_id": "C2",
                "item_id": item,
                "kind": "audio",
                "sample_rate": 16000,
                "channels": 1,
            },
        ).json()["id"]
        client.put(f"/api/takes/{tid}/chunks/0", content=data).raise_for_status()
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
    for item, ans in (
        ("C6-01", "your prescription will be ready in twenty minutes"),
        ("C6-07", "the pharmacy on main street closes at six on saturday"),
    ):
        _typed_take(client, sid, "C6", item, ans)
    _typed_take(client, sid, "C7", "C7-phone", "6")
    client.patch(f"/api/sessions/{sid}", json={"status": "done"}).raise_for_status()
    _drain(db)
    return sid


def test_dashboard_export_viewer(client: TestClient, db, monkeypatch) -> None:
    _fake_engines(monkeypatch)
    sid = _core_session(client, db)
    dash = client.get("/api/dashboard").json()
    assert dash["subject"]["email"] == "tester@example.com" and dash["viewer"]["role"] == "learner"
    assert len(dash["sessions"]) == 1
    speaking = {m["id"]: m for m in dash["domains"]["speaking"]}
    ei_latest = speaking["ei_pct_syllables"]["latest"]
    assert 0 < ei_latest["value"] < 100.0 and ei_latest["n"] == 3
    assert ei_latest["ci95"] is not None  # 3 items → bootstrap
    assert speaking["ei_pct_syllables"]["definition"]["ko"]
    listening = {m["id"]: m for m in dash["domains"]["listening"]}
    assert (
        listening["wer_clear"]["latest"]["value"] == 0.0
        and listening["wer_phone"]["latest"]["value"] > 0
    )
    assert {m["id"] for m in dash["domains"]["self"]} >= {"confidence"}
    assert {m["id"] for m in dash["domains"]["quality"]} >= {
        "completion_pct",
        "transcript_agreement",
    }
    est = {e["skill"]: e for e in dash["estimates"]}
    assert (
        est["speaking"]["cefr"] in ("A2", "B1", "B2", "C1", "C2")
        and est["speaking"]["label"] == "estimate"
    )
    assert speaking["ei_pct_syllables"]["latest"]["scale"] is None  # no anchor sessions yet

    exp = client.get(f"/api/sessions/{sid}/export").json()
    assert exp["schema"] == "assessment_result.v1"
    assert exp["session"]["form_id"] == "core-A" and len(exp["takes"]) == 6
    assert (
        "ei_pct_syllables" in exp["metrics"]
        and exp["metrics"]["ei_pct_syllables"]["definition"]["en"]
    )
    assert "test.0.1" in exp["pipeline_versions"]
    assert any(e["skill"] == "speaking" for e in exp["estimates"])
    assert exp["session_results"]["dictation"]["mean_wer"]["clear"] == 0.0

    take_id = next(t["id"] for t in exp["takes"] if t["kind"] == "audio")
    v = client.get(f"/api/takes/{take_id}/viewer").json()
    assert (
        v["audio_url"].endswith("/audio") and len(v["words"]) == 5 and v["words"][0]["start"] == 0.0
    )
    assert "pauses" in v and "nuclei" in v


def test_anchor_scales_and_subject_switch(client: TestClient, db, monkeypatch) -> None:
    from app.main import app

    _fake_engines(monkeypatch)
    base = get_settings()
    # Learner session first (as tester@example.com, the learner).
    app.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"learner_email": "tester@example.com", "anchor_emails": "anchor@example.com"}
    )
    _core_session(client, db)
    # Anchor session on the same form with a worse repetition score.
    app.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={
            "dev_email": "anchor@example.com",
            "learner_email": "tester@example.com",
            "anchor_emails": "anchor@example.com",
        }
    )
    assert client.get("/api/me").json()["role"] == "anchor"
    _fake_engines(monkeypatch, text="the pharmacy closes at")  # 4/5 words
    _core_session(client, db)
    dash = client.get("/api/dashboard").json()  # anchors see the learner by default
    assert dash["subject"]["email"] == "tester@example.com" and dash["viewer"]["role"] == "anchor"
    assert dash["anchors_available"]["core-A"] is True
    ei = {m["id"]: m for m in dash["domains"]["speaking"]}["ei_pct_syllables"]["latest"]
    assert (
        ei["anchor"] is not None and ei["anchor"] < 100 and ei["scale"] == 100.0
    )  # learner beats anchor → capped
    me = client.get("/api/dashboard?subject=me").json()
    assert me["subject"]["email"] == "anchor@example.com"
    other = client.get("/api/dashboard?subject=tester@example.com").json()
    assert other["subject"]["email"] == "tester@example.com"
    # Learners cannot look at other subjects.
    app.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"learner_email": "tester@example.com", "anchor_emails": "anchor@example.com"}
    )
    assert client.get("/api/dashboard?subject=anchor@example.com").status_code == 403


def test_retest_noise_and_calibration() -> None:
    sessions = [
        {
            "form_id": "core-A",
            "started_at": "2026-10-01T10:00:00+00:00",
            "metrics": {"speech_rate": 3.0, "wer_clear": 10.0},
        },
        {
            "form_id": "core-A",
            "started_at": "2026-10-05T10:00:00+00:00",
            "metrics": {"speech_rate": 3.4, "wer_clear": 8.0},
        },
        {
            "form_id": "core-B",
            "started_at": "2026-11-05T10:00:00+00:00",
            "metrics": {"speech_rate": 4.0},
        },
        {
            "form_id": "core-B",
            "started_at": "2027-01-05T10:00:00+00:00",
            "metrics": {"speech_rate": 5.0},
        },  # too far apart
    ]
    noise = metrics.retest_noise(sessions)
    assert noise == {"speech_rate": 0.4, "wer_clear": 2.0}
    pts = [
        {"session_id": "a", "started_at": "1", "value": 3.0, "ci95": None},
        {"session_id": "b", "started_at": "2", "value": 3.3, "ci95": None},
    ]
    assert metrics.trend(pts, noise["speech_rate"])["detectable"] is False
    pts[1]["value"] = 3.6
    assert metrics.trend(pts, noise["speech_rate"])["detectable"] is True

    assert metrics.cefr_from_official("toefl", "speaking", 22) == "B2"
    assert metrics.cefr_from_official("toefl", "reading", 27) == "C1"
    assert metrics.cefr_from_official("ielts", "listening", 6.0) == "B2"
    offs = metrics.calibration_offsets(
        [{"date": "2026-12-01", "test": "toefl", "speaking": 22, "reading": 27}],
        [
            ("2026-10-01T00:00:00", {"speaking": "B1", "reading": "C1"}),
            ("2026-11-20T00:00:00", {"speaking": "B1", "reading": "B2"}),
        ],
    )
    assert offs == {"speaking": 1, "reading": 1}
    est = metrics.apply_offset(
        {
            "skill": "speaking",
            "cefr": "B1",
            "toefl": (16, 19),
            "ielts": (4.0, 5.0),
            "label": "estimate",
        },
        1,
    )
    assert est["cefr"] == "B2" and est["toefl"] == (20, 24) and "calibrated" in est["label"]
    assert metrics.apply_offset({"skill": "speaking", "cefr": None}, 1)["cefr"] is None


def test_dashboard_reports_noise_and_calibration(client: TestClient, db, monkeypatch) -> None:
    _fake_engines(monkeypatch)
    _core_session(client, db)
    _core_session(client, db)  # same form, same day → a test–retest pair
    dash = client.get("/api/dashboard").json()
    assert "ei_pct_syllables" in dash["retest_noise"]
    ei = {m["id"]: m for m in dash["domains"]["speaking"]}["ei_pct_syllables"]
    assert ei["trend"]["noise"] == dash["retest_noise"]["ei_pct_syllables"]
    assert ei["trend"]["detectable"] is False  # identical sittings
    assert dash["calibration"] == {"external": [], "offsets": {}}
