"""Fabric Lakehouse SQL query tool.

Authenticates via Entra ID (Azure AD) client_credentials flow and executes
SQL queries against the Fabric Lakehouse SQL endpoint via pyodbc.
"""

from __future__ import annotations

import logging
import struct
from typing import Any

import httpx
import pyodbc

from shared.config import settings

logger = logging.getLogger(__name__)

_token_cache: dict[str, Any] = {}


async def _get_sql_token() -> str:
    """Obtain an access token for the Fabric SQL endpoint."""
    cached = _token_cache.get("sql_token")
    if cached:
        return cached

    token_url = f"https://login.microsoftonline.com/{settings.FABRIC_TENANT_ID}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(token_url, data={
            "grant_type": "client_credentials",
            "client_id": settings.FABRIC_CLIENT_ID,
            "client_secret": settings.FABRIC_CLIENT_SECRET,
            "scope": "https://database.windows.net/.default",
        })
        resp.raise_for_status()
        token = resp.json()["access_token"]

    _token_cache["sql_token"] = token
    return token


def invalidate_token_cache() -> None:
    """Clear the cached SQL token."""
    _token_cache.clear()


def _get_connection(token: str) -> pyodbc.Connection:
    """Create a pyodbc connection to the Fabric SQL endpoint using AAD token."""
    token_bytes = token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={settings.FABRIC_SQL_ENDPOINT};"
        f"DATABASE={settings.FABRIC_LAKEHOUSE_NAME};"
        "Encrypt=Yes;"
        "TrustServerCertificate=No;"
    )
    return pyodbc.connect(conn_str, attrs_before={1256: token_struct})


async def execute_sql(query: str, params: tuple | None = None) -> list[dict[str, Any]]:
    """Execute a SQL query against the Fabric Lakehouse SQL endpoint and return rows."""
    token = await _get_sql_token()
    try:
        conn = _get_connection(token)
    except pyodbc.Error:
        invalidate_token_cache()
        token = await _get_sql_token()
        conn = _get_connection(token)

    try:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        result = [dict(zip(columns, row)) for row in rows]
        logger.info("SQL query returned %d rows", len(result))
        return result
    finally:
        conn.close()


async def get_product_image_from_bc(product_sku: str) -> str | None:
    """Look up a product image URL from Business Central data in Fabric.

    BC item images are not available in the lakehouse SQL endpoint tables.
    Product images are sourced via supplier websites and web search instead
    (see agents/workflows/content/image_sourcing.py).
    """
    return None


async def get_product_inventory(product_sku: str) -> dict[str, Any] | None:
    """Retrieve inventory/availability data for a product from BC via Fabric."""
    try:
        rows = await execute_sql(
            "SELECT itemNo, locationCode, SUM(remainingQuantity) AS remainingQuantity "
            "FROM itemmodule_itemledgerentry "
            "WHERE itemNo = ? AND remainingQuantity > 0 "
            "GROUP BY itemNo, locationCode",
            (product_sku,),
        )
        return rows[0] if rows else None
    except Exception:
        logger.exception("Failed to query inventory for SKU %s", product_sku)
        return None
