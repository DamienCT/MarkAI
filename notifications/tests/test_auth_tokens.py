"""Regression tests for notifications auth (P0-07: unauth /notify + SSE IDOR).

Loads app/auth.py directly by file path so the tests run without valkey /
sse-starlette installed and without clashing with other services' ``app``
packages when collected repo-wide.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "auth.py"
_spec = importlib.util.spec_from_file_location("notif_auth", _MODULE_PATH)
auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auth)

SECRET = "test-secret-token"


# ── service token (shared, header-borne) ───────────────────────────


def test_service_token_roundtrip():
    assert auth.service_token_valid(SECRET, SECRET) is True


def test_service_token_rejects_wrong_value():
    assert auth.service_token_valid(SECRET, "wrong") is False
    assert auth.service_token_valid(SECRET, "") is False


def test_blank_secret_never_validates():
    # Fail closed: an unset NOTIFICATIONS_AUTH_TOKEN must not turn into
    # allow-anything ("" == "" would have).
    assert auth.service_token_valid("", "") is False
    assert auth.service_token_valid("", "anything") is False


# ── per-user SSE stream tokens ─────────────────────────────────────


def test_stream_token_roundtrip():
    token, exp = auth.mint_stream_token(SECRET, "user-1", ttl_seconds=300, now=1_000_000)
    assert exp == 1_000_300
    assert auth.verify_stream_token(SECRET, "user-1", token, now=1_000_100) is True


def test_stream_token_bound_to_user_no_idor():
    token, _ = auth.mint_stream_token(SECRET, "user-1", now=1_000_000)
    # user-1's token must never open user-2's stream.
    assert auth.verify_stream_token(SECRET, "user-2", token, now=1_000_100) is False


def test_stream_token_expires():
    token, exp = auth.mint_stream_token(SECRET, "user-1", ttl_seconds=300, now=1_000_000)
    assert auth.verify_stream_token(SECRET, "user-1", token, now=exp) is False
    assert auth.verify_stream_token(SECRET, "user-1", token, now=exp + 1) is False


def test_stream_token_rejects_tampered_expiry():
    token, _ = auth.mint_stream_token(SECRET, "user-1", ttl_seconds=60, now=1_000_000)
    _, _, digest = token.partition(".")
    forged = f"9999999999.{digest}"
    assert auth.verify_stream_token(SECRET, "user-1", forged, now=1_000_030) is False


@pytest.mark.parametrize(
    "bad_token",
    ["", "not-a-token", "12345", ".deadbeef", "notanint.deadbeef", "12345."],
)
def test_stream_token_rejects_malformed(bad_token):
    assert auth.verify_stream_token(SECRET, "user-1", bad_token, now=0) is False


def test_stream_token_rejects_wrong_secret():
    token, _ = auth.mint_stream_token(SECRET, "user-1", now=1_000_000)
    assert auth.verify_stream_token("other-secret", "user-1", token, now=1_000_030) is False


def test_stream_token_global_secret_not_accepted():
    # The old scheme passed the global service token in the query string;
    # the new verifier must never accept it as a stream token.
    assert auth.verify_stream_token(SECRET, "user-1", SECRET, now=0) is False


def test_mint_requires_secret_and_user():
    with pytest.raises(ValueError):
        auth.mint_stream_token("", "user-1")
    with pytest.raises(ValueError):
        auth.mint_stream_token(SECRET, "")


def test_ttl_is_clamped():
    _, exp_low = auth.mint_stream_token(SECRET, "u", ttl_seconds=1, now=0)
    assert exp_low == auth.MIN_STREAM_TOKEN_TTL_S
    _, exp_high = auth.mint_stream_token(SECRET, "u", ttl_seconds=10**9, now=0)
    assert exp_high == auth.MAX_STREAM_TOKEN_TTL_S
