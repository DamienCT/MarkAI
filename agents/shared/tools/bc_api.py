"""Business Central API v2.0 client — item-card pictures.

Why this exists
---------------
The Fabric lakehouse mirror of Business Central does NOT replicate item
pictures: ``dbo.itemmodule_item`` has 142 columns and not one of them is a
picture/media/image column (an INFORMATION_SCHEMA sweep across the whole
lakehouse for ``%picture%``/``%media%``/``%image%``/``%photo%`` turns up only
``accountingmodule_glaccount.picture``). BC stores item pictures as Tenant
Media blobs, which are only reachable through the Business Central API v2.0::

    GET {base}/v2.0/{tenant}/{environment}/api/v2.0/companies
    GET .../companies({companyId})/items?$filter=number eq '{sku}'
    GET .../companies({companyId})/items({itemId})/picture
    GET <pictureContent@odata.mediaReadLink>          -> the image bytes

Scope of this module
--------------------
Protocol only: token acquisition, company/item resolution, picture download,
caching, rate limiting and the auth circuit breaker. It deliberately imports
nothing from either service (no settings, no MinIO, no DB) so that one
implementation can serve both the agents workflow chain and the FastAPI
backend, which are built from disjoint Docker contexts.

SINGLE SOURCE OF TRUTH. This file is vendored byte-identically to:
    agents/shared/tools/bc_api.py     <- authoritative copy, edit this one
    backend/app/services/bc_api.py    <- vendored copy, keep in sync
``agents/tests/test_bc_api.py`` and ``backend/tests/test_bc_api.py`` both fail
if the two files drift, so the protocol can never fork.

Callers supply a :class:`BCConfig` and get back a :class:`BCPicture` (raw
bytes + content type) or ``None``. Every failure mode — missing credentials,
no picture on the item card, HTTP error, throttling exhaustion — returns
``None`` rather than raising, so a broken BC degrades to the supplier/web
sourcing steps instead of failing a content run.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

BC_SCOPE = "https://api.businesscentral.dynamics.com/.default"

# ── Throttling ───────────────────────────────────────────────────────────
# BC online, per environment: max 5 concurrent OData requests (excess queues,
# then 503) and 600 requests/minute on Production (300 on Sandbox); the
# per-user ceiling is 6000 per 5-minute sliding window. Exceeding either
# returns 429 with a Retry-After header.
# Stay under both: 4 in flight and >=125ms between requests (~480/min).
_MAX_CONCURRENT = 4
_MIN_REQUEST_INTERVAL_S = 0.125
_MAX_RETRIES = 2
_MAX_RETRY_AFTER_S = 60.0

# ── Cache TTLs ───────────────────────────────────────────────────────────
_TOKEN_SKEW_S = 300         # renew 5 min before the token actually expires
_COMPANY_TTL_S = 30 * 60
_ITEM_TTL_S = 30 * 60
_NO_PICTURE_TTL_S = 30 * 60

# How long the whole path stays switched off after an auth rejection. Without
# this a 600-product sync would fire 600 doomed requests; with it, one.
_AUTH_FAILURE_COOLDOWN_S = 15 * 60

_MAX_PICTURE_BYTES = 12 * 1024 * 1024

_ACCEPTED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp")


class BCUnavailable(Exception):
    """Internal signal: BC is unreachable/unauthorised. Never escapes this module."""


@dataclass(frozen=True)
class BCConfig:
    """Everything needed to talk to one BC environment.

    Built by each service from its own settings object — see
    ``shared.tools.bc_images`` (agents) and ``app.services.bc_image_service``
    (backend).
    """

    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    environment: str = "Production"
    base_url: str = "https://api.businesscentral.dynamics.com"
    enabled: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(
            self.enabled
            and self.tenant_id
            and self.client_id
            and self.client_secret
            and self.environment
        )

    @property
    def api_root(self) -> str:
        return (
            f"{self.base_url.rstrip('/')}/v2.0/"
            f"{self.tenant_id}/{self.environment}/api/v2.0"
        )

    @property
    def cache_key(self) -> tuple[str, str, str]:
        return (self.tenant_id, self.client_id, self.environment)


@dataclass(frozen=True)
class BCPicture:
    """An item-card picture straight from the client's own ERP."""

    content: bytes
    content_type: str
    company_id: str
    item_id: str
    sku: str
    width: int = 0
    height: int = 0

    @property
    def extension(self) -> str:
        ct = (self.content_type or "").lower()
        if "png" in ct:
            return "png"
        if "webp" in ct:
            return "webp"
        if "gif" in ct:
            return "gif"
        if "bmp" in ct:
            return "bmp"
        return "jpg"


