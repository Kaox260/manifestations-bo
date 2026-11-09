import uuid

import pytest

from app.services import perplexity as px


# ----------------------------------------------------------------- helpers
def make_source(client, headers, url="https://example.org/a"):
    r = client.post("/sources", json={"platform": "web", "url": url}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def event_body(source_id, **over):
    return {
        "source_id": source_id, "event_type": "arrest", "occurred_on": "2026-03-01",
        "city": "Paris", "description": "d", "actors": ["police"], "victims": ["protester"],
        "verification_status": "alleged", "confidence": 3,
        "source_urls": ["https://example.org/a"], "needs_human_review": False,
    } | over


def make_event(client, headers, source_id, **over):
    return client.post("/events", json=event_body(source_id, **over), headers=headers)


# ----------------------------------------------------------------- sources
def test_create_source(client, auth_headers):
    r = client.post(
        "/sources",
        json={"platform": "tiktok", "url": "https://www.tiktok.com/@u/video/1", "title": "t"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["platform"] == "tiktok" and body["reliability"] == "unknown"
    assert client.get(f"/sources/{body['id']}").json()["title"] == "t"
    assert [s["id"] for s in client.get("/sources").json()] == [body["id"]]
    assert client.get(f"/sources/{uuid.uuid4()}").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"platform": "myspace", "url": "https://example.org"},
        {"platform": "web", "url": "pas une url"},
        {"platform": "web"},
    ],
)
def test_create_source_invalid(client, auth_headers, body):
    assert client.post("/sources", json=body, headers=auth_headers).status_code == 422


# ----------------------------------------------------------------- création d'événements
def test_create_valid_event(client, auth_headers):
    sid = make_source(client, auth_headers)
    r = make_event(client, auth_headers, sid)
    assert r.status_code == 201, r.text
    ev = r.json()
    assert ev["city"] == "Paris" and ev["event_type"] == "arrest"
    assert ev["confidence"] == 3 and ev["status"] == "pending" and ev["needs_review"] is False
    assert client.get(f"/events/{ev['id']}").json()["id"] == ev["id"]


def test_event_needs_review_by_default(client, auth_headers):
    sid = make_source(client, auth_headers)
    body = event_body(sid)
    del body["needs_human_review"]
    r = client.post("/events", json=body, headers=auth_headers)
    assert r.status_code == 201 and r.json()["needs_review"] is True


def test_event_unknown_source_rejected(client, auth_headers):
    assert make_event(client, auth_headers, str(uuid.uuid4())).status_code == 422


@pytest.mark.parametrize("confidence", [-1, 6, 100])
def test_event_invalid_confidence_rejected(client, auth_headers, confidence):
    sid = make_source(client, auth_headers)
    assert make_event(client, auth_headers, sid, confidence=confidence).status_code == 422


@pytest.mark.parametrize("confidence", [0, 3])
def test_official_requires_confidence_4(client, auth_headers, confidence):
    sid = make_source(client, auth_headers)
    r = make_event(client, auth_headers, sid, verification_status="official", confidence=confidence)
    assert r.status_code == 422
    assert make_event(client, auth_headers, sid, verification_status="official", confidence=4).status_code == 201


def test_unverified_requires_confidence_max_2(client, auth_headers):
    sid = make_source(client, auth_headers)
    assert make_event(client, auth_headers, sid, verification_status="unverified", confidence=3).status_code == 422
    assert make_event(client, auth_headers, sid, verification_status="unverified", confidence=2).status_code == 201


# ----------------------------------------------------------------- lecture / filtres
def test_list_events_and_pagination(client, auth_headers):
    sid = make_source(client, auth_headers)
    for _ in range(3):
        make_event(client, auth_headers, sid)
    assert len(client.get("/events").json()) == 3
    assert len(client.get("/events", params={"limit": 2}).json()) == 2
    assert len(client.get("/events", params={"limit": 2, "offset": 2}).json()) == 1
    assert client.get(f"/events/{uuid.uuid4()}").status_code == 404


