"""Lancement commun de Chromium (headed sous Xvfb) pour les services Playwright."""
import os
import sys

VIEWPORT = {"width": 1280, "height": 800}
LOCALE = "fr-FR"
TIMEZONE = "Europe/Paris"


def check_display() -> None:
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        raise RuntimeError("DISPLAY is not set: start Xvfb and export DISPLAY (e.g. :99)")


def launch(p):
    """Chromium headed (headless=False) ; le rendu part sur le DISPLAY Xvfb."""
    check_display()
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(viewport=VIEWPORT, locale=LOCALE, timezone_id=TIMEZONE)
    return browser, context