# ── Module state (all keyed so several tenants/environments can coexist) ──

_token_cache: dict[tuple[str, str, str], tuple[str, float]] = {}
_company_cache: dict[tuple[str, str, str], tuple[float, dict[str, str]]] = {}
_item_cache: dict[tuple[Any, ...], tuple[float, str | None]] = {}
_no_picture_cache: dict[tuple[Any, ...], float] = {}
_disabled_until: dict[tuple[str, str, str], float] = {}
_auth_error_logged: set[tuple[str, str, str]] = set()

_semaphores: dict[int, asyncio.Semaphore] = {}
_last_request_at: dict[int, float] = {}


def reset_cache() -> None:
    """Drop every cached token, lookup and circuit-breaker state (tests/ops)."""
    _token_cache.clear()
    _company_cache.clear()
    _item_cache.clear()
    _no_picture_cache.clear()
    _disabled_until.clear()
    _auth_error_logged.clear()
    _semaphores.clear()
    _last_request_at.clear()


def _loop_key() -> int:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:  # pragma: no cover — only outside an event loop
        return 0


def _semaphore() -> asyncio.Semaphore:
    """Per-event-loop semaphore.

    A module-level Semaphore binds to the first loop that awaits it, which
    breaks the second ``asyncio.run`` in a test session. Keying by loop keeps
    it correct in both the long-lived worker and short-lived test loops.
    """
    key = _loop_key()
    sem = _semaphores.get(key)
    if sem is None:
        if len(_semaphores) > 8:  # stale loops from finished asyncio.run calls
            _semaphores.clear()
            _last_request_at.clear()
        sem = asyncio.Semaphore(_MAX_CONCURRENT)
        _semaphores[key] = sem
    return sem


async def _respect_min_interval() -> None:
    key = _loop_key()
    now = time.monotonic()
    last = _last_request_at.get(key, 0.0)
    wait = _MIN_REQUEST_INTERVAL_S - (now - last)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_request_at[key] = time.monotonic()


def is_available(cfg: BCConfig) -> bool:
    """True when BC is configured and not inside an auth-failure cooldown."""
    if not cfg.is_configured:
        return False
    until = _disabled_until.get(cfg.cache_key, 0.0)
    return time.time() >= until


def _trip_breaker(cfg: BCConfig, status_code: int, body: str) -> None:
    """Switch the BC path off for a cooldown after an auth rejection."""
    key = cfg.cache_key
    _disabled_until[key] = time.time() + _AUTH_FAILURE_COOLDOWN_S
    _token_cache.pop(key, None)
    if key not in _auth_error_logged:
        _auth_error_logged.add(key)
        logger.error(
            "Business Central API rejected the service principal (HTTP %s). "
            "BC item-card images are disabled for %d minutes. Grant is needed: "
            "(1) Entra app %s -> API permissions -> Dynamics 365 Business Central "
            "-> Application permissions -> API.ReadWrite.All -> Grant admin consent; "
            "(2) in Business Central open 'Microsoft Entra Applications', add that "
            "Client ID, set State=Enabled and assign the D365 BASIC + D365 READ "
            "permission sets. Response: %s",
            status_code,
            _AUTH_FAILURE_COOLDOWN_S // 60,
            cfg.client_id,
            body[:300],
        )


async def _get_token(client: httpx.AsyncClient, cfg: BCConfig) -> str:
    key = cfg.cache_key
    cached = _token_cache.get(key)
    if cached and time.time() < cached[1]:
        return cached[0]

    resp = await client.post(
        f"https://login.microsoftonline.com/{cfg.tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "scope": BC_SCOPE,
        },
    )
    if resp.status_code != 200:
        _trip_breaker(cfg, resp.status_code, resp.text)
        raise BCUnavailable(f"token request failed: HTTP {resp.status_code}")

    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        _trip_breaker(cfg, 200, "token response had no access_token")
        raise BCUnavailable("token response had no access_token")

    expires_in = int(payload.get("expires_in") or 3600)
    _token_cache[key] = (token, time.time() + max(60, expires_in - _TOKEN_SKEW_S))
    return token


