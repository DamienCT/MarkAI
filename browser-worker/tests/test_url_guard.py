"""SSRF regression corpus for the browser-worker URL guard (N-05 / P0-07).

Loads app/url_guard.py directly by file path so the tests run without
Playwright installed and without clashing with other services' ``app``
packages when collected repo-wide.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "url_guard.py"
_spec = importlib.util.spec_from_file_location("bw_url_guard", _MODULE_PATH)
url_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(url_guard)


_RESOLVE_TABLE: dict[str, list[str]] = {
    "public.example": ["93.184.216.34"],
    "cdn.public.example": ["93.184.216.35"],
    "rebind.example": ["93.184.216.34", "127.0.0.1"],
    "internal-dns.example": ["10.0.0.7"],
    "v6-private.example": ["fd12:3456::1"],
}


async def _resolver(host: str) -> list[str]:
    if host in _RESOLVE_TABLE:
        return _RESOLVE_TABLE[host]
    raise OSError(f"no such host: {host}")


def _validate(url: str) -> str:
    return asyncio.run(url_guard.validate_url(url, _resolver))


# ── check_ip ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",          # loopback
        "10.0.0.5",           # RFC1918
        "172.16.0.1",         # RFC1918
        "192.168.1.1",        # RFC1918
        "169.254.169.254",    # link-local / cloud metadata
        "100.64.0.1",         # CGNAT
        "0.0.0.0",            # unspecified
        "224.0.0.1",          # multicast
        "255.255.255.255",    # broadcast/reserved
        "::1",                # v6 loopback
        "fe80::1",            # v6 link-local
        "fc00::1",            # ULA fc00::/7
        "fd00::dead:beef",    # ULA
        "::ffff:127.0.0.1",   # v4-mapped loopback
        "::ffff:10.0.0.1",    # v4-mapped private
        "::",                 # v6 unspecified
    ],
)
def test_check_ip_refuses_special_ranges(ip):
    assert url_guard.check_ip(ip) is False


@pytest.mark.parametrize("ip", ["8.8.8.8", "93.184.216.34", "2001:4860:4860::8888"])
def test_check_ip_allows_public(ip):
    assert url_guard.check_ip(ip) is True


# ── validate_url syntax + resolution ───────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fd00::1]/",
        "http://10.0.0.5/",
        "ftp://example.com/",
        "file:///etc/passwd",
        "http://example.com:8080/",          # alternate port
        "https://example.com:8443/",         # alternate port
        "http://user:pass@public.example/",  # credentials in URL
        "http://localhost/",
        "http://foo.localhost/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://intranet/",                  # non-qualified name
        "http://rebind.example/",            # one resolved addr is loopback
        "http://internal-dns.example/",      # resolves to RFC1918
        "http://v6-private.example/",        # resolves to ULA
        "http://does-not-resolve.example/",  # resolution failure → refuse
    ],
)
def test_validate_url_refuses(url):
    with pytest.raises(url_guard.URLGuardError):
        _validate(url)


def test_validate_url_allows_public_host():
    assert _validate("https://public.example/page") == "public.example"


def test_validate_url_allows_default_ports():
    assert _validate("http://public.example:80/") == "public.example"
    assert _validate("https://public.example:443/") == "public.example"


# ── host_matches (substring-routing regression, main.py) ───────────


@pytest.mark.parametrize(
    ("host", "domain", "expected"),
    [
        ("instagram.com", "instagram.com", True),
        ("www.instagram.com", "instagram.com", True),
        ("Instagram.COM", "instagram.com", True),
        ("evilinstagram.com", "instagram.com", False),
        ("instagram.com.evil.com", "instagram.com", False),
        ("evil.com", "instagram.com", False),
        (None, "instagram.com", False),
        ("", "instagram.com", False),
    ],
)
def test_host_matches(host, domain, expected):
    assert url_guard.host_matches(host, domain) is expected


# ── safe_fetch: manual redirects, per-hop validation, size caps ────


def _fetch(url: str, handler, max_bytes: int = 1_000_000):
    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await url_guard.safe_fetch(
                url, max_bytes=max_bytes, resolver=_resolver, client=client
            )

    return asyncio.run(_run())


def test_safe_fetch_returns_body():
    def handler(request):
        return httpx.Response(200, content=b"IMAGEDATA", headers={"content-type": "image/png"})

    resp = _fetch("https://public.example/a.png", handler)
    assert resp is not None
    assert resp.status_code == 200
    assert resp.content == b"IMAGEDATA"


def test_safe_fetch_refuses_private_target():
    def handler(request):  # pragma: no cover — must never be reached
        raise AssertionError("guard let a private target through")

    assert _fetch("http://127.0.0.1/secret", handler) is None


def test_safe_fetch_refuses_redirect_to_private():
    def handler(request):
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        raise AssertionError("followed redirect to private host")

    assert _fetch("https://public.example/start", handler) is None


def test_safe_fetch_refuses_redirect_to_metadata():
    def handler(request):
        if request.url.host == "public.example":
            return httpx.Response(
                301, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        raise AssertionError("followed redirect to metadata IP")

    assert _fetch("https://public.example/start", handler) is None


def test_safe_fetch_refuses_redirect_to_alternate_port():
    def handler(request):
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://cdn.public.example:8080/x"})
        raise AssertionError("followed redirect to alternate port")

    assert _fetch("https://public.example/start", handler) is None


def test_safe_fetch_follows_validated_redirect():
    def handler(request):
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "https://cdn.public.example/real"})
        return httpx.Response(200, content=b"OK")

    resp = _fetch("https://public.example/start", handler)
    assert resp is not None and resp.content == b"OK"


def test_safe_fetch_caps_redirect_hops():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://public.example/loop"})

    assert _fetch("https://public.example/loop", handler) is None


def test_safe_fetch_enforces_size_cap():
    def handler(request):
        return httpx.Response(200, content=b"x" * 1024)

    assert _fetch("https://public.example/big", handler, max_bytes=100) is None
