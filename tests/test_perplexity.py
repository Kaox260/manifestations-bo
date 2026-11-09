import dataclasses
import json
import uuid

import pytest
import requests

from app.services import perplexity as px

SID = uuid.uuid4()
SRC = {"id": SID, "platform": "web", "url": "https://example.org/a", "title": "t"}
GOOD = {
    "source_id": str(uuid.uuid4()), "event_type": "arrest", "occurred_on": "2026-03-01",
    "city": "Paris", "description": "d", "actors": ["police"], "victims": ["protester"],
    "verification_status": "alleged", "confidence": 3,
    "source_urls": ["https://example.org/a"], "needs_human_review": True,
}


def wrap(content):
    return {"choices": [{"message": {"content": content}}]}


class FakeResp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text
        self.ok = status < 400

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setattr(px, "settings", dataclasses.replace(px.settings, perplexity_api_key="SECRET-KEY"))


def test_payload():
    p = px.build_analysis_payload(SRC, "trans", "ocr", ["c1"])
    assert p["model"] == "sonar" and p["messages"][0]["content"] == px.SYSTEM_PROMPT
    schema = p["response_format"]["json_schema"]["schema"]
    assert "publishable" not in schema["properties"]
    assert set(schema["required"]) >= {"source_id", "city", "confidence"}
    assert str(SID) in p["messages"][1]["content"] and "trans" in p["messages"][1]["content"]


def test_parse_ok_and_fence_and_source_override():
    ev = px.parse_perplexity_response(wrap("```json\n" + json.dumps(GOOD) + "\n```"), source_id=SID)
    assert ev.source_id == SID and ev.needs_human_review


def test_parse_errors():
    with pytest.raises(px.PerplexityResponseError):
        px.parse_perplexity_response({})
    with pytest.raises(px.PerplexityResponseError):
        px.parse_perplexity_response(wrap("pas du json"))
    with pytest.raises(px.PerplexityResponseError):
        px.parse_perplexity_response(wrap("[1]"))
    with pytest.raises(px.PerplexityValidationError) as e:
        px.parse_perplexity_response(wrap(json.dumps(GOOD | {"verification_status": "official", "confidence": 1})))
    assert e.value.errors


def test_call_ok_and_header(key, monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, headers=headers, timeout=timeout)
        return FakeResp(body=wrap("{}"))

    monkeypatch.setattr(px.requests, "post", fake_post)
    assert px.call_perplexity({"x": 1}) == wrap("{}")
    assert seen["url"] == "https://api.perplexity.ai/chat/completions" and seen["timeout"] == 120
    assert seen["headers"]["Authorization"] == "Bearer SECRET-KEY"


def test_call_errors_do_not_leak_key(key, monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("Bearer SECRET-KEY failed")

    monkeypatch.setattr(px.requests, "post", boom)
    with pytest.raises(px.PerplexityHTTPError) as e:
        px.call_perplexity({})
    assert "SECRET-KEY" not in str(e.value)

    monkeypatch.setattr(px.requests, "post", lambda *a, **k: FakeResp(429, text="rate"))
    with pytest.raises(px.PerplexityHTTPError) as e:
        px.call_perplexity({})
    assert e.value.status_code == 429

    monkeypatch.setattr(px.requests, "post", lambda *a, **k: FakeResp(200, body=None))
    with pytest.raises(px.PerplexityResponseError):
        px.call_perplexity({})


def test_missing_key(monkeypatch):
    monkeypatch.setattr(px, "settings", dataclasses.replace(px.settings, perplexity_api_key=""))
    with pytest.raises(px.PerplexityConfigError):
        px.call_perplexity({})