async def _get(
    client: httpx.AsyncClient, cfg: BCConfig, url: str
) -> httpx.Response | None:
    """Authenticated GET with throttle handling.

    Returns the response, or ``None`` for 404/204 (the caller treats that as
    "not there"). Raises :class:`BCUnavailable` for auth failures and
    exhausted retries — never lets an httpx error escape.
    """
    attempt = 0
    while True:
        token = await _get_token(client, cfg)
        async with _semaphore():
            await _respect_min_interval()
            try:
                resp = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                raise BCUnavailable(f"GET {url} failed: {exc}") from exc

        if resp.status_code in (401, 403):
            _trip_breaker(cfg, resp.status_code, resp.text)
            raise BCUnavailable(f"GET {url} unauthorised: HTTP {resp.status_code}")

        if resp.status_code in (404, 204):
            return None

        if resp.status_code in (429, 503) and attempt < _MAX_RETRIES:
            attempt += 1
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            delay = retry_after if retry_after is not None else min(2.0 * attempt, 10.0)
            logger.warning(
                "Business Central throttled (HTTP %s), retrying in %.1fs (attempt %d/%d)",
                resp.status_code,
                delay,
                attempt,
                _MAX_RETRIES,
            )
            await asyncio.sleep(min(delay, _MAX_RETRY_AFTER_S))
            continue

        if resp.status_code >= 400:
            raise BCUnavailable(
                f"GET {url} failed: HTTP {resp.status_code} {resp.text[:200]}"
            )

        return resp


