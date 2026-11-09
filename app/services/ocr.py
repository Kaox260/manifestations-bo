"""OCR d'images avec Tesseract (nécessite le binaire `tesseract` + le pack `fra`)."""
import re


def clean_text(text: str) -> str:
    lines = (re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


def ocr_image(path: str) -> str | None:
    """Texte de l'image (langue fra), espaces normalisés ; None si aucun texte."""
    import pytesseract  # imports tardifs : dépendances optionnelles
    from PIL import Image

    with Image.open(path) as img:
        raw = pytesseract.image_to_string(img, lang="fra")
    return clean_text(raw) or None
