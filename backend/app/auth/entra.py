import asyncio
import logging
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from app.config import settings

logger = logging.getLogger(__name__)

_jwks_client: PyJWKClient | None = None


async def _get_jwks_client(tenant_id: str) -> PyJWKClient:
    """Return a cached PyJWKClient for the given tenant."""
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        _jwks_client = PyJWKClient(jwks_url)
    return _jwks_client


async def validate_entra_token(token: str) -> dict[str, Any]:
    """
    Validate a JWT issued by Microsoft Entra ID.
    Returns the decoded token claims if valid.
    Raises jwt.exceptions.PyJWTError or related errors on failure.
    """
    client = await _get_jwks_client(settings.AZURE_AD_TENANT_ID)
    signing_key = await asyncio.to_thread(client.get_signing_key_from_jwt, token)

    issuer = f"https://login.microsoftonline.com/{settings.AZURE_AD_TENANT_ID}/v2.0"

    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.AZURE_AD_CLIENT_ID,
        issuer=issuer,
        options={"verify_aud": True},
    )

    return claims


def extract_groups(claims: dict[str, Any]) -> list[str]:
    """Extract group IDs from JWT claims."""
    groups = claims.get("groups", [])
    if isinstance(groups, list):
        return groups
    return []


def invalidate_jwks_cache() -> None:
    """Clear the cached JWKS client -- useful for key rotation."""
    global _jwks_client
    _jwks_client = None


# ---------------------------------------------------------------------------
# Microsoft Graph API helpers (client credentials flow)
# ---------------------------------------------------------------------------

_graph_token_cache: dict[str, Any] = {}
_graph_token_lock = asyncio.Lock()


def _get_token_lock() -> asyncio.Lock:
    """Return the module-level token lock."""
    return _graph_token_lock


async def get_graph_api_token() -> str:
    """
    Obtain an access token for Microsoft Graph API using client credentials.
    Caches the token until it expires. Thread-safe via asyncio.Lock.
    """
    import time

    cached = _graph_token_cache.get("token")
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["access_token"]

    async with _get_token_lock():
        # Double-check after acquiring lock
        cached = _graph_token_cache.get("token")
        if cached and cached["expires_at"] > time.time() + 60:
            return cached["access_token"]

        tenant_id = settings.AZURE_AD_TENANT_ID
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_url,
                data={
                    "client_id": settings.AZURE_AD_CLIENT_ID,
                    "client_secret": settings.AZURE_AD_CLIENT_SECRET,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        _graph_token_cache["token"] = {
            "access_token": data["access_token"],
            "expires_at": time.time() + data.get("expires_in", 3600),
        }
        return data["access_token"]


async def search_graph_users(query: str) -> list[dict[str, Any]]:
    """
    Search Entra ID users by displayName or mail using Microsoft Graph API.
    Returns a list of {id, displayName, mail, userPrincipalName}.
    """
    token = await get_graph_api_token()

    # Sanitise the query for OData $filter — strip control chars and escape quotes
    import re

    safe_q = re.sub(r"[\x00-\x1f\x7f]", "", query)  # strip control characters
    safe_q = safe_q.replace("\\", "\\\\").replace("'", "''")

    graph_url = "https://graph.microsoft.com/v1.0/users"
    params = {
        "$filter": (
            f"startswith(mail,'{safe_q}') or startswith(userPrincipalName,'{safe_q}')"
        ),
        "$select": "id,displayName,mail,userPrincipalName,jobTitle,department",
        "$top": "20",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            graph_url,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()

    return data.get("value", [])


async def get_graph_users_by_ids(user_ids: list[str]) -> list[dict[str, Any]]:
    """
    Fetch user details from Graph API for a list of Entra object IDs.
    """
    if not user_ids:
        return []

    token = await get_graph_api_token()

    # Use $filter with 'in' operator for batch lookup
    ids_filter = ",".join(f"'{uid}'" for uid in user_ids)
    graph_url = "https://graph.microsoft.com/v1.0/users"
    params = {
        "$filter": f"id in ({ids_filter})",
        "$select": "id,displayName,mail,userPrincipalName",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            graph_url,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()

    return data.get("value", [])


async def check_user_in_security_group(user_id: str, group_id: str) -> bool:
    """
    Check if a user is a member of a specific security group via Graph API.
    Uses the transitive memberOf check.
    """
    if not group_id:
        return False

    token = await get_graph_api_token()

    url = f"https://graph.microsoft.com/v1.0/users/{user_id}/checkMemberGroups"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json={"groupIds": [group_id]},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        data = resp.json()

    return group_id in data.get("value", [])
