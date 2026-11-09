"""Découverte de vidéos TikTok via Playwright (Chromium headed sous Xvfb).

Garde-fous : aucune connexion TikTok simulée, aucun contournement de CAPTCHA
(on s'arrête et on log), aucune vidéo téléchargée (on ne lit que le DOM public).
Sous Linux, démarrer Xvfb au préalable et exporter DISPLAY (ex: `xvfb-run -a python ...`
ou `Xvfb :99 &` puis `DISPLAY=:99`).
"""
import logging
import os
import random
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Source, Task
from app.services.browser import launch as _launch

logger = logging.getLogger(__name__)

PLATFORM = "tiktok"
TASK_TYPE = "analyze_source"
SEARCH_URL = "https://www.tiktok.com/search/video"
MAX_URLS = 30
MAX_SCROLL = 4
NAV_TIMEOUT_MS = 30_000

_VIDEO_PATH = re.compile(r"^/@([^/?#]+)/video/(\d+)")
_CAPTCHA_SELECTORS = (
    "#captcha-verify-container, .captcha_verify_container, "
    "[class*='captcha' i], iframe[src*='captcha' i]"
)
_VIDEO_LINK_JS = "els => els.map(e => e.href)"


@dataclass
class DiscoveryResult:
    urls: list[str] = field(default_factory=list)
    screenshot_path: str | None = None
    captcha: bool = False


# --------------------------------------------------------------------------- helpers
def build_search_url(query: str) -> str:
    return f"{SEARCH_URL}?q={quote_plus(query.strip())}"


