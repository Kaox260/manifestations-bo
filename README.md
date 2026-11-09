# Manifestations API

Backend FastAPI pour collecter, analyser et cartographier des événements liés à des manifestations en France.
Les JSON structurés (worker local, API Perplexity…) sont validés par Pydantic v2, stockés dans PostgreSQL
et exposés en GeoJSON pour une carte Leaflet.

## Installation

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # puis adapter DATABASE_URL
createdb manifestations
psql "postgresql://postgres:postgres@localhost:5432/manifestations" -f schema.sql
uvicorn app.main:app --reload
```

Docs interactives : http://localhost:8000/docs

## Endpoints

| Méthode | Route | Description |
|---|---|---|
| GET | `/health` | Healthcheck |
| POST/GET | `/events`, `/events/bulk` (POST) | Créer / lister (filtres : event_type, city, status, date_from, date_to) |
| GET | `/events/geojson` | FeatureCollection GeoJSON (mêmes filtres) |
| GET | `/events/{id}` | Détail |
| POST/GET | `/sources`, `/sources/{id}` | Sources |
| POST/GET/PATCH | `/tasks`, `/tasks/{id}` | File de tâches pour les workers |

Exemple Leaflet : `L.geoJSON(await (await fetch('/events/geojson')).json()).addTo(map)`

## Tests

```bash
pytest
```

## Structure

`app/` (config, database, models, schemas, routers) · `schema.sql` (migrations SQL) · `tests/`.
Les intégrations TikTok, Whisper, OCR et Perplexity ne sont pas encore implémentées.
