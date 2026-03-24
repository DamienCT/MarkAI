#!/usr/bin/env python3
"""Discover tables available in Microsoft Fabric Lakehouse.

Tries multiple API approaches to list tables:
1. Fabric REST API (lakehouse tables endpoint)
2. Power BI executeQueries with DAX INFO.TABLES()
3. Power BI executeQueries with EVALUATE on known table patterns
4. SQL endpoint via pyodbc (list tables + sample columns)

Requires env vars: FABRIC_TENANT_ID, FABRIC_CLIENT_ID, FABRIC_CLIENT_SECRET,
                   FABRIC_LAKEHOUSE_NAME, FABRIC_SQL_ENDPOINT

Usage:
    python scripts/bc-table-discovery.py
"""

from __future__ import annotations

import json
import os
import struct
import sys

import httpx
import pyodbc

# ── Configuration from environment ──────────────────────────────────

FABRIC_TENANT_ID = os.environ.get("FABRIC_TENANT_ID", "")
FABRIC_CLIENT_ID = os.environ.get("FABRIC_CLIENT_ID", "")
FABRIC_CLIENT_SECRET = os.environ.get("FABRIC_CLIENT_SECRET", "")
FABRIC_LAKEHOUSE_NAME = os.environ.get("FABRIC_LAKEHOUSE_NAME", "lh_bronze")
FABRIC_SQL_ENDPOINT = os.environ.get("FABRIC_SQL_ENDPOINT", "")

AUTHORITY_URL = f"https://login.microsoftonline.com/{FABRIC_TENANT_ID}/oauth2/v2.0/token"
PBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"
FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"