def _parse_retry_after(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _odata_literal(value: str) -> str:
    """Quote a value for an OData string filter (single quotes are doubled)."""
    return "'" + value.replace("'", "''") + "'"


async def _resolve_company_id(
    client: httpx.AsyncClient, cfg: BCConfig, company: str
) -> str | None:
    """Map a BC company name (e.g. 'Naturespan') to its API company GUID."""
    wanted = (company or "").strip().lower()
    if not wanted:
        return None

    key = cfg.cache_key
    cached = _company_cache.get(key)
    if cached and (time.time() - cached[0]) < _COMPANY_TTL_S:
        return cached[1].get(wanted)

    resp = await _get(client, cfg, f"{cfg.api_root}/companies")
    if resp is None:
        return None

    mapping: dict[str, str] = {}
    for entry in resp.json().get("value", []):
        cid = entry.get("id")
        if not cid:
            continue
        # Match on either identifier — the lakehouse 'Company' column carries
        # the BC company Name, but users configure brands from displayName.
        for label in (entry.get("name"), entry.get("displayName")):
            if label:
                mapping.setdefault(str(label).strip().lower(), cid)

    _company_cache[key] = (time.time(), mapping)
    if wanted not in mapping:
        logger.info(
            "BC company %r not found in environment %s (known: %s)",
            company,
            cfg.environment,
            ", ".join(sorted(mapping)) or "none",
        )
    return mapping.get(wanted)


async def _resolve_item_id(
    client: httpx.AsyncClient, cfg: BCConfig, company_id: str, sku: str
) -> str | None:
    """Map an item No. (SKU) to its API item GUID. Negative results cached."""
    key = (*cfg.cache_key, company_id, sku)
    cached = _item_cache.get(key)
    if cached and (time.time() - cached[0]) < _ITEM_TTL_S:
        return cached[1]

    filter_expr = quote(f"number eq {_odata_literal(sku)}", safe="")
    url = (
        f"{cfg.api_root}/companies({company_id})/items"
        f"?$filter={filter_expr}&$select=id,number&$top=1"
    )
    resp = await _get(client, cfg, url)
    item_id: str | None = None
    if resp is not None:
        values = resp.json().get("value", [])
        if values:
            item_id = values[0].get("id")

    _item_cache[key] = (time.time(), item_id)
    return item_id


def _media_read_link(picture: dict[str, Any]) -> str | None:
    """Pull the picture-content stream URL out of a picture resource.

    The v2.0 picture resource names the stream ``pictureContent``; older
    payloads (and the doc's own example) call it ``content``. Accept any
    ``*@odata.mediaReadLink`` so a rename doesn't break sourcing.
    """
    for name in ("pictureContent@odata.mediaReadLink", "content@odata.mediaReadLink"):
        link = picture.get(name)
        if link:
            return str(link)
    for name, value in picture.items():
        if name.endswith("@odata.mediaReadLink") and value:
            return str(value)
    return None


async def fetch_item_picture(
    cfg: BCConfig,
    company: str,
    sku: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 45.0,
) -> BCPicture | None:
    """Fetch the item-card picture for ``sku`` in BC company ``company``.

    Returns ``None`` — never raises — when BC is disabled or unconfigured, the
    company/item/picture does not exist, credentials are rejected, or any HTTP
    error occurs. That is deliberate: the caller must be free to fall through
    to the supplier-website and web-search steps.
    """
    if not sku or not company:
        return None
    if not cfg.is_configured:
        logger.debug("BC item-card images skipped — credentials/settings incomplete")
        return None
    if not is_available(cfg):
        logger.debug("BC item-card images skipped — inside auth-failure cooldown")
        return None

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    try:
        return await _fetch_item_picture(cfg, company, sku, client)
    except BCUnavailable as exc:
        logger.warning("BC item-card image unavailable for %s/%s: %s", company, sku, exc)
        return None
    except Exception:
        logger.exception("BC item-card image lookup crashed for %s/%s", company, sku)
        return None
    finally:
        if owns_client:
            await client.aclose()


async def _fetch_item_picture(
    cfg: BCConfig, company: str, sku: str, client: httpx.AsyncClient
) -> BCPicture | None:
    company_id = await _resolve_company_id(client, cfg, company)
    if not company_id:
        return None

    item_id = await _resolve_item_id(client, cfg, company_id, sku)
    if not item_id:
        logger.debug("BC has no item %r in company %s", sku, company)
        return None

    no_pic_key = (*cfg.cache_key, company_id, item_id)
    cached_at = _no_picture_cache.get(no_pic_key)
    if cached_at and (time.time() - cached_at) < _NO_PICTURE_TTL_S:
        return None

    picture_url = f"{cfg.api_root}/companies({company_id})/items({item_id})/picture"
    resp = await _get(client, cfg, picture_url)
    if resp is None:
        _no_picture_cache[no_pic_key] = time.time()
        return None

    picture = resp.json() or {}
    width = int(picture.get("width") or 0)
    height = int(picture.get("height") or 0)
    link = _media_read_link(picture)
    if link is None:
        if width == 0 and height == 0:
            # An item with no picture still returns a picture record — just an
            # empty one, with no media stream link and zero dimensions.
            _no_picture_cache[no_pic_key] = time.time()
            logger.debug("BC item %s in %s has an empty picture record", sku, company)
            return None
        # Dimensions but no link: build the documented stream URL ourselves.
        link = f"{picture_url}({picture.get('id') or item_id})/pictureContent"

    content_resp = await _get(client, cfg, link)
    if content_resp is None or not content_resp.content:
        _no_picture_cache[no_pic_key] = time.time()
        return None

    data = content_resp.content
    if len(data) > _MAX_PICTURE_BYTES:
        logger.warning(
            "BC picture for %s/%s is %d bytes — over the %d byte cap, skipping",
            company,
            sku,
            len(data),
            _MAX_PICTURE_BYTES,
        )
        return None

    content_type = (
        (picture.get("contentType") or "").strip()
        or content_resp.headers.get("content-type", "").split(";")[0].strip()
        or "image/jpeg"
    )
    # BC has been seen returning 'image\jpeg' (backslash) in its own docs.
    content_type = content_type.replace("\\", "/").lower()
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"
    if content_type not in _ACCEPTED_IMAGE_TYPES:
        logger.debug("BC picture for %s/%s has unusual type %s", company, sku, content_type)

    logger.info(
        "Business Central item-card picture found for %s/%s (%d bytes, %s)",
        company,
        sku,
        len(data),
        content_type,
    )
    return BCPicture(
        content=data,
        content_type=content_type,
        company_id=company_id,
        item_id=item_id,
        sku=sku,
        width=width,
        height=height,
    )


async def probe(cfg: BCConfig, timeout: float = 45.0) -> dict[str, Any]:
    """Diagnostic: can we reach BC right now? Never raises, never logs secrets.

    Returns ``{"ok": bool, "detail": str, "companies": [names]}``.
    """
    if not cfg.is_configured:
        return {"ok": False, "detail": "BC credentials/settings incomplete", "companies": []}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            resp = await _get(client, cfg, f"{cfg.api_root}/companies")
        except BCUnavailable as exc:
            return {"ok": False, "detail": str(exc), "companies": []}
        except Exception as exc:  # pragma: no cover — defensive
            return {"ok": False, "detail": f"{type(exc).__name__}: {exc}", "companies": []}
    if resp is None:
        return {"ok": False, "detail": "environment not found", "companies": []}
    names = [
        str(c.get("name") or c.get("displayName") or "")
        for c in resp.json().get("value", [])
    ]
    return {"ok": True, "detail": "ok", "companies": [n for n in names if n]}
