import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_bearer = HTTPBearer(auto_error=False)


def require_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Exige `Authorization: Bearer <API_TOKEN>`. Le token n'est jamais logué."""
    expected = settings.api_token
    if not expected:
        # Fail closed : sans API_TOKEN configuré, aucune route protégée n'est accessible.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API_TOKEN not configured")
    if creds is None or not secrets.compare_digest(
        creds.credentials.encode(), expected.encode()
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )
