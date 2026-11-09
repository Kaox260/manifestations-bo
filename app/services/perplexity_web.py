"""Interrogation de Perplexity via le site web (Playwright), avec le cookie de session.

Remplace l'appel API : le prompt est saisi dans perplexity.ai, puis le JSON de la réponse
est lu dans la page. La sortie a la même forme que l'API (`choices[0].message.content`),
donc `perplexity.parse_perplexity_response` valide ensuite avec EventCreate.

Garde-fous : le cookie n'est jamais logué ni inclus dans une exception ; en cas de
challenge anti-bot (CAPTCHA, Cloudflare), on s'arrête sans rien contourner.
"""
import json
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.config import settings
from app.services import browser
from app.services.perplexity import PerplexityConfigError, PerplexityError

logger = logging.getLogger(__name__)

REQUIRED_KEYS = {"event_type", "city", "description", "verification_status", "confidence"}
NONCE_KEY = "_nonce"
POLL_SECONDS = 3
CHALLENGE_MARKERS = ("verify you are human", "just a moment", "captcha", "vérifiez que vous")
INPUT_SELECTORS = ("#ask-input", "textarea", "[contenteditable='true']")
_PAIR = re.compile(r"^[A-Za-z_][\w.\-]*=[^=]")


class PerplexityWebError(PerplexityError):
    """Échec du pilotage web (challenge anti-bot, session expirée, page inattendue...)."""


# --------------------------------------------------------------------------- pur / testable
def parse_cookie_setting(raw: str, default_name: str) -> list[tuple[str, str]]:
    """`valeur` seule -> [(default_name, valeur)] ; `a=1; b=2` -> [(a,1),(b,2)]."""
    raw = raw.strip()
    if not raw:
        return []
    if ";" in raw or _PAIR.match(raw):
        pairs = []
        for part in raw.split(";"):
            if "=" in part:
                name, value = part.strip().split("=", 1)
                pairs.append((name.strip(), value.strip()))
        return pairs
    return [(default_name, raw)]


def build_web_prompt(payload: dict[str, Any], nonce: str) -> str:
    """Aplatit le payload API en un prompt unique, avec schéma et consigne de sortie."""
    system, user = (m["content"] for m in payload["messages"][:2])
    schema = payload["response_format"]["json_schema"]["schema"]
    return (
        f"{system}\n\n{user}\n\n"
        "JSON Schema à respecter (les champs requis sont obligatoires) :\n"
        f"{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}\n\n"
        f"Ajoute au JSON la clé \"{NONCE_KEY}\" avec exactement la valeur \"{nonce}\". "
        "Réponds par un unique bloc de code ```json contenant l'objet, sans aucun autre texte."
    )


def extract_json_objects(text: str) -> list[dict]:
    """Tous les objets JSON de premier niveau trouvés dans `text`."""
    decoder, found, i = json.JSONDecoder(), [], 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            found.append(obj)
        i = end
    return found


def pick_answer(texts: dict[str, Any], nonce: str) -> dict | None:
    """Dernier objet portant les champs d'un événement ET le nonce de cette requête.

    Le nonce empêche de prendre un JSON injecté dans les sources (commentaires, OCR...)
    qui apparaîtrait dans l'écho de la question.
    """
    for chunk_list in (texts.get("pre") or [], [texts.get("body") or ""]):
        for chunk in reversed(chunk_list):
            for obj in reversed(extract_json_objects(chunk)):
                if REQUIRED_KEYS <= obj.keys() and obj.get(NONCE_KEY) == nonce:
                    return {k: v for k, v in obj.items() if k != NONCE_KEY}
    return None


def wait_for_answer(page, nonce: str, timeout: float, sleep=time.sleep) -> dict | None:
    """Sonde la page jusqu'à une réponse JSON stable (identique à deux sondages)."""
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        texts = page.evaluate(
            "() => ({pre: [...document.querySelectorAll('pre')].map(e => e.innerText),"
            " body: document.body.innerText})"
        )
        answer = pick_answer(texts, nonce)
        if answer is not None and answer == previous:
            return answer
        previous = answer
        sleep(POLL_SECONDS)
    return None


# --------------------------------------------------------------------------- navigateur
def _snapshot(page, label: str) -> None:
    """Capture de diagnostic (ne contient que la page publique de la requête)."""
    try:
        d = Path(settings.screenshot_dir)
        d.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(d / f"perplexity-{label}-{int(time.time())}.png"))
    except Exception:
        pass


def _find_input(page):
    for sel in INPUT_SELECTORS:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=8000)
            return loc
        except Exception:
            continue
    return None


def call_perplexity_web(payload: dict[str, Any]) -> dict[str, Any]:
    """Pose la question sur perplexity.ai et retourne une réponse au format API."""
    cookies = parse_cookie_setting(settings.perplexity_session_cookie, settings.perplexity_cookie_name)
    if not cookies:
        raise PerplexityConfigError("PERPLEXITY_SESSION_COOKIE is not configured")

    nonce = secrets.token_hex(8)
    prompt = build_web_prompt(payload, nonce)
    base = settings.perplexity_web_url
    host = urlsplit(base).hostname or ""

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            br, context = browser.launch(p)
            try:
                context.add_cookies([
                    {"name": n, "value": v, "domain": host, "path": "/",
                     "secure": base.startswith("https") or n.startswith(("__Secure-", "__Host-")), "httpOnly": True, "sameSite": "Lax"}
                    for n, v in cookies
                ])
                page = context.new_page()
                page.set_default_timeout(30_000)
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)

                body = (page.evaluate("() => document.body.innerText") or "").lower()
                if any(m in body for m in CHALLENGE_MARKERS):
                    _snapshot(page, "challenge")
                    raise PerplexityWebError("anti-bot challenge detected; aborting (not bypassed)")

                box = _find_input(page)
                if box is None:
                    _snapshot(page, "no-input")
                    raise PerplexityWebError("prompt input not found (session expired or UI changed)")
                box.fill(prompt)
                page.keyboard.press("Enter")

                answer = wait_for_answer(page, nonce, settings.perplexity_web_timeout)
                if answer is None:
                    _snapshot(page, "no-answer")
                    raise PerplexityWebError(
                        "no valid JSON answer before timeout (session expired, quota or UI changed)"
                    )
            finally:
                context.close()
                br.close()
    except PerplexityError:
        raise
    except Exception as exc:
        # Seul le type d'erreur est conservé : jamais de détail pouvant contenir le cookie.
        logger.warning("Perplexity web automation failed: %s", type(exc).__name__)
        raise PerplexityWebError(f"browser automation failed: {type(exc).__name__}") from None

    return {"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]}