def normalize_video_url(url: str) -> str | None:
    """https://www.tiktok.com/@user/video/<id> (sans query/fragment), sinon None."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host != "tiktok.com" and not host.endswith(".tiktok.com"):
        return None
    m = _VIDEO_PATH.match(parts.path)
    if not m:
        return None
    return f"https://www.tiktok.com/@{m.group(1).lower()}/video/{m.group(2)}"


def _ascii_lower(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def is_relevant(metadata: dict[str, Any], query: str) -> bool:
    """Pertinent = titre/description contient au moins un mot (>=3 lettres) de la requête."""
    haystack = _ascii_lower(f"{metadata.get('title') or ''} {metadata.get('raw_text') or ''}")
    words = [w for w in re.findall(r"\w+", _ascii_lower(query)) if len(w) >= 3]
    return bool(haystack.strip()) and any(w in haystack for w in words)


def _pause() -> int:
    return int(random.uniform(1.5, 2.0) * 1000)


def _screenshot_path(prefix: str) -> Path:
    d = Path(settings.screenshot_dir)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return d / f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}.png"


def _has_captcha(page) -> bool:
    try:
        return page.locator(_CAPTCHA_SELECTORS).count() > 0
    except Exception:
        return False


def _collect(page, seen: dict[str, None]) -> None:
    hrefs = page.eval_on_selector_all("a[href*='/video/']", _VIDEO_LINK_JS)
    for href in hrefs:
        norm = normalize_video_url(href)
        if norm and norm not in seen and len(seen) < MAX_URLS:
            seen[norm] = None


# --------------------------------------------------------------------------- scraping
def discover_tiktok_urls(query: str, max_scroll: int = MAX_SCROLL) -> DiscoveryResult:
    """Ouvre la recherche, scrolle (<=4 fois), retourne <=30 URLs normalisées + capture.

    N'échoue jamais : toute erreur est loguée et un résultat (éventuellement vide) est rendu.
    """
    result = DiscoveryResult()
    max_scroll = max(0, min(max_scroll, MAX_SCROLL))
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, context = _launch(p)
            try:
                page = context.new_page()
                page.set_default_timeout(NAV_TIMEOUT_MS)
                page.goto(build_search_url(query), wait_until="domcontentloaded")
                page.wait_for_timeout(_pause())

                if _has_captcha(page):
                    # On ne contourne pas : on s'arrête.
                    logger.warning("TikTok CAPTCHA detected on search page; aborting discovery")
                    result.captcha = True
                else:
                    seen: dict[str, None] = {}
                    _collect(page, seen)
                    for _ in range(max_scroll):
                        if len(seen) >= MAX_URLS:
                            break
                        page.evaluate("window.scrollBy(0, Math.round(window.innerHeight * 0.8))")
                        page.wait_for_timeout(_pause())
                        if _has_captcha(page):
                            logger.warning("TikTok CAPTCHA appeared while scrolling; stopping")
                            result.captcha = True
                            break
                        _collect(page, seen)
                    result.urls = list(seen)

                path = _screenshot_path("tiktok-search")
                page.screenshot(path=str(path))
                result.screenshot_path = str(path)
            finally:
                context.close()
                browser.close()
    except Exception:
        logger.exception("TikTok discovery failed for query=%r", query)
    return result


def extract_page_metadata(url: str, page=None) -> dict[str, Any]:
    """Métadonnées publiques d'une page vidéo (balises og:*, titre) + capture d'écran.

    `page` : page Playwright déjà ouverte à réutiliser ; sinon un navigateur dédié est lancé.
    Retourne {} en cas d'erreur ou de CAPTCHA.
    """
    try:
        if page is not None:
            return _extract(page, url)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, context = _launch(p)
            try:
                return _extract(context.new_page(), url)
            finally:
                context.close()
                browser.close()
    except Exception:
        logger.exception("TikTok metadata extraction failed for %s", url)
        return {}


def _extract(page, url: str) -> dict[str, Any]:
    page.set_default_timeout(NAV_TIMEOUT_MS)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(_pause())
    if _has_captcha(page):
        logger.warning("TikTok CAPTCHA detected on %s; skipping", url)
        return {}

    def og(name: str) -> str | None:
        loc = page.locator(f'meta[property="{name}"]')
        return loc.first.get_attribute("content") if loc.count() else None

    path = _screenshot_path("tiktok-video")
    page.screenshot(path=str(path))
    m = _VIDEO_PATH.match(urlsplit(url).path)
    return {
        "title": og("og:title") or page.title() or None,
        "raw_text": og("og:description"),
        "author": m.group(1) if m else None,
        "screenshot_path": str(path),
        "raw_metadata": {
            "og_url": og("og:url"),
            "og_type": og("og:type"),
            "video_id": m.group(2) if m else None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# --------------------------------------------------------------------------- database
def save_source_if_new(url: str, metadata: dict[str, Any], db: Session | None = None) -> Source | None:
    """Insère la source si l'URL normalisée est inconnue. Retourne la Source, ou None si doublon.

    URL invalide -> ValueError. Sans `db`, ouvre et ferme sa propre session.
    """
    norm = normalize_video_url(url)
    if norm is None:
        raise ValueError(f"Not a TikTok video URL: {url!r}")
    own = db is None
    db = db or SessionLocal()
    try:
        exists = db.scalar(
            select(Source.id).where(Source.platform == PLATFORM, Source.url == norm).limit(1)
        )
        if exists:
            return None
        meta = dict(metadata.get("raw_metadata") or {})
        if metadata.get("author"):
            meta["author"] = metadata["author"]
        source = Source(
            platform=PLATFORM,
            url=norm,
            title=metadata.get("title"),
            raw_text=metadata.get("raw_text"),
            screenshot_path=metadata.get("screenshot_path"),
            raw_metadata=meta or None,
            reliability="social",
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        return source
    finally:
        if own:
            db.close()


def create_analysis_task(source_id: uuid.UUID, db: Session | None = None) -> Task:
    own = db is None
    db = db or SessionLocal()
    try:
        task = Task(task_type=TASK_TYPE, payload={"source_id": str(source_id)})
        db.add(task)
        db.commit()
        db.refresh(task)
        return task
    finally:
        if own:
            db.close()


# --------------------------------------------------------------------------- orchestration
def run_tiktok_discovery(query: str, max_scroll: int = MAX_SCROLL) -> dict[str, int]:
    """Pipeline complet. Ne lève jamais : retourne des compteurs, les erreurs sont loguées."""
    stats = {"found": 0, "new": 0, "tasks": 0, "errors": 0, "captcha": 0}
    try:
        discovery = discover_tiktok_urls(query, max_scroll)
        stats["found"] = len(discovery.urls)
        stats["captcha"] = int(discovery.captcha)
        if not discovery.urls:
            return stats

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p, SessionLocal() as db:
            browser, context = _launch(p)
            try:
                page = context.new_page()
                for url in discovery.urls:
                    try:
                        # Évite d'ouvrir la page de vidéos déjà connues.
                        if db.scalar(select(Source.id).where(Source.platform == PLATFORM, Source.url == url).limit(1)):
                            continue
                        metadata = extract_page_metadata(url, page=page)
                        source = save_source_if_new(url, metadata, db=db)
                        if source is None:
                            continue
                        stats["new"] += 1
                        if is_relevant(metadata, query):
                            create_analysis_task(source.id, db=db)
                            stats["tasks"] += 1
                    except Exception:
                        db.rollback()
                        stats["errors"] += 1
                        logger.exception("TikTok processing failed for %s", url)
            finally:
                context.close()
                browser.close()
    except Exception:
        stats["errors"] += 1
        logger.exception("TikTok discovery run failed")
    logger.info("TikTok run done: %s", stats)
    return stats