def test_filter_events_by_city_and_type(client, auth_headers):
    sid = make_source(client, auth_headers)
    make_event(client, auth_headers, sid, city="Paris", event_type="arrest")
    make_event(client, auth_headers, sid, city="Paris", event_type="property_damage")
    make_event(client, auth_headers, sid, city="Lyon", event_type="arrest")

    def count(**params):
        return len(client.get("/events", params=params).json())

    assert count(city="Paris") == 2
    assert count(event_type="arrest") == 2
    assert count(city="Paris", event_type="arrest") == 1
    assert count(city="Marseille") == 0


def test_filter_events_by_date_and_confidence(client, auth_headers):
    sid = make_source(client, auth_headers)
    make_event(client, auth_headers, sid, occurred_on="2026-01-10", confidence=1)
    make_event(client, auth_headers, sid, occurred_on="2026-03-10", confidence=4)
    count = lambda **p: len(client.get("/events", params=p).json())
    assert count(date_from="2026-02-01") == 1
    assert count(date_to="2026-02-01") == 1
    assert count(min_confidence=3) == 1


# ----------------------------------------------------------------- geojson
def test_geojson_only_publishable(client, auth_headers):
    sid = make_source(client, auth_headers)
    make_event(client, auth_headers, sid)                                           # ville approx.
    make_event(client, auth_headers, sid, city="Lyon", latitude=45.0, longitude=4.0)  # exact
    make_event(client, auth_headers, sid, needs_human_review=True)                  # exclu
    make_event(client, auth_headers, sid, confidence=2)                             # exclu
    make_event(client, auth_headers, sid, city="Villeinconnue")                     # non localisable

    r = client.get("/events.geojson")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection" and len(body["features"]) == 2
    by_city = {f["properties"]["city"]: f for f in body["features"]}
    paris, lyon = by_city["Paris"], by_city["Lyon"]
    assert paris["type"] == "Feature" and paris["geometry"]["type"] == "Point"
    assert paris["properties"]["geo_precision"] == "city"
    assert paris["properties"]["verification_status"] == "alleged"
    assert paris["properties"]["sources_count"] == 1
    assert lyon["geometry"]["coordinates"] == [4.0, 45.0]
    assert lyon["properties"]["geo_precision"] == "exact"


def test_geojson_empty(client):
    assert client.get("/events.geojson").json() == {"type": "FeatureCollection", "features": []}


def test_map_page_served(client):
    r = client.get("/static/map.html")
    assert r.status_code == 200 and "leaflet" in r.text.lower()


