"""M4: item scoring (multiple choice, C-test, reading, AXB), the email checklist, and the
session rollups for the rotating modules."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import processing
from app.pipeline import checklist, items

from .test_pipeline_m1 import _drain, _kinds
from .test_pipeline_m2 import _typed_take


def test_mc_and_vocabulary_summary() -> None:
    r = items.score_mc("2", 2, ["a", "b", "c", "d"])
    assert r["correct"] is True and r["chosen"] == "c"
    assert items.score_mc(None, 0, ["a"])["correct"] is None
    assert items.score_mc("x", 0, ["a"])["answer"] is None
    v = items.vocabulary_summary(
        [
            {"band": "1k", "correct": True},
            {"band": "1k", "correct": True},
            {"band": "2k", "correct": False},
            {"band": "2k", "correct": True},
            {"band": "medical", "correct": True},
        ]
    )
    assert (
        v["size_estimate"] == 1500
        and v["bands_tested"] == ["1k", "2k"]
        and v["medical_pct"] == 100.0
    )
    assert items.comprehension_summary([{"correct": True}, {"correct": None}])["pct"] == 50.0


def test_ctest_scoring() -> None:
    text = "They wo{rry} about pa{in}, or th{ey} think."
    assert items.ctest_blanks(text) == ["rry", "in", "ey"]
    assert items.render_ctest(text) == "They wo____ about pa____, or th____ think."
    r = items.score_ctest(text, ["RRY", "in", "ay"])
    assert (
        r["n"] == 3
        and r["correct"] == 2
        and r["pct"] == 66.7
        and r["blanks"][2]["correct"] is False
    )
    assert items.score_ctest(text, [])["correct"] == 0


def test_reading_and_axb() -> None:
    r = items.reading_speed("one two three four five six", 1000.0, 3000.0)
    assert r.words == 6 and r.reading_time_s == 2.0 and r.wpm == 180.0
    assert items.reading_speed("a b", None, 10.0).wpm is None
    assert items.effective_reading_speed(200.0, 75.0) == 150.0
    a = items.axb_summary(
        [
            items.score_axb("a", "A", "r/l"),
            items.score_axb("B", "A", "r/l"),
            items.score_axb(None, "B", "f/p"),
        ]
    )
    assert a["n"] == 3 and a["correct"] == 1 and a["by_contrast"]["r/l"]["pct"] == 50.0


def test_rotating_modules_processing_and_summary(client: TestClient, db, monkeypatch) -> None:
    from app.engines.claude import Correction

    monkeypatch.setattr(
        processing,
        "minimal_correction",
        lambda text, **_: Correction(text, [text] * 3, [0, 0, 0], 0),
    )
    monkeypatch.setattr(
        checklist,
        "score_goals",
        lambda goals, turns, **_: checklist.ChecklistResult(
            [{"goal": g, "done": i < 2, "votes": 3, "evidence": []} for i, g in enumerate(goals)],
            2,
            len(goals),
            round(2 / len(goals), 3),
            3,
        ),
    )
    # R1 vocabulary: 3 items, two right
    sid = client.post("/api/sessions", json={"form_id": "rotating-R1-A"}).json()["id"]
    for item, ans in (("R1-01", "0"), ("R1-04", "0"), ("R1-31", "2")):
        _typed_take(client, sid, "R1", item, ans)
    client.patch(f"/api/sessions/{sid}", json={"status": "done"})
    _drain(db)
    res = client.get(f"/api/sessions/{sid}/results").json()
    v = res["vocabulary"]["result"]
    assert v["by_band"]["1k"]["pct"] == 100.0 and v["by_band"]["medical"]["pct"] == 0.0
    assert v["size_estimate"] == 2000 and v["bands_tested"] == ["1k", "2k"]

    # R2: passage with reading time, two questions, one c-test text
    sid = client.post("/api/sessions", json={"form_id": "rotating-R2-A"}).json()["id"]
    tid = client.post(
        f"/api/sessions/{sid}/takes",
        json={"task_id": "R2-read", "item_id": "R2-passage", "kind": "typed"},
    ).json()["id"]
    client.post(
        f"/api/takes/{tid}/events",
        json=[
            {"name": "prompt_end", "t_client_ms": 0.0},
            {"name": "submit", "t_client_ms": 90_000.0},
        ],
    )
    client.post(f"/api/takes/{tid}/typed", json={"text": "", "keystrokes": []}).raise_for_status()
    _typed_take(client, sid, "R2-q", "R2-q1", "0")
    _typed_take(client, sid, "R2-q", "R2-q2", "1")
    text = "wo" + "␟".join(
        [
            "rry",
            "in",
            "ey",
            "at",
            "ck-up",
            "ot",
            "ssary",
            "ing",
            "nately",
            "lems",
            "ch",
            "nd",
            "o",
            "an",
            "es",
            "st",
            "mend",
            "sit",
            "ix",
            "en",
        ]
    )
    _typed_take(
        client, sid, "R2-ctest", "R2-c1", text[2:]
    )  # 20 answers, last one wrong on purpose? all right except 'thing' missing
    client.patch(f"/api/sessions/{sid}", json={"status": "done"})
    _drain(db)
    res = client.get(f"/api/sessions/{sid}/results").json()
    rd = res["reading"]["result"]["R2-passage"]
    assert rd["reading_time_s"] == 90.0 and 150 < rd["wpm"] < 200
    assert rd["comprehension_pct"] == 50.0 and rd["effective_wpm"] == round(rd["wpm"] * 0.5, 1)
    assert res["comprehension"]["result"]["R2-q"]["correct"] == 1
    assert res["comprehension"]["result"]["R2-q"]["genre"] == "patient_information"
    ct = res["c_test"]["result"]
    assert ct["n"] == 21 and ct["correct"] == 20

    # R3: AXB two items; R4: email with checklist
    sid = client.post("/api/sessions", json={"form_id": "rotating-R3-A"}).json()["id"]
    _typed_take(client, sid, "R3-axb", "R3-axb-01", "B")
    _typed_take(client, sid, "R3-axb", "R3-axb-03", "A")
    client.patch(f"/api/sessions/{sid}", json={"status": "done"})
    _drain(db)
    ax = client.get(f"/api/sessions/{sid}/results").json()["axb"]["result"]
    assert ax["pct"] == 50.0 and ax["by_contrast"]["f/p"]["correct"] == 0

    sid = client.post("/api/sessions", json={"form_id": "rotating-R4-A"}).json()["id"]
    tid = _typed_take(
        client,
        sid,
        "R4-email",
        "R4-email-1",
        "Dear clinic, this is Mina. Could you send my blood test results from last week? Thank you.",
    )
    client.patch(f"/api/sessions/{sid}", json={"status": "done"})
    _drain(db)
    k = _kinds(db, tid)
    assert k["checklist"]["done"] == 2 and k["checklist"]["total"] == 6
    assert "typing" in k and "lexical" in k and "errors" in k
    res = client.get(f"/api/sessions/{sid}/results").json()
    assert res["email"]["result"]["completion"] == round(2 / 6, 3)
