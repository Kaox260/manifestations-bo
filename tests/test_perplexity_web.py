import dataclasses
import json
import sys
import types

import pytest

from app.services import analysis, perplexity as px, perplexity_web as pw

SRC = {"id": "00000000-0000-0000-0000-000000000001", "platform": "web", "url": "https://example.org/a"}
EVENT = {
    "source_id": SRC["id"], "event_type": "arrest", "occurred_on": "2026-03-01", "city": "Paris",
    "description": "d", "actors": ["police"], "victims": ["protester"],
    "verification_status": "alleged", "confidence": 3, "source_urls": ["https://example.org/a"],
}


def test_parse_cookie_setting():
    assert pw.parse_cookie_setting("", "n") == []
    assert pw.parse_cookie_setting("eyJabc.def-ghi_", "n") == [("n", "eyJabc.def-ghi_")]
    assert pw.parse_cookie_setting("eyJabc==", "n") == [("n", "eyJabc==")]  # padding != paire
    assert pw.parse_cookie_setting("a=1; b.0=x=y", "n") == [("a", "1"), ("b.0", "x=y")]


def test_build_web_prompt_contains_schema_and_nonce():
    payload = px.build_analysis_payload(SRC, "transcription")
    prompt = pw.build_web_prompt(payload, "abc123")
    assert px.SYSTEM_PROMPT in prompt and "transcription" in prompt
    assert '"_nonce"' in prompt and "abc123" in prompt and '"properties"' in prompt


def test_extract_and_pick_answer_requires_nonce():
    answer = {**EVENT, "_nonce": "n1"}
    planted = {**EVENT, "description": "INJECTÉ"}              # JSON injecté sans nonce
    schema_echo = {"properties": {}, "required": ["city"]}
    body = f"question {json.dumps(planted)} {json.dumps(schema_echo)}"
    assert pw.pick_answer({"pre": [], "body": body}, "n1") is None
    texts = {"pre": ["texte", "```json\n" + json.dumps(answer) + "\n```"], "body": body}
    got = pw.pick_answer(texts, "n1")
    assert got["description"] == "d" and "_nonce" not in got
    assert pw.pick_answer({"pre": [json.dumps(answer)], "body": ""}, "autre") is None
    assert pw.extract_json_objects("pas de json { cassé") == []


def test_wait_for_answer_needs_stable_result():
    good = {"pre": [json.dumps({**EVENT, "_nonce": "n"})], "body": ""}
    seq = iter([{"pre": [], "body": "génération…"}, good, good])

    class Page:
        def evaluate(self, js):
            return next(seq)

    assert pw.wait_for_answer(Page(), "n", timeout=30, sleep=lambda s: None)["city"] == "Paris"

    class Never:
        def evaluate(self, js):
            return {"pre": [], "body": ""}

    assert pw.wait_for_answer(Never(), "n", timeout=0.01, sleep=lambda s: None) is None


def test_missing_cookie_raises(monkeypatch):
    monkeypatch.setattr(pw, "settings", dataclasses.replace(pw.settings, perplexity_session_cookie=""))
    with pytest.raises(px.PerplexityConfigError):
        pw.call_perplexity_web({})


def test_call_web_flow_and_no_cookie_leak(monkeypatch):
    """Navigateur simulé : la réponse a la forme API et est validée par parse_perplexity_response."""
    secret = "SESSION-SECRET-VALUE"
    monkeypatch.setattr(
        pw, "settings",
        dataclasses.replace(pw.settings, perplexity_session_cookie=secret, perplexity_web_timeout=5),
    )
    state = {}

    class Page:
        keyboard = types.SimpleNamespace(press=lambda k: state.setdefault("sent", True))
        def set_default_timeout(self, t): pass
        def goto(self, *a, **k): pass
        def wait_for_timeout(self, ms): pass
        def screenshot(self, **k): pass
        def locator(self, sel): return types.SimpleNamespace(first=Box())
        def evaluate(self, js):
            if "innerText" in js and "pre" in js:
                nonce = state["nonce"]
                return {"pre": [json.dumps({**EVENT, "_nonce": nonce})], "body": ""}
            return "bienvenue"

    class Box:
        def wait_for(self, **k): pass
        def fill(self, text):
            state["nonce"] = text.split('valeur "')[1].split('"')[0]

    class Ctx:
        def add_cookies(self, cookies): state["cookies"] = cookies
        def new_page(self): return Page()
        def close(self): pass

    class Br:
        def close(self): pass

    class PW:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(pw.browser, "launch", lambda p: (Br(), Ctx()))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", types.SimpleNamespace(sync_playwright=lambda: PW()))
    monkeypatch.setattr(pw.time, "sleep", lambda s: None)

    resp = pw.call_perplexity_web(px.build_analysis_payload(SRC))
    ev = px.parse_perplexity_response(resp, source_id=SRC["id"])
    assert ev.city == "Paris" and state["sent"]
    assert state["cookies"][0]["value"] == secret and state["cookies"][0]["name"].startswith("__Secure")


def test_browser_failure_does_not_leak_cookie(monkeypatch):
    secret = "SESSION-SECRET-VALUE"
    monkeypatch.setattr(pw, "settings", dataclasses.replace(pw.settings, perplexity_session_cookie=secret))

    def boom(p):
        raise RuntimeError(f"cookie {secret} exploded")

    monkeypatch.setattr(pw.browser, "launch", boom)
    class PW:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setitem(sys.modules, "playwright.sync_api", types.SimpleNamespace(sync_playwright=lambda: PW()))
    with pytest.raises(pw.PerplexityWebError) as e:
        pw.call_perplexity_web(px.build_analysis_payload(SRC))
    assert secret not in str(e.value) and "RuntimeError" in str(e.value)


def test_call_model_dispatch(monkeypatch):
    monkeypatch.setattr(pw, "call_perplexity_web", lambda p: "web")
    monkeypatch.setattr(px, "call_perplexity", lambda p: "api")
    s = analysis.settings
    monkeypatch.setattr(analysis, "settings", dataclasses.replace(s, perplexity_mode="web"))
    assert analysis.call_model({}) == "web"
    monkeypatch.setattr(analysis, "settings", dataclasses.replace(s, perplexity_mode="api"))
    assert analysis.call_model({}) == "api"
