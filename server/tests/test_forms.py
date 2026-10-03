from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.content import Form, load_form, load_forms

CONTENT = Path(__file__).resolve().parents[2] / "content"


def test_all_forms_in_content_validate() -> None:
    forms = load_forms(CONTENT)
    assert "dummy-v0" in forms
    for f in forms.values():
        assert f.title.en and f.title.ko
        for t in f.tasks:
            assert t.instructions.en and t.instructions.ko


def test_dummy_form_shape() -> None:
    f = load_form(CONTENT / "forms" / "dummy-v0.yaml")
    assert [t.type for t in f.tasks] == ["read_aloud", "typed_response"]
    assert f.tasks[0].timing.max_s >= f.tasks[0].timing.respond_s


def test_form_validation_rejects_bad_items() -> None:
    bad = {
        "id": "x",
        "version": 1,
        "kind": "dummy",
        "title": {"en": "x", "ko": "x"},
        "tasks": [
            {
                "id": "T",
                "type": "read_aloud",
                "title": {"en": "t", "ko": "t"},
                "instructions": {"en": "i", "ko": "i"},
                "timing": {"respond_s": 5},
                "items": [{"id": "T-1", "prompt": {"en": "no text", "ko": "x"}}],
            }
        ],
    }
    with pytest.raises(ValueError):
        Form.model_validate(bad)


def test_forms_api(client: TestClient) -> None:
    r = client.get("/api/forms")
    assert r.status_code == 200
    ids = [f["id"] for f in r.json()]
    assert "dummy-v0" in ids
    r = client.get("/api/forms/dummy-v0")
    assert r.status_code == 200
    assert r.json()["tasks"][0]["items"][0]["text"].startswith("The pharmacist")
    assert client.get("/api/forms/nope").status_code == 404


def test_task_level_audio_is_served(client: TestClient) -> None:
    r = client.get("/api/forms/e2e-core/audio/audio/e2e-core/clip.wav")
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    assert client.get("/api/forms/e2e-core/audio/audio/e2e-core/nope.wav").status_code == 404
