import asyncio
import logging
import re
import struct
import time
from typing import Any

import httpx
import pyodbc

from app.config import settings

logger = logging.getLogger(__name__)

_TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Whitelist of allowed table names to prevent SQL injection via config
_ALLOWED_TABLES = {
    "itemmodule_item",
    "itemmodule_itemcategory",
    "vendormodule_vendor",
    "itemmodule_itemledgerentry",
    # Legacy/alternate names
    "items",
    "item_categories",
    "vendors",
    "item_ledger_entries",
}


def _safe_table_name(name: str) -> str:
    """Validate table name against regex AND whitelist to prevent SQL injection."""
    if not _TABLE_NAME_RE.match(name):
        raise ValueError(f"Invalid table name: {name}")
    if name not in _ALLOWED_TABLES:
        raise ValueError(f"Table name not in whitelist: {name}")
    return name


_token_cache: dict[str, Any] = {}


async def _get_sql_token() -> str:
    """Get an access token for the Fabric SQL endpoint."""
    cached = _token_cache.get("sql_token")
    cached_at = _token_cache.get("sql_token_at", 0)
    if cached and (time.time() - cached_at) < 3000:  # 50 min TTL (tokens last 60 min)
        return cached

    token_url = f"https://login.microsoftonline.com/{settings.FABRIC_TENANT_ID}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.FABRIC_CLIENT_ID,
                "client_secret": settings.FABRIC_CLIENT_SECRET,
                "scope": "https://database.windows.net/.default",
            },
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]

    _token_cache["sql_token"] = token
    _token_cache["sql_token_at"] = time.time()
    return token


def invalidate_token_cache() -> None:
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


# ── Connection cache (reuse within token lifetime) ──────────────────────
_conn_cache: dict[str, Any] = {}  # keys: "conn", "created_at"
_CONN_MAX_AGE = 55 * 60  # 55 minutes (tokens last 60 min)


def _get_cached_connection(token: str) -> pyodbc.Connection:
    """Return a cached connection if still fresh, otherwise create a new one."""
    cached_conn = _conn_cache.get("conn")
    created_at = _conn_cache.get("created_at", 0)

    if cached_conn is not None and (time.time() - created_at) < _CONN_MAX_AGE:
        try:
            # Quick check that the connection is still alive
            cached_conn.cursor().execute("SELECT 1")
            return cached_conn
        except Exception:
            # Connection is stale, close and recreate
            try:
                cached_conn.close()
            except Exception:
                pass

    conn = _get_connection(token)
    _conn_cache["conn"] = conn
    _conn_cache["created_at"] = time.time()
    return conn


def _run_query_sync(
    token: str, query: str, params: tuple | None
) -> list[dict[str, Any]]:
    """Run a blocking pyodbc query (designed to be called via asyncio.to_thread)."""
    conn = _get_cached_connection(token)
    try:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except pyodbc.Error:
        # On error, invalidate the cached connection so next call creates a new one
        _conn_cache.pop("conn", None)
        _conn_cache.pop("created_at", None)
        raise


async def execute_sql(query: str, params: tuple | None = None) -> list[dict[str, Any]]:
    """Execute a SQL query against the Fabric Lakehouse SQL endpoint."""
    token = await _get_sql_token()
    try:
        return await asyncio.to_thread(_run_query_sync, token, query, params)
    except pyodbc.Error:
        invalidate_token_cache()
        token = await _get_sql_token()
        return await asyncio.to_thread(_run_query_sync, token, query, params)


async def list_companies() -> list[str]:
    """Get all unique BC company names from the items table."""
    table = _safe_table_name(settings.BC_TABLE_ITEMS)
    rows = await execute_sql(f"SELECT DISTINCT Company FROM {table} ORDER BY Company")
    return [r["Company"] for r in rows]


async def list_locations_for_company(company: str) -> list[str]:
    """Get all unique stock locations from item ledger entries for a given company."""
    table = _safe_table_name(settings.BC_TABLE_ITEM_LEDGER_ENTRIES)
    rows = await execute_sql(
        f"SELECT DISTINCT locationCode FROM {table} WHERE Company = ? AND locationCode != '' ORDER BY locationCode",
        (company,),
    )
    return [r["locationCode"] for r in rows]


