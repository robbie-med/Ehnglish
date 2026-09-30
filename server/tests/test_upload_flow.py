import hashlib
import struct
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import worker
from app.config import get_settings
from app.models import Job, ProcessingResult, Take

from .conftest import make_wav


def _session(client: TestClient) -> str:
    r = client.post(
        "/api/sessions",
        json={
            "form_id": "dummy-v0",
            "setup": {"sleep": 7, "stress": 2, "mood": 4},
            "client": {"ua": "t"},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _audio_take(client: TestClient, sid: str, item="D1-01", attempt=1, sr=48000) -> str:
    r = client.post(
        f"/api/sessions/{sid}/takes",
        json={
            "task_id": "D1",
            "item_id": item,
            "attempt": attempt,
            "kind": "audio",
            "sample_rate": sr,
            "channels": 1,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload(client: TestClient, take_id: str, data: bytes, chunk=64 * 1024) -> int:
    n = 0
    for i in range(0, len(data), chunk):
        r = client.put(
            f"/api/takes/{take_id}/chunks/{n}",
            content=data[i : i + chunk],
            headers={"Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 200, r.text
        n += 1
    return n


def test_full_audio_flow_with_worker(client: TestClient, db) -> None:
    sid = _session(client)
    tid = _audio_take(client, sid)
    data = make_wav(seconds=1.5)
    n = _upload(client, tid, data)
    assert n > 1
    st = client.get(f"/api/takes/{tid}/upload-status").json()
    assert st["received"] == list(range(n))

    client.post(
        f"/api/takes/{tid}/events",
        json=[
            {"name": "prompt_end", "t_client_ms": 1000.0},
            {"name": "record_start", "t_client_ms": 1000.5},
            {"name": "record_stop", "t_client_ms": 2500.5},
        ],
    ).raise_for_status()

    r = client.post(
        f"/api/takes/{tid}/finalize",
        json={
            "sha256": hashlib.sha256(data).hexdigest(),
            "chunk_count": n,
            "quality": {"rms_dbfs": -9.0, "clip_count": 0},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "finalized"
    assert abs(body["duration_s"] - 1.5) < 1e-3
    assert body["quality"]["rms_dbfs"] == -9.0
    assert [e["name"] for e in body["events"]] == ["prompt_end", "record_start", "record_stop"]

    raw = get_settings().raw_dir
    wav_path = raw / body["wav_path"]
    assert wav_path.is_file() and wav_path.read_bytes() == data
    assert not (raw / "uploads" / tid).exists()  # parts cleaned up

    # The stub job was queued and the worker processes it, stamping the pipeline version.
    job = db.scalar(select(Job).where(Job.type == "wav_probe"))
    assert job is not None and job.status == "queued"
    done = worker.run_once(db)
    assert done is not None and done.status == "done", done.last_error
    res = db.scalar(
        select(ProcessingResult).where(ProcessingResult.take_id == done.payload["take_id"] and True)
    )
    assert res is not None
    assert res.pipeline_version == "test.0.1"
    assert abs(res.result["duration_s"] - 1.5) < 1e-3
    assert -10 < res.result["rms_dbfs"] < -8  # 0.5 amplitude sine ≈ -9 dBFS
    assert res.result["clip_count"] == 0
    assert worker.run_once(db) is None  # queue drained

    t = client.get(f"/api/takes/{tid}").json()
    assert t["status"] == "processed"
    assert t["results"][0]["kind"] == "wav_probe"

    a = client.get(f"/api/takes/{tid}/audio")
    assert a.status_code == 200 and a.content[:4] == b"RIFF"

    s = client.get(f"/api/sessions/{sid}").json()
    assert len(s["takes"]) == 1 and s["setup"]["sleep"] == 7


def test_finalize_rejects_sha_mismatch(client: TestClient) -> None:
    sid = _session(client)
    tid = _audio_take(client, sid)
    data = make_wav(0.2)
    n = _upload(client, tid, data)
    r = client.post(f"/api/takes/{tid}/finalize", json={"sha256": "0" * 64, "chunk_count": n})
    assert r.status_code == 400 and "sha256" in r.json()["detail"]
    assert client.get(f"/api/takes/{tid}").json()["status"] == "failed"


def test_finalize_rejects_missing_chunks(client: TestClient) -> None:
    sid = _session(client)
    tid = _audio_take(client, sid)
    data = make_wav(0.2)
    n = _upload(client, tid, data)
    r = client.post(
        f"/api/takes/{tid}/finalize",
        json={"sha256": hashlib.sha256(data).hexdigest(), "chunk_count": n + 2},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["missing"] == [n, n + 1]
    # Still resumable: upload status is unchanged and take still uploading.
    assert client.get(f"/api/takes/{tid}/upload-status").json()["status"] == "uploading"


def test_finalize_rejects_non_wav_and_header_mismatch(client: TestClient) -> None:
    sid = _session(client)
    tid = _audio_take(client, sid)
    junk = b"not a wav" * 1000
    n = _upload(client, tid, junk)
    r = client.post(
        f"/api/takes/{tid}/finalize",
        json={"sha256": hashlib.sha256(junk).hexdigest(), "chunk_count": n},
    )
    assert r.status_code == 400 and "invalid WAV" in r.json()["detail"]

    tid2 = _audio_take(client, sid, attempt=2, sr=44100)
    data = make_wav(0.2, sample_rate=48000)
    n = _upload(client, tid2, data)
    r = client.post(
        f"/api/takes/{tid2}/finalize",
        json={"sha256": hashlib.sha256(data).hexdigest(), "chunk_count": n},
    )
    assert r.status_code == 400 and "does not match" in r.json()["detail"]


def test_rerecord_supersedes_previous_attempt(client: TestClient, db) -> None:
    sid = _session(client)
    t1 = _audio_take(client, sid, attempt=1)
    t2 = _audio_take(client, sid, attempt=2)
    statuses = {str(t.id): t.status for t in db.scalars(select(Take)).all()}
    assert statuses[t1] == "rejected" and statuses[t2] == "uploading"
    # Same attempt twice is a conflict.
    r = client.post(
        f"/api/sessions/{sid}/takes",
        json={
            "task_id": "D1",
            "item_id": "D1-01",
            "attempt": 2,
            "kind": "audio",
            "sample_rate": 48000,
            "channels": 1,
        },
    )
    assert r.status_code == 409


def test_take_validation(client: TestClient) -> None:
    sid = _session(client)
    r = client.post(
        f"/api/sessions/{sid}/takes",
        json={
            "task_id": "D1",
            "item_id": "nope",
            "kind": "audio",
            "sample_rate": 48000,
            "channels": 1,
        },
    )
    assert r.status_code == 400
    r = client.post(
        f"/api/sessions/{sid}/takes", json={"task_id": "D1", "item_id": "D1-01", "kind": "typed"}
    )
    assert r.status_code == 400  # D1 is audio
    r = client.post(
        f"/api/sessions/{sid}/takes", json={"task_id": "D1", "item_id": "D1-01", "kind": "audio"}
    )
    assert r.status_code == 400  # missing sample rate


def test_typed_response_writes_keystroke_log(client: TestClient) -> None:
    sid = _session(client)
    r = client.post(
        f"/api/sessions/{sid}/takes", json={"task_id": "D2", "item_id": "D2-01", "kind": "typed"}
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    keys = [
        {"t": 10.0, "type": "down", "key": "H", "code": "KeyH"},
        {"t": 60.0, "type": "input", "len": 1},
        {"t": 70.0, "type": "up", "key": "H", "code": "KeyH"},
    ]
    r = client.post(
        f"/api/takes/{tid}/typed", json={"text": "Hi, I'd like to reschedule.", "keystrokes": keys}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "finalized" and body["keystroke_count"] == 3
    assert body["text"].startswith("Hi")
    log = Path(get_settings().raw_dir) / f"sessions/{sid}/D2_D2-01_a1_{tid}.keys.jsonl"
    lines = log.read_text().splitlines()
    assert len(lines) == 3 and '"code": "KeyH"' in lines[0]
    # A second submit is refused; chunks are refused for typed takes.
    assert client.post(f"/api/takes/{tid}/typed", json={"text": "x"}).status_code == 409
    assert client.put(f"/api/takes/{tid}/chunks/0", content=b"abc").status_code == 400


def test_session_close_and_isolation(client: TestClient) -> None:
    sid = _session(client)
    r = client.patch(f"/api/sessions/{sid}", json={"status": "done", "setup": {"note": "ok"}})
    assert r.status_code == 200 and r.json()["finished_at"] and r.json()["setup"]["note"] == "ok"
    # Closed sessions take no more takes.
    r = client.post(
        f"/api/sessions/{sid}/takes", json={"task_id": "D2", "item_id": "D2-01", "kind": "typed"}
    )
    assert r.status_code == 409
    # Another user cannot see it.
    from app.main import app

    base = get_settings()
    app.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"dev_email": "other@example.com"}
    )
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    assert client.get("/api/sessions").json() == []


def test_wav_header_parser_edge_cases() -> None:
    from app import wav

    data = make_wav(0.01, sample_rate=16000)
    info = wav.parse_header(data[:64])
    assert (info.sample_rate, info.channels, info.bits_per_sample) == (16000, 1, 16)
    assert abs(info.duration_s - 0.01) < 1e-6
    # LIST chunk between fmt and data is tolerated.
    extra = b"LIST" + struct.pack("<I", 4) + b"INFO"
    with_list = data[:36] + extra + data[36:]
    assert wav.parse_header(with_list[:80]).data_offset == 44 + 12
    for bad in (b"RIFX" + data[4:], data[:20], b"x" * 44):
        try:
            wav.parse_header(bad)
        except wav.WavError:
            pass
        else:
            raise AssertionError("expected WavError")
