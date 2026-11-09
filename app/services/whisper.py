"""Transcription audio/vidéo locale avec faster-whisper (CPU, int8)."""
import logging
from functools import lru_cache
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

LANGUAGE = "fr"


@lru_cache(maxsize=1)
def _get_model(name: str):
    from faster_whisper import WhisperModel  # import tardif : dépendance lourde

    return WhisperModel(name, device="cpu", compute_type="int8")


def transcribe_audio(path: str) -> dict[str, Any]:
    """Transcrit `path` (audio ou vidéo) en français.

    Seules les `MAX_VIDEO_DURATION_SECONDS` premières secondes sont traitées.
    Retourne {"text": str, "language": "fr", "duration": float} où `duration` est la
    durée effectivement transcrite.
    """
    limit = float(settings.max_video_duration_seconds)
    model = _get_model(settings.whisper_model)
    segments, info = model.transcribe(
        path, language=LANGUAGE, clip_timestamps=[0.0, limit], vad_filter=True
    )
    parts: list[str] = []
    for seg in segments:  # générateur : la transcription se fait ici
        if seg.start >= limit:
            break
        text = seg.text.strip()
        if text:
            parts.append(text)
    duration = min(float(info.duration), limit)
    return {"text": " ".join(parts), "language": LANGUAGE, "duration": duration}
