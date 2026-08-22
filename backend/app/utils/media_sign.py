"""Media access control: HMAC-signed URLs + the shared media-auth dependency.

The media GET endpoints (`/api/v1/files/*`, `/api/v1/brands/{id}/logos/{label}`)
were fully unauthenticated (audit P0-08 / addendum §2.4). They now require ONE
of three credentials:

1. ``X-Media-Token: <MEDIA_PROXY_TOKEN>`` header (constant-time compare) —
   used by the Next.js same-origin media proxy and internal services.
2. Signed query params ``mt=<hex>&exp=<unix>`` produced by
   :func:`sign_media_path` — used by publish flows (Meta / LinkedIn / Teams
   cards fetching media by URL) where no header can be sent.
3. A valid Entra ID bearer token (``Authorization: Bearer ...``).

Signing contract (publish_service et al. call this):

    sign_media_path("content-images/abc.jpg", ttl=86400)
        -> "mt=<hex>&exp=<unix>"

``path`` may be EITHER the full URL path of the media endpoint
(``/api/v1/files/content-images/abc.jpg``) OR the bare MinIO object path
(``content-images/abc.jpg``) — no scheme/host, no query string. Append the
returned fragment to the URL's query string. Verification recomputes the
HMAC over ``"{path}|{exp}"`` for both forms of ``request.url.path``, so any
transform params (``w``/``q``/``fmt``) stay outside the signature.

Fail-closed: with MEDIA_PROXY_TOKEN unset, header and signed-URL access are
refused. In production a blank token also refuses bearer-less requests
outright (config.py additionally lists it in _REQUIRED_PROD); only
non-production environments fall back to open media access, loudly logged,
so local dev keeps rendering images without extra setup.
"""

import hashlib
import hmac
import logging
import time

from fastapi import HTTPException, Request, status

from app.config import settings

logger = logging.getLogger(__name__)

_warned_open_media = False


def _media_token() -> str:
    # MEDIA_PROXY_TOKEN lives in app/config.py; getattr guards the deploy
    # window where the setting is not yet present (blank = fail closed).
    return getattr(settings, "MEDIA_PROXY_TOKEN", "") or ""


def _normalize_path(path: str) -> str:
    path = (path or "").strip()
    if not path.startswith("/"):
        path = "/" + path
    return path


def sign_media_path(path: str, ttl: int = 3600) -> str:
    """Return signed query params ``"mt=<hex>&exp=<unix>"`` for a media path.

    ``path`` is the URL path of the media endpoint (e.g.
    ``/api/v1/files/content-images/abc.jpg``) — leading slash, no host, no
    query string. ``ttl`` is the validity window in seconds. Raises
    RuntimeError when MEDIA_PROXY_TOKEN is not configured — callers must not
    emit unsigned public media URLs.
    """
    token = _media_token()
    if not token:
        raise RuntimeError(
            "MEDIA_PROXY_TOKEN is not configured — cannot sign media URLs"
        )
    exp = int(time.time()) + int(ttl)
    payload = f"{_normalize_path(path)}|{exp}".encode()
    sig = hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()
    return f"mt={sig}&exp={exp}"


def verify_media_sig(path: str, mt: str, exp: str | int) -> bool:
    """Constant-time verification of a ``sign_media_path`` signature."""
    token = _media_token()
    if not token or not mt:
        return False
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < time.time():
        return False
    payload = f"{_normalize_path(path)}|{exp_i}".encode()
    expected = hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, mt)


async def require_media_access(request: Request) -> None:
    """FastAPI dependency guarding media GET endpoints.

    Accepts, in order: X-Media-Token header, signed mt/exp query params, or
    a valid Entra bearer token. Rejects everything else with 401.
    """
    global _warned_open_media
    token = _media_token()

    supplied = request.headers.get("x-media-token") or ""
    if token and supplied and hmac.compare_digest(supplied.encode(), token.encode()):
        return

    mt = request.query_params.get("mt")
    exp = request.query_params.get("exp")
    if token and mt and exp:
        # Accept a signature over either the full URL path or the bare
        # object path (publish_service signs the MinIO path it stores).
        candidates = [request.url.path]
        for prefix in ("/api/v1/files/",):
            if request.url.path.startswith(prefix):
                candidates.append(request.url.path[len(prefix) - 1 :])
        if any(verify_media_sig(c, mt, exp) for c in candidates):
            return

    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        from app.auth.entra import validate_entra_token

        try:
            await validate_entra_token(auth[7:].strip())
            return
        except Exception as exc:
            logger.warning("Media bearer token validation failed: %s", exc)
            # Fall through to the 401 below — an invalid bearer never grants
            # access, and neither does any other credential at this point.

    if not token and settings.MARKAI_ENV != "production":
        # Local-dev escape ONLY: no token configured outside production.
        # Production requires MEDIA_PROXY_TOKEN (config _REQUIRED_PROD) and
        # never reaches this branch with a blank token past startup.
        if not _warned_open_media:
            _warned_open_media = True
            logger.warning(
                "MEDIA_PROXY_TOKEN is unset — serving media WITHOUT "
                "authentication (allowed in %s only, never production)",
                settings.MARKAI_ENV,
            )
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Media authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def media_response_headers(media_type: str) -> dict[str, str]:
    """Security headers for every media response (audit media hardening).

    nosniff + a no-execute CSP on everything; Content-Disposition: attachment
    for anything that is not a non-SVG image/* or video/* type —
    image/svg+xml is ALWAYS attachment so stored SVG can never execute in
    the API origin.
    """
    ct = (media_type or "").lower().split(";")[0].strip()
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    inline_ok = (
        ct.startswith("image/") and ct != "image/svg+xml"
    ) or ct.startswith("video/")
    if not inline_ok:
        headers["Content-Disposition"] = "attachment"
    return headers
