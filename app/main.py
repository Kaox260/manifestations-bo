import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import events, sources, tasks

logging.basicConfig(level=settings.log_level)

app = FastAPI(title="Manifestations API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(sources.router)
app.include_router(tasks.router)

# Carte publique : /static/map.html
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent.parent / "static"), name="static")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
