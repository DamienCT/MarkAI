"""Redaction helpers for log/exception messages that may carry credentials.

Meta/LinkedIn access tokens historically leaked into backend logs via full
request URLs: query strings embedded in httpx INFO request lines and in
``str(httpx.HTTPStatusError)`` (audit N-01). Every log or exception message
that can carry a URL must pass through :func:`redact` (or :func:`redact_url`
for plain URLs) before being emitted.

Over-redaction is acceptable; leaking a live credential is not.
"""

from __future__ import annotations

import re

_MASK = "***"

# Query-param names that must never appear with their value in a log line.
# Matched case-insensitively: either the name CONTAINS a broad marker
# (token / secret / passw / credential / api key) or it IS one of the exact
# short names (code / sig / signature / key / auth).
_PARAM_NAME = (
    r"(?:[^=&\s'\"]*(?:token|secret|passw|credential|api_?key)[^=&\s'\"]*"
    r"|code|sig|signature|key|auth)"
)

# name=value inside a URL query string (after ? or &).
_QUERY_PARAM_RE = re.compile(r"(?i)([?&]" + _PARAM_NAME + r"=)[^&\s'\"]*")

# Bare name=value outside a query string (e.g. "access_token=EAAB..." in an
# exception repr). The lookbehind keeps names embedded in longer identifiers
# (status_code=, monkey=) untouched.
_BARE_PARAM_RE = re.compile(r"(?i)(?<![\w?&-])(" + _PARAM_NAME + r"=)[^&\s'\"]+")

# Dict/JSON style: 'access_token': 'EAAB...' or "api_key" = "sk-...".
_DICT_STYLE_RE = re.compile(
    r"(?i)(['\"]" + _PARAM_NAME + r"['\"]\s*[:=]\s*)(['\"])[^'\"]*(['\"])"
)

# Authorization header values leaking through reprs.
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")


def redact_url(url: object) -> str:
    """Mask credential-bearing query params in a URL string."""
    return _QUERY_PARAM_RE.sub(r"\g<1>" + _MASK, str(url))


def redact(value: object) -> str:
    """Mask credentials anywhere in an arbitrary message or exception.

    Accepts any object (typically an exception or a formatted string) and
    returns its ``str()`` with token/code/sig/key-like values replaced by
    ``***`` — in URLs, bare ``name=value`` pairs, dict-style reprs, and
    ``Bearer`` header values.
    """
    s = _QUERY_PARAM_RE.sub(r"\g<1>" + _MASK, str(value))
    s = _BARE_PARAM_RE.sub(r"\g<1>" + _MASK, s)
    s = _DICT_STYLE_RE.sub(lambda m: m.group(1) + m.group(2) + _MASK + m.group(3), s)
    s = _BEARER_RE.sub(r"\g<1>" + _MASK, s)
    return s
