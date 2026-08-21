"""Auth primitives for the notifications service.

Two mechanisms, both keyed off NOTIFICATIONS_AUTH_TOKEN:

* service calls (``/notify``, token minting) present the raw shared token
  in the ``X-Auth-Token`` header (constant-time compared);
* SSE stream connections present a per-user, expiring token
  ``"<exp>.<hex hmac_sha256(secret, user_id + ':' + exp)>"`` so a token
  only ever opens the stream of the user it was minted for (no IDOR) and
  goes stale on its own. EventSource cannot send headers, hence the query
  parameter — but the token is user-bound and short-lived, never the
  global secret.

Pure functions (no settings import) so they are unit-testable in isolation.
"""

from __future__ import annotations

import hashlib
import hmac
import time

DEFAULT_STREAM_TOKEN_TTL_S = 3600
MIN_STREAM_TOKEN_TTL_S = 60
MAX_STREAM_TOKEN_TTL_S = 86_400


def service_token_valid(secret: str, presented: str) -> bool:
    """Constant-time check of the shared service token. Blank secret → False."""
    if not secret:
        return False
    return hmac.compare_digest(
        (presented or "").encode("utf-8"), secret.encode("utf-8")
    )


def _stream_digest(secret: str, user_id: str, exp: int) -> str:
    msg = f"{user_id}:{exp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def mint_stream_token(
    secret: str,
    user_id: str,
    ttl_seconds: int = DEFAULT_STREAM_TOKEN_TTL_S,
    now: float | None = None,
) -> tuple[str, int]:
    """Return ``(token, expires_at)`` for *user_id*. Raises on blank inputs."""
    if not secret:
        raise ValueError("Cannot mint stream tokens without a secret")
    if not user_id:
        raise ValueError("user_id is required")
    ttl = max(MIN_STREAM_TOKEN_TTL_S, min(int(ttl_seconds), MAX_STREAM_TOKEN_TTL_S))
    exp = int(now if now is not None else time.time()) + ttl
    return f"{exp}.{_stream_digest(secret, user_id, exp)}", exp


def verify_stream_token(
    secret: str, user_id: str, token: str, now: float | None = None
) -> bool:
    """True only for an unexpired token minted for exactly *user_id*."""
    if not secret or not user_id or not token:
        return False
    exp_part, sep, digest = token.partition(".")
    if not sep or not digest:
        return False
    try:
        exp = int(exp_part)
    except ValueError:
        return False
    if exp <= (now if now is not None else time.time()):
        return False
    expected = _stream_digest(secret, user_id, exp)
    return hmac.compare_digest(digest.encode("utf-8"), expected.encode("utf-8"))
