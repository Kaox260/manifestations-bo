import uuid

import sys

import pytest
from sqlalchemy import select

from app.models import Base, Source, Task
from app.services import tiktok as tk


def test_search_url():
    assert tk.build_search_url(" manifestation Paris ") == (
        "https://www.tiktok.com/search/video?q=manifestation+Paris"
    )


def test_normalize():
    n = "https://www.tiktok.com/@user/video/123"
    assert tk.normalize_video_url("https://tiktok.com/@User/video/123?lang=fr#x") == n
    assert tk.normalize_video_url("https://m.tiktok.com/@user/video/123/") == n
    assert tk.normalize_video_url("https://evil.com/@user/video/123") is None
    assert tk.normalize_video_url("https://www.tiktok.com/@user") is None
    assert tk.normalize_video_url("https://nottiktok.com/@u/video/1") is None


def test_relevance():
    assert tk.is_relevant({"title": "Grande MANIFESTATION à Lyon"}, "manifestation")
    assert tk.is_relevant({"raw_text": "défilé"}, "defile")
    assert not tk.is_relevant({"title": "recette"}, "manifestation")
    assert not tk.is_relevant({}, "manifestation")


def test_save_dedup_and_task(db):
    url = "https://www.tiktok.com/@u/video/9?x=1"
    s = tk.save_source_if_new(url, {"title": "t", "author": "u"}, db=db)
    assert s and s.url == "https://www.tiktok.com/@u/video/9" and s.platform == "tiktok"
    assert tk.save_source_if_new("https://tiktok.com/@U/video/9", {}, db=db) is None
    with pytest.raises(ValueError):
        tk.save_source_if_new("https://example.org", {}, db=db)
    t = tk.create_analysis_task(s.id, db=db)
    assert t.payload == {"source_id": str(s.id)} and t.task_type == "analyze_source"
    assert db.scalars(select(Task)).all()[0].id == t.id


def test_discovery_never_crashes(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    r = tk.discover_tiktok_urls("x")  # DISPLAY absent ou playwright manquant -> loggé
    assert r.urls == []
    assert tk.extract_page_metadata("https://www.tiktok.com/@u/video/1") == {}
    assert tk.run_tiktok_discovery("x")["found"] == 0