async def get_items(
    company: str, vendor_filter: list[str] | None = None, exclude_blocked: bool = True
) -> list[dict[str, Any]]:
    """Fetch items from BC for a specific company, excluding blocked items."""
    table = _safe_table_name(settings.BC_TABLE_ITEMS)
    query = f"SELECT * FROM {table} WHERE Company = ?"
    params = [company]

    if exclude_blocked:
        query += " AND blocked = 0"

    if vendor_filter:
        placeholders = ",".join(["?"] * len(vendor_filter))
        query += f" AND vendorNo IN ({placeholders})"
        params.extend(vendor_filter)

    return await execute_sql(query, tuple(params))


async def get_active_stock(company: str, locations: list[str]) -> list[dict[str, Any]]:
    """
    Get items with remaining stock > 0 at the specified locations,
    excluding blocked items.
    """
    items_table = _safe_table_name(settings.BC_TABLE_ITEMS)
    ledger_table = _safe_table_name(settings.BC_TABLE_ITEM_LEDGER_ENTRIES)

    loc_placeholders = ",".join(["?"] * len(locations))

    query = f"""
        SELECT
            ile.itemNo,
            ile.locationCode,
            SUM(ile.remainingQuantity) as totalRemaining,
            i.description,
            i.description2,
            i.vendorNo,
            i.itemCategoryCode,
            i.unitPrice,
            i.unitCost,
            i.baseUnitOfMeasure,
            i.type
        FROM {ledger_table} ile
        INNER JOIN {items_table} i
            ON ile.itemNo = i.no AND ile.Company = i.Company
        WHERE ile.Company = ?
            AND ile.locationCode IN ({loc_placeholders})
            AND i.blocked = 0
        GROUP BY
            ile.itemNo, ile.locationCode,
            i.description, i.description2, i.vendorNo,
            i.itemCategoryCode, i.unitPrice, i.unitCost,
            i.baseUnitOfMeasure, i.type
        HAVING SUM(ile.remainingQuantity) > 0
        ORDER BY ile.itemNo
    """
    params = (company, *locations)
    return await execute_sql(query, params)


async def get_item_categories(company: str) -> list[dict[str, Any]]:
    """Fetch item categories for a company."""
    table = _safe_table_name(settings.BC_TABLE_ITEM_CATEGORIES)
    return await execute_sql(f"SELECT * FROM {table} WHERE Company = ?", (company,))


async def get_vendors(company: str) -> list[dict[str, Any]]:
    """Fetch vendors for a company."""
    table = _safe_table_name(settings.BC_TABLE_VENDORS)
    return await execute_sql(
        f"SELECT * FROM {table} WHERE Company = ? AND blocked = ' ' ORDER BY name",
        (company,),
    )


async def get_expiring_items(
    company: str, locations: list[str], days_ahead: int = 30
) -> list[dict[str, Any]]:
    """Get items expiring within the next N days at the given locations."""
    ledger_table = _safe_table_name(settings.BC_TABLE_ITEM_LEDGER_ENTRIES)
    items_table = _safe_table_name(settings.BC_TABLE_ITEMS)
    loc_placeholders = ",".join(["?"] * len(locations))

    query = f"""
        SELECT
            ile.itemNo, ile.locationCode, ile.lotNo,
            ile.expirationDate, ile.remainingQuantity,
            i.description, i.description2, i.vendorNo, i.itemCategoryCode
        FROM {ledger_table} ile
        INNER JOIN {items_table} i
            ON ile.itemNo = i.no AND ile.Company = i.Company
        WHERE ile.Company = ?
            AND ile.locationCode IN ({loc_placeholders})
            AND ile.remainingQuantity > 0
            AND i.blocked = 0
            AND ile.expirationDate >= GETDATE()
            AND ile.expirationDate <= DATEADD(day, ?, GETDATE())
        ORDER BY ile.expirationDate
    """
    params = (company, *locations, days_ahead)
    return await execute_sql(query, params)


async def get_new_items(company: str, days_back: int = 30) -> list[dict[str, Any]]:
    """Get items created or modified in the last N days."""
    table = _safe_table_name(settings.BC_TABLE_ITEMS)
    query = f"""
        SELECT * FROM {table}
        WHERE Company = ? AND blocked = 0
            AND lastDateModified >= DATEADD(day, ?, GETDATE())
        ORDER BY lastDateModified DESC
    """
    return await execute_sql(query, (company, -days_back))
