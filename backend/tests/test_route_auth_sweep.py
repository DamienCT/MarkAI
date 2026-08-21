"""Auth sweep — every /api/v1 route must reject unauthenticated requests.

Walks the real app's route table so newly added routes are swept
automatically: a route that is meant to be public must be added to
PUBLIC_ROUTES explicitly, otherwise this test fails loudly.
"""

import re

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.main import app

# Routes that intentionally serve without a bearer token, keyed by the exact
# registered path template. Keep the reason next to each entry.
#
# NOTE: /api/v1/files/* and /api/v1/brands/{id}/logos/{label} are no longer
# public — they require media auth (X-Media-Token / signed URL / bearer, see
# app.utils.media_sign) and are swept like every other route. The
# _enforce_media_auth fixture below configures a token so the gate enforces
# in the test env (blank token falls open outside production by design).
PUBLIC_ROUTES = {
    # n8n callback — authenticated via X-Webhook-Secret header, not a JWT.
    "/api/v1/webhooks/publish-result": "webhook-secret auth",
    # Read internally by the agents service; exposes model IDs only.
    "/api/v1/providers/active": "agents-service model lookup",
}


@pytest.fixture(autouse=True)
def _enforce_media_auth(monkeypatch):
    """Media endpoints only fail open when MEDIA_PROXY_TOKEN is blank outside
    production — configure one so the sweep verifies the media auth gate."""
    monkeypatch.setattr(
        "app.utils.media_sign._media_token", lambda: "sweep-media-token"
    )

# A UUID-shaped dummy satisfies str, uuid, and :path converters alike; auth
# rejects the request before path-param validation ever runs.
_DUMMY_PARAM = "00000000-0000-0000-0000-000000000000"


def _api_v1_routes():
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
    ]


def test_whitelist_entries_still_exist():
    """A stale whitelist entry hides nothing but must be pruned."""
    registered = {route.path for route in _api_v1_routes()}
    stale = set(PUBLIC_ROUTES) - registered
    assert not stale, f"Whitelisted routes no longer registered: {sorted(stale)}"


def test_sweep_covers_a_sane_number_of_routes():
    """Guard against the sweep silently matching nothing (e.g. after a
    prefix rename) and green-lighting an unswept app."""
    assert len(_api_v1_routes()) > 50


@pytest.mark.anyio
async def test_every_api_v1_route_rejects_unauthenticated_requests():
    failures = []
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for route in _api_v1_routes():
            if route.path in PUBLIC_ROUTES:
                continue
            url = re.sub(r"\{[^}]+\}", _DUMMY_PARAM, route.path)
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                # An exception means the handler ran (e.g. reached for the
                # real DB) — i.e. the route let an unauthenticated request
                # through. Record it instead of aborting the sweep.
                try:
                    response = await client.request(method, url)
                except Exception as exc:
                    failures.append(
                        f"{method} {route.path} -> raised {type(exc).__name__}"
                    )
                    continue
                if response.status_code not in (401, 403):
                    failures.append(
                        f"{method} {route.path} -> {response.status_code}"
                    )
    assert not failures, (
        "Routes served an unauthenticated request (add deliberate public "
        "routes to PUBLIC_ROUTES):\n" + "\n".join(failures)
    )
