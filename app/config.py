import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # SQLAlchemy 2.1 prend psycopg (v3) pour "postgresql://" ; on impose psycopg2.
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/manifestations",
    ).replace("postgresql://", "postgresql+psycopg2://", 1)
    api_token: str = os.getenv("API_TOKEN", "")
    perplexity_api_key: str = os.getenv("PERPLEXITY_API_KEY", "")
    # "web" : pilote perplexity.ai avec le cookie de session ; "api" : API officielle.
    perplexity_mode: str = os.getenv("PERPLEXITY_MODE", "web")
    perplexity_session_cookie: str = os.getenv("PERPLEXITY_SESSION_COOKIE", "")
    perplexity_cookie_name: str = os.getenv(
        "PERPLEXITY_COOKIE_NAME", "__Secure-next-auth.session-token"
    )
    perplexity_web_url: str = os.getenv("PERPLEXITY_WEB_URL", "https://www.perplexity.ai")
    perplexity_web_timeout: int = int(os.getenv("PERPLEXITY_WEB_TIMEOUT", "180"))
    screenshot_dir: str = os.getenv("SCREENSHOT_DIR", "screenshots")
    whisper_model: str = os.getenv("WHISPER_MODEL", "tiny")
    max_video_duration_seconds: int = int(os.getenv("MAX_VIDEO_DURATION_SECONDS", "180"))
    tiktok_queries: list[str] = field(
        default_factory=lambda: [
            q.strip() for q in os.getenv("TIKTOK_QUERIES", "").split(";") if q.strip()
        ]
    )
    app_env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()
        ]
    )


settings = Settings()
