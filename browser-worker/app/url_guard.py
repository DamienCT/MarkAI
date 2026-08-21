"""Central outbound-URL guard for the browser worker (SSRF containment).

Every URL this service is asked to visit — screenshot/extract targets,
social-page URLs, image candidates from Bing — is attacker-influenced, so
each one passes through here before any connection is made:

* scheme allowlist: http/https only, no credentials in the URL;
* port allowlist: default ports 80/443 only;
* hostname sanity: dotted public names only (`localhost`, `*.internal`,
  `*.local`, bare intranet names are refused without a lookup);
* DNS resolution with private-range denial: EVERY resolved address
  (IPv4 + IPv6, mapped forms unwrapped) must be globally routable —
  loopback, RFC1918, link-local (169.254.169.254 cloud metadata),
  CGNAT, ULA fc00::/7, ::1, multicast, reserved and unspecified
  ranges are all refused. Resolution failure refuses (fail closed);
* redirects are never followed blindly: Playwright pages get a request
  interceptor that re-validates every hop/subresource, and the httpx
  helper follows redirects manually with a hop cap;
* response size caps on raw fetches.

Deliberately self-contained (stdlib + httpx, no app.config import) so it
can be unit-tested without Playwright or service settings.

Residual risk (documented): for Playwright navigation the browser performs
its own DNS lookup after our check, so a rebinding attacker with a
zero-TTL record retains a small TOCTOU window. The verdict cache keeps the
window narrow and every redirect hop is still re-checked.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from typing import Awaitable, Callable, Iterable
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("browser-worker.url_guard")

MAX_REDIRECTS = 5
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}
# Hard cap on any raw body this service reads back (extract path ≤ 2 MB).
EXTRACT_MAX_BYTES = 2_000_000

# Hostname suffixes that are never legitimate public targets.
_DENIED_HOST_SUFFIXES = (".localhost", ".internal", ".local", ".home.arpa")
_DENIED_HOSTS = {"localhost", "metadata.google.internal", "metadata"}

# host -> (allowed, expiry). Short TTL: narrows the DNS-rebinding window
# while avoiding a lookup per subresource request.
_VERDICT_TTL_S = 60.0
_VERDICT_CACHE_MAX = 4096
_verdict_cache: dict[str, tuple[bool, float]] = {}

Resolver = Callable[[str], Awaitable[Iterable[str]]]


class URLGuardError(ValueError):
    """Raised when a URL is refused by the guard."""


def check_ip(ip_str: str) -> bool:
    """True if *ip_str* is a globally routable, non-special address."""
    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def host_matches(hostname: str | None, domain: str) -> bool:
    """Exact-host or dot-suffix domain match (never substring).

    ``instagram.com`` matches ``instagram.com`` and ``www.instagram.com``
    but NOT ``evilinstagram.com`` or ``instagram.com.evil.com``.
    """
    if not hostname:
        return False
    host = hostname.lower().rstrip(".")
    domain = domain.lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


def _check_host_syntax(url: str) -> str:
    """Validate scheme/port/credentials/hostname shape; return the hostname.

    Raises URLGuardError. Does NOT resolve DNS.
    """
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise URLGuardError(f"Unparseable URL: {exc}") from exc
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise URLGuardError(f"Scheme not allowed: {parts.scheme!r}")
    if parts.username or parts.password:
        raise URLGuardError("Credentials in URL are not allowed")
    try:
        port = parts.port
    except ValueError as exc:
        raise URLGuardError("Invalid port") from exc
    if port is not None and port not in ALLOWED_PORTS:
        raise URLGuardError(f"Port not allowed: {port}")
    host = (parts.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise URLGuardError("URL has no hostname")

    # IP literals are decided immediately, no lookup.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not check_ip(host):
            raise URLGuardError(f"IP address not allowed: {host}")
        return host

    if host in _DENIED_HOSTS or any(host.endswith(s) for s in _DENIED_HOST_SUFFIXES):
        raise URLGuardError(f"Hostname not allowed: {host}")
    if "." not in host:
        # Bare names only resolve via search domains — never a public site.
        raise URLGuardError(f"Non-qualified hostname not allowed: {host}")
    return host


async def _default_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def _host_allowed(host: str, resolver: Resolver | None = None) -> bool:
    """Resolve *host* and require every returned address to be public."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return check_ip(host)

    now = time.monotonic()
    if resolver is None:
        cached = _verdict_cache.get(host)
        if cached is not None and cached[1] > now:
            return cached[0]

    try:
        addrs = list(await (resolver or _default_resolver)(host))
    except Exception:
        addrs = []
    # Empty resolution or ANY private/special address refuses the host.
    allowed = bool(addrs) and all(check_ip(a) for a in addrs)

    if resolver is None:
        if len(_verdict_cache) >= _VERDICT_CACHE_MAX:
            _verdict_cache.clear()
        _verdict_cache[host] = (allowed, now + _VERDICT_TTL_S)
    return allowed


async def validate_url(url: str, resolver: Resolver | None = None) -> str:
    """Full guard: syntax checks plus DNS private-range denial.

    Returns the validated hostname; raises URLGuardError on refusal.
    """
    host = _check_host_syntax(url)
    if not await _host_allowed(host, resolver):
        raise URLGuardError(f"Host refused (private/unresolvable): {host}")
    return host


async def install_page_guard(page) -> None:
    """Intercept every request a Playwright page makes and re-validate it.

    Covers redirect hops, subresources, iframes — anything that could pull
    internal content into an extraction or screenshot. Refused requests are
    aborted (a refused main-frame navigation fails the goto, fail closed).
    """

    async def _handler(route) -> None:
        url = route.request.url
        try:
            await validate_url(url)
        except URLGuardError as exc:
            logger.warning("Blocked request to %s: %s", url[:200], exc)
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    await page.route("**/*", _handler)


async def safe_fetch(
    url: str,
    *,
    max_bytes: int,
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
    resolver: Resolver | None = None,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response | None:
    """GET *url* with redirects followed manually, each hop re-validated.

    Returns the final response with ``.content`` capped at *max_bytes*
    (larger bodies → refused, None). Any guard refusal, redirect loop or
    network error returns None — callers treat that as "candidate invalid".
    """
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, headers=headers or {})
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                await validate_url(current, resolver)
            except URLGuardError as exc:
                logger.info("safe_fetch refused %s: %s", current[:200], exc)
                return None
            req = client.build_request("GET", current, headers=headers)
            resp = await client.send(req, stream=True, follow_redirects=False)
            try:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    await resp.aclose()
                    if not location:
                        return None
                    current = str(httpx.URL(current).join(location))
                    continue
                # Stream the body with a hard cap so a huge (or endless)
                # response can't exhaust memory.
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    return None
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return None
                    chunks.append(chunk)
                # Make .content available on the streamed response.
                resp._content = b"".join(chunks)  # noqa: SLF001
                return resp
            finally:
                await resp.aclose()
        logger.info("safe_fetch: too many redirects for %s", url[:200])
        return None
    except Exception:
        logger.debug("safe_fetch failed for %s", url[:200], exc_info=True)
        return None
    finally:
        if owns_client:
            await client.aclose()