def get_token(scope: str) -> str:
    """Obtain an access token via OAuth2 client credentials flow."""
    resp = httpx.post(
        AUTHORITY_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": FABRIC_CLIENT_ID,
            "client_secret": FABRIC_CLIENT_SECRET,
            "scope": scope,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def discover_via_pbi(token: str) -> tuple[str, str, str]:
    """Find workspace ID, dataset ID, and workspace name via Power BI API."""
    headers = {"Authorization": f"Bearer {token}"}

    resp = httpx.get(f"{PBI_API_BASE}/groups", headers=headers, timeout=30)
    resp.raise_for_status()
    workspaces = resp.json().get("value", [])
    print(f"  Found {len(workspaces)} workspace(s).")

    for ws in workspaces:
        ws_id = ws["id"]
        ws_name = ws.get("name", "unnamed")

        ds_resp = httpx.get(
            f"{PBI_API_BASE}/groups/{ws_id}/datasets",
            headers=headers,
            timeout=30,
        )
        ds_resp.raise_for_status()
        datasets = ds_resp.json().get("value", [])

        for ds in datasets:
            ds_name = ds.get("name", "")
            if FABRIC_LAKEHOUSE_NAME.lower() in ds_name.lower():
                print(f"  Matched: workspace='{ws_name}' ({ws_id}), dataset='{ds_name}' ({ds['id']})")
                return ws_id, ds["id"], ws_name

    print("  ERROR: No dataset found matching the lakehouse name.", file=sys.stderr)
    sys.exit(1)


def try_fabric_api(workspace_id: str) -> list[str] | None:
    """Try Fabric REST API to list lakehouse tables."""
    print("\n[Method 1] Trying Fabric REST API...")
    try:
        token = get_token("https://api.fabric.microsoft.com/.default")
        headers = {"Authorization": f"Bearer {token}"}

        # List items in workspace to find the lakehouse item ID
        resp = httpx.get(
            f"{FABRIC_API_BASE}/workspaces/{workspace_id}/items",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("value", [])

        lakehouse_id = None
        for item in items:
            if (
                item.get("type", "").lower() == "lakehouse"
                and FABRIC_LAKEHOUSE_NAME.lower() in item.get("displayName", "").lower()
            ):
                lakehouse_id = item["id"]
                print(f"  Found lakehouse item: {item['displayName']} ({lakehouse_id})")
                break

        if not lakehouse_id:
            print("  Lakehouse item not found via Fabric API.")
            return None

        # List tables in the lakehouse (paginated — follow continuationToken)
        all_tables: list[dict] = []
        url = f"{FABRIC_API_BASE}/workspaces/{workspace_id}/lakehouses/{lakehouse_id}/tables"
        params: dict[str, str] = {}

        while True:
            resp = httpx.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            body = resp.json()

            page = body.get("data", []) or body.get("value", [])
            all_tables.extend(page)
            print(f"  Fetched page: {len(page)} tables (total so far: {len(all_tables)})")

            # Check for continuation token
            cont_token = body.get("continuationToken")
            cont_uri = body.get("continuationUri")

            if cont_token:
                params["continuationToken"] = cont_token
            elif cont_uri:
                # Some API versions return a full URI
                url = cont_uri
                params = {}
            else:
                break

        if all_tables:
            names = [t.get("name", t.get("tableName", "unknown")) for t in all_tables]
            print(f"  Found {len(names)} table(s) total.")
            return names

        print(f"  Response structure: {json.dumps(body, indent=2)[:500]}")
        return None

    except httpx.HTTPStatusError as e:
        print(f"  Fabric API returned {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"  Fabric API failed: {e}")
        return None


def try_dax_info_tables(pbi_token: str, workspace_id: str, dataset_id: str) -> list[str] | None:
    """Try DAX INFO.TABLES() query."""
    print("\n[Method 2] Trying DAX INFO.TABLES()...")
    try:
        headers = {
            "Authorization": f"Bearer {pbi_token}",
            "Content-Type": "application/json",
        }
        body = {
            "queries": [
                {"query": "EVALUATE SELECTCOLUMNS(INFO.TABLES(), \"Name\", [Name], \"IsHidden\", [IsHidden])"}
            ],
            "serializerSettings": {"includeNulls": True},
        }

        resp = httpx.post(
            f"{PBI_API_BASE}/groups/{workspace_id}/datasets/{dataset_id}/executeQueries",
            headers=headers,
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        rows = data.get("results", [{}])[0].get("tables", [{}])[0].get("rows", [])
        visible = [r["[Name]"] for r in rows if not r.get("[IsHidden]", False)]
        print(f"  Found {len(visible)} visible table(s).")
        return visible

    except httpx.HTTPStatusError as e:
        print(f"  DAX query returned {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"  DAX query failed: {e}")
        return None


def try_dmv_tables(pbi_token: str, workspace_id: str, dataset_id: str) -> list[str] | None:
    """Try DAX with TMSCHEMA_TABLES DMV."""
    print("\n[Method 3] Trying TMSCHEMA_TABLES DMV...")
    try:
        headers = {
            "Authorization": f"Bearer {pbi_token}",
            "Content-Type": "application/json",
        }
        body = {
            "queries": [
                {"query": "SELECT [Name] FROM $SYSTEM.TMSCHEMA_TABLES WHERE [IsHidden] = FALSE"}
            ],
            "serializerSettings": {"includeNulls": True},
        }

        resp = httpx.post(
            f"{PBI_API_BASE}/groups/{workspace_id}/datasets/{dataset_id}/executeQueries",
            headers=headers,
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        rows = data.get("results", [{}])[0].get("tables", [{}])[0].get("rows", [])
        names = [r.get("[Name]", r.get("Name", "")) for r in rows if r]
        print(f"  Found {len(names)} table(s).")
        return names

    except httpx.HTTPStatusError as e:
        print(f"  DMV query returned {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"  DMV query failed: {e}")
        return None


def try_dataset_details(pbi_token: str, workspace_id: str, dataset_id: str) -> list[str] | None:
    """Try getting dataset details which may include table info."""
    print("\n[Method 4] Trying dataset discover endpoint...")
    try:
        headers = {"Authorization": f"Bearer {pbi_token}"}

        # Try the discover endpoint
        resp = httpx.get(
            f"{PBI_API_BASE}/groups/{workspace_id}/datasets/{dataset_id}",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"  Dataset info: {json.dumps(data, indent=2)[:500]}")

        # Try to get datasources
        resp2 = httpx.get(
            f"{PBI_API_BASE}/groups/{workspace_id}/datasets/{dataset_id}/datasources",
            headers=headers,
            timeout=30,
        )
        if resp2.status_code == 200:
            ds_data = resp2.json()
            print(f"  Datasources: {json.dumps(ds_data, indent=2)[:500]}")

        return None  # This method only gathers info

    except httpx.HTTPStatusError as e:
        print(f"  Dataset details returned {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"  Dataset details failed: {e}")
        return None


def try_sql_endpoint() -> list[str] | None:
    """Try listing tables via the Fabric SQL endpoint using pyodbc."""
    print("\n[Method 5] Trying Fabric SQL endpoint via pyodbc...")
    if not FABRIC_SQL_ENDPOINT:
        print("  FABRIC_SQL_ENDPOINT not set, skipping.")
        return None

    try:
        token = get_token("https://database.windows.net/.default")
        token_bytes = token.encode("utf-16-le")
        token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

        conn_str = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={FABRIC_SQL_ENDPOINT};"
            f"DATABASE={FABRIC_LAKEHOUSE_NAME};"
            "Encrypt=Yes;"
            "TrustServerCertificate=No;"
        )
        conn = pyodbc.connect(conn_str, attrs_before={1256: token_struct})
        cursor = conn.cursor()

        # List all tables using INFORMATION_SCHEMA
        cursor.execute(
            "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_SCHEMA, TABLE_NAME"
        )
        rows = cursor.fetchall()
        table_names = [row[1] for row in rows]
        print(f"  Found {len(table_names)} table(s) via SQL endpoint.")

        conn.close()
        return table_names if table_names else None

    except Exception as e:
        print(f"  SQL endpoint failed: {e}")
        return None


def show_sample_columns(table_names: list[str]) -> None:
    """Connect via SQL endpoint and show column names for key tables."""
    print("\n" + "=" * 70)
    print("COLUMN DISCOVERY (via SQL endpoint)")
    print("=" * 70)

    if not FABRIC_SQL_ENDPOINT:
        print("  FABRIC_SQL_ENDPOINT not set, skipping column discovery.")
        return

    # Focus on the key BC tables
    key_tables = [
        "itemmodule_item",
        "itemmodule_itemledgerentry",
        "vendormodule_vendor",
        "itemmodule_itemcategory",
    ]
    tables_to_check = [t for t in key_tables if t in table_names]
    if not tables_to_check:
        # Fall back to first 5 tables
        tables_to_check = table_names[:5]

    try:
        token = get_token("https://database.windows.net/.default")
        token_bytes = token.encode("utf-16-le")
        token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

        conn_str = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={FABRIC_SQL_ENDPOINT};"
            f"DATABASE={FABRIC_LAKEHOUSE_NAME};"
            "Encrypt=Yes;"
            "TrustServerCertificate=No;"
        )
        conn = pyodbc.connect(conn_str, attrs_before={1256: token_struct})
        cursor = conn.cursor()

        for table in tables_to_check:
            print(f"\n  Table: {table}")
            print(f"  {'-' * 60}")
            cursor.execute(
                "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
                (table,),
            )
            cols = cursor.fetchall()
            for col_name, data_type in cols:
                print(f"    {col_name:<40} {data_type}")

        conn.close()

    except Exception as e:
        print(f"  Column discovery failed: {e}")


def write_output(table_names: list[str], workspace_id: str, dataset_id: str) -> None:
    """Write the discovered tables to FABRIC-TABLES.txt."""
    table_names.sort()

    lines = []
    lines.append("=" * 70)
    lines.append("FABRIC LAKEHOUSE TABLE DISCOVERY")
    lines.append(f"Lakehouse: {FABRIC_LAKEHOUSE_NAME}")
    lines.append(f"Workspace: {workspace_id}")
    lines.append(f"Dataset:   {dataset_id}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"{'#':<4} {'Table Name'}")
    lines.append(f"{'-'*4} {'-'*60}")

    for i, name in enumerate(table_names, 1):
        lines.append(f"{i:<4} {name}")

    lines.append("")
    lines.append("-" * 70)
    lines.append("SUGGESTED .env MAPPINGS (copy the ones you want):")
    lines.append("-" * 70)
    lines.append("")

    for name in table_names:
        safe_key = name.upper().replace(" ", "_").replace("-", "_")
        lines.append(f"BC_TABLE_{safe_key}={name}")

    output = "\n".join(lines) + "\n"
    print(output)

    output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "FABRIC-TABLES.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Saved to: {output_path}")


def main() -> None:
    missing = []
    for var in ["FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET"]:
        if not os.environ.get(var):
            missing.append(var)

    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    # Step 1: Get PBI token and discover dataset
    print("Authenticating with Microsoft Entra ID (Power BI scope)...")
    pbi_token = get_token("https://analysis.windows.net/powerbi/api/.default")
    print("Authenticated.\n")

    print("Discovering lakehouse dataset...")
    workspace_id, dataset_id, ws_name = discover_via_pbi(pbi_token)

    # Step 2: Try each method to list tables
    table_names = None

    # Method 1: Fabric REST API
    table_names = try_fabric_api(workspace_id)

    # Method 2: DAX INFO.TABLES()
    if not table_names:
        table_names = try_dax_info_tables(pbi_token, workspace_id, dataset_id)

    # Method 3: DMV
    if not table_names:
        table_names = try_dmv_tables(pbi_token, workspace_id, dataset_id)

    # Method 4: Dataset details (info only)
    if not table_names:
        try_dataset_details(pbi_token, workspace_id, dataset_id)

    # Method 5: SQL endpoint via pyodbc
    if not table_names:
        table_names = try_sql_endpoint()

    if table_names:
        print(f"\nSuccessfully discovered {len(table_names)} tables.\n")
        write_output(table_names, workspace_id, dataset_id)

        # Phase 2: Show sample columns for key tables
        show_sample_columns(table_names)
    else:
        print(
            "\nCould not list tables automatically. The service principal may need "
            "'Build' permission on the dataset, or admin consent for Dataset.Read.All. "
            "Check the output above for more details.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
