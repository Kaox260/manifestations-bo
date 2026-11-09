import dataclasses
import json
import sys
import types
import uuid

import pytest
from sqlalchemy import select

from app.models import Base, Event, EventSource, Source, Task
from app.services import analysis, ocr, perplexity as px, whisper


def event_json(**over):
    return {
        "source_id": str(uuid.uuid4()), "event_type": "arrest", "occurred_on": "2026-03-01",
        "city": "Paris", "description": "d", "actors": ["police"], "victims": ["protester"],
        "verification_status": "alleged", "confidence": 3,
        "source_urls": ["https://example.org/a"], "needs_human_review": False,
    } | over


def fake_api(monkeypatch, content, seen=None):
    def call(payload):
        if seen is not None:
            seen.append(payload)
        if isinstance(content, Exception):
            raise content
        return {"choices": [{"message": {"content": json.dumps(content)}}]}

    monkeypatch.setattr(analysis, "call_model", call)


def setup(db, **meta):
    src = Source(platform="web", url="https://example.org/a", raw_metadata=meta or None)
    db.add(src)
    db.flush()
    task = Task(task_type="analyze_source", status="running", payload={"source_id": str(src.id)})
    db.add(task)
    db.commit()
    return src, task


def test_create_then_update_and_force_review(db, monkeypatch):
    src, task = setup(db, transcript="bonjour", comments=["c1"])
    seen = []
    fake_api(monkeypatch, event_json(), seen)
    ev = analysis.analyze_source(src.id, db=db)
    assert ev.source_id == src.id and ev.needs_review is True  # forcé malgré needs_human_review=False
    assert "bonjour" in seen[0]["messages"][1]["content"]
    assert db.get(Task, task.id).status == "done" and db.get(Task, task.id).result["action"] == "created"
    assert len(db.scalars(select(EventSource)).all()) == 1

    # relance : mise à jour, pas de doublon
    task2 = Task(task_type="analyze_source", status="running", payload={"source_id": str(src.id)})
    db.add(task2); db.commit()
    fake_api(monkeypatch, event_json(description="nouvelle"))
    ev2 = analysis.analyze_source(src.id, task_id=task2.id, db=db)
    assert ev2.id == ev.id and ev2.description == "nouvelle"
    assert db.get(Task, task2.id).result["action"] == "updated"
    assert len(db.scalars(select(Event)).all()) == 1


def test_validated_event_not_overwritten(db, monkeypatch):
    src, _ = setup(db)
    fake_api(monkeypatch, event_json())
    ev = analysis.analyze_source(src.id, db=db)
    ev.status = "validated"; db.commit()
    t = Task(task_type="analyze_source", status="running", payload={"source_id": str(src.id)})
    db.add(t); db.commit()
    fake_api(monkeypatch, event_json(description="écrase"))
    ev2 = analysis.analyze_source(src.id, db=db)
    assert ev2.description == "d" and db.get(Task, t.id).result["action"] == "kept"


def test_failures_mark_task_failed(db, monkeypatch):
    src, task = setup(db)
    fake_api(monkeypatch, px.PerplexityHTTPError("boom", 500))
    assert analysis.analyze_source(src.id, db=db) is None
    t = db.get(Task, task.id)
    assert t.status == "failed" and "boom" in t.error

    t2 = Task(task_type="analyze_source", status="running", payload={"source_id": str(src.id)})
    db.add(t2); db.commit()
    fake_api(monkeypatch, event_json(verification_status="official", confidence=1))
    assert analysis.analyze_source(src.id, task_id=t2.id, db=db) is None
    assert db.get(Task, t2.id).status == "failed"

    t3 = Task(task_type="analyze_source", status="running", payload={"source_id": str(uuid.uuid4())})
    db.add(t3); db.commit()
    assert analysis.analyze_source(uuid.UUID(t3.payload["source_id"]), db=db) is None
    assert db.get(Task, t3.id).error == "source not found"


def test_media_inputs_cached(db, monkeypatch, tmp_path):
    audio = tmp_path / "a.wav"; audio.write_bytes(b"x")
    shot = tmp_path / "s.png"; shot.write_bytes(b"x")
    src, _ = setup(db, audio_path=str(audio))
    src.screenshot_path = str(shot); db.commit()
    monkeypatch.setattr(whisper, "transcribe_audio", lambda p: {"text": "tx", "language": "fr", "duration": 1})
    monkeypatch.setattr(ocr, "ocr_image", lambda p: "texte ocr")
    fake_api(monkeypatch, event_json())
    analysis.analyze_source(src.id, db=db)
    assert db.get(Source, src.id).raw_metadata["transcript"] == "tx"
    assert db.get(Source, src.id).raw_metadata["ocr_text"] == "texte ocr"


def test_ocr_clean():
    assert ocr.clean_text("  a   b \n\n\t c\t\td  \n") == "a b\nc d"


def test_ocr_none_when_empty(monkeypatch):
    fake_pt = types.SimpleNamespace(image_to_string=lambda img, lang: " \n ")
    class Img:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    fake_pil = types.SimpleNamespace(Image=types.SimpleNamespace(open=lambda p: Img()))
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pt)
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    assert ocr.ocr_image("x.png") is None


def test_whisper_limits_duration(monkeypatch):
    seg = lambda s, t: types.SimpleNamespace(start=s, text=f" {t} ")
    class Model:
        def transcribe(self, path, **kw):
            assert kw["language"] == "fr" and kw["clip_timestamps"] == [0.0, 10.0]
            return iter([seg(0, "un"), seg(5, "deux"), seg(11, "trois")]), types.SimpleNamespace(duration=60.0)
    monkeypatch.setattr(whisper, "_get_model", lambda name: Model())
    monkeypatch.setattr(whisper, "settings", dataclasses.replace(whisper.settings, max_video_duration_seconds=10))
    assert whisper.transcribe_audio("f.mp4") == {"text": "un deux", "language": "fr", "duration": 10.0}