# ----------------------------------------------------------------- PATCH événement
def test_patch_event(client, auth_headers):
    sid = make_source(client, auth_headers)
    ev = make_event(client, auth_headers, sid, verification_status="official", confidence=4).json()
    url = f"/events/{ev['id']}"
    r = client.patch(url, json={"status": "validated", "location_raw": "pl. X"}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "validated"
    assert client.patch(url, json={"confidence": 2}, headers=auth_headers).status_code == 422
    assert client.patch(url, json={"city": "X"}, headers=auth_headers).status_code == 422
    assert client.patch(f"/events/{uuid.uuid4()}", json={}, headers=auth_headers).status_code == 404


# ----------------------------------------------------------------- authentification
def _protected_calls(sid, eid, tid):
    return [
        ("POST", "/sources", {"platform": "web", "url": "https://x.fr"}),
        ("POST", "/events", event_body(sid)),
        ("PATCH", f"/events/{eid}", {"status": "validated"}),
        ("POST", "/tasks", {"task_type": "scrape"}),
        ("GET", "/tasks/next", None),
        ("GET", f"/tasks/{tid}", None),
        ("PATCH", f"/tasks/{tid}/result", {"result": {}}),
    ]


@pytest.mark.parametrize(
    "headers",
    [
        {},                                                # pas de token
        {"Authorization": "Bearer mauvais-token"},         # mauvais token
        {"Authorization": "Basic dGVzdC10b2tlbg=="},       # mauvais schéma
        {"Authorization": "Bearer "},                      # token vide
    ],
    ids=["sans-token", "mauvais-token", "mauvais-schema", "token-vide"],
)
def test_protected_routes_refused(client, auth_headers, headers):
    sid = make_source(client, auth_headers)
    eid = make_event(client, auth_headers, sid).json()["id"]
    tid = client.post("/tasks", json={"task_type": "scrape"}, headers=auth_headers).json()["id"]
    for method, path, body in _protected_calls(sid, eid, tid):
        r = client.request(method, path, json=body, headers=headers)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
    # rien n'a été modifié par les appels refusés
    assert client.get(f"/events/{eid}").json()["status"] == "pending"


def test_protected_routes_accept_valid_token(client, auth_headers):
    sid = make_source(client, auth_headers)
    eid = make_event(client, auth_headers, sid).json()["id"]
    tid = client.post("/tasks", json={"task_type": "scrape"}, headers=auth_headers).json()["id"]
    for method, path, body in _protected_calls(sid, eid, tid):
        r = client.request(method, path, json=body, headers=auth_headers)
        assert r.status_code < 400 or r.status_code == 409, f"{method} {path} -> {r.status_code}"


def test_public_routes_need_no_token(client, auth_headers):
    sid = make_source(client, auth_headers)
    for path in ("/health", "/events", "/events.geojson", "/sources", f"/sources/{sid}"):
        assert client.get(path).status_code == 200, path


def test_routes_fail_closed_without_configured_token(client, auth_headers, monkeypatch):
    import dataclasses
    from app import auth

    monkeypatch.setattr(auth, "settings", dataclasses.replace(auth.settings, api_token=""))
    assert client.get("/tasks/next", headers=auth_headers).status_code == 503


# ----------------------------------------------------------------- tasks
def test_tasks_flow(client, auth_headers):
    t = client.post("/tasks", json={"task_type": "scrape"}, headers=auth_headers).json()
    assert client.get(f"/tasks/{t['id']}", headers=auth_headers).json()["status"] == "pending"
    nxt = client.get("/tasks/next", headers=auth_headers)
    assert nxt.status_code == 200 and nxt.json()["status"] == "running"
    assert client.get("/tasks/next", headers=auth_headers).status_code == 204
    r = client.patch(f"/tasks/{t['id']}/result", json={"result": {"ok": 1}}, headers=auth_headers)
    assert r.json()["status"] == "done"
    assert client.patch(f"/tasks/{t['id']}/result", json={}, headers=auth_headers).status_code == 409
    assert client.get(f"/tasks/{uuid.uuid4()}", headers=auth_headers).status_code == 404


# ----------------------------------------------------------------- Perplexity mocké -> API
def test_analysis_with_mocked_perplexity_feeds_api(client, auth_headers, db, monkeypatch):
    """Le pipeline d'analyse (Perplexity mocké) produit un événement à relire, absent de la carte."""
    import json
    from app.models import Task
    from app.services import analysis

    sid = make_source(client, auth_headers)
    db.add(Task(task_type="analyze_source", status="running", payload={"source_id": sid}))
    db.commit()

    reply = event_body(sid, needs_human_review=False)
    monkeypatch.setattr(
        px, "call_perplexity",
        lambda payload: {"choices": [{"message": {"content": json.dumps(reply)}}]},
    )
    # `db` et `client` sont deux sessions sur la même base en mémoire.
    ev = analysis.analyze_source(uuid.UUID(sid), db=db)
    assert ev is not None and ev.needs_review is True
    assert len(client.get("/events").json()) == 1
    assert client.get("/events.geojson").json()["features"] == []
