#!/usr/bin/env python3
"""Discover columns for key BC tables in Fabric Lakehouse."""

from __future__ import annotations
import json, os, sys
import httpx

FABRIC_TENANT_ID = os.environ.get("FABRIC_TENANT_ID", "")
FABRIC_CLIENT_ID = os.environ.get("FABRIC_CLIENT_ID", "")
FABRIC_CLIENT_SECRET = os.environ.get("FABRIC_CLIENT_SECRET", "")

AUTHORITY_URL = f"https://login.microsoftonline.com/{FABRIC_TENANT_ID}/oauth2/v2.0/token"
PBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"
FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"

TABLES_TO_INSPECT = [
    "itemmodule_item",
    "itemmodule_itemledgerentry",
    "vendormodule_vendor",
    "itemmodule_itemcategory",
    "vendormodule_price_masterlist",
]


def get_token(scope: str) -> str:
    resp = httpx.post(AUTHORITY_URL, data={
        "grant_type": "client_credentials",
        "client_id": FABRIC_CLIENT_ID,
        "client_secret": FABRIC_CLIENT_SECRET,
        "scope": scope,
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def discover_lakehouse(token: str) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    resp = httpx.get(f"{FABRIC_API_BASE}/workspaces", headers=headers, timeout=30)
    resp.raise_for_status()
    for ws in resp.json().get("value", []):
        items_resp = httpx.get(
            f"{FABRIC_API_BASE}/workspaces/{ws['id']}/items",
            headers=headers, timeout=30,
        )
        items_resp.raise_for_status()
        for item in items_resp.json().get("value", []):
            if item.get("type", "").lower() == "lakehouse" and "lh_bronze" in item.get("displayName", "").lower():
                return ws["id"], item["id"]
    print("Lakehouse not found")
    sys.exit(1)


def get_table_columns(fabric_token: str, ws_id: str, lh_id: str, table_name: str) -> list[dict]:
    """Get column info for a table via the Fabric lakehouse tables API."""
    headers = {"Authorization": f"Bearer {fabric_token}"}
    url = f"{FABRIC_API_BASE}/workspaces/{ws_id}/lakehouses/{lh_id}/tables/{table_name}/columns"
    try:
        resp = httpx.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json().get("data", []) or resp.json().get("value", [])
    except Exception:
        pass
    return []


def get_sample_rows(pbi_token: str, ws_id_pbi: str, ds_id: str, table_name: str, limit: int = 3) -> list[dict]:
    """Get sample rows using DAX TOPN query."""
    headers = {"Authorization": f"Bearer {pbi_token}", "Content-Type": "application/json"}
    dax = f"EVALUATE TOPN({limit}, '{table_name}')"
    body = {"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}}
    url = f"{PBI_API_BASE}/groups/{ws_id_pbi}/datasets/{ds_id}/executeQueries"
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [{}])[0].get("tables", [{}])[0].get("rows", [])
    except httpx.HTTPStatusError as e:
        print(f"  DAX failed ({e.response.status_code}): {e.response.text[:200]}")
        return []


def discover_pbi_dataset(token: str) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    resp = httpx.get(f"{PBI_API_BASE}/groups", headers=headers, timeout=30)
    resp.raise_for_status()
    for ws in resp.json().get("value", []):
        ds_resp = httpx.get(f"{PBI_API_BASE}/groups/{ws['id']}/datasets", headers=headers, timeout=30)
        ds_resp.raise_for_status()
        for ds in ds_resp.json().get("value", []):
            if "lh_bronze" in ds.get("name", "").lower():
                return ws["id"], ds["id"]
    print("Dataset not found")
    sys.exit(1)


def main():
    print("Authenticating...")
    fabric_token = get_token("https://api.fabric.microsoft.com/.default")
    pbi_token = get_token("https://analysis.windows.net/powerbi/api/.default")

    print("Discovering lakehouse...")
    ws_id, lh_id = discover_lakehouse(fabric_token)
    print(f"  Fabric: workspace={ws_id}, lakehouse={lh_id}")

    pbi_ws_id, ds_id = discover_pbi_dataset(pbi_token)
    print(f"  PBI: workspace={pbi_ws_id}, dataset={ds_id}\n")

    output_lines = []

    for table in TABLES_TO_INSPECT:
        print(f"--- {table} ---")
        output_lines.append(f"{'='*70}")
        output_lines.append(f"TABLE: {table}")
        output_lines.append(f"{'='*70}")

        # Try columns API
        cols = get_table_columns(fabric_token, ws_id, lh_id, table)
        if cols:
            output_lines.append("\nCOLUMNS (from Fabric API):")
            for c in cols:
                name = c.get("name", c.get("columnName", "?"))
                dtype = c.get("type", c.get("dataType", "?"))
                output_lines.append(f"  {name:<40} {dtype}")
                print(f"  col: {name} ({dtype})")

        # Try sample rows via DAX
        print(f"  Fetching sample rows...")
        rows = get_sample_rows(pbi_token, pbi_ws_id, ds_id, table, limit=3)
        if rows:
            # Extract column names from first row
            col_names = list(rows[0].keys())
            output_lines.append(f"\nCOLUMN NAMES (from sample data, {len(col_names)} columns):")
            for cn in sorted(col_names):
                sample_val = rows[0].get(cn)
                val_str = str(sample_val)[:60] if sample_val is not None else "NULL"
                output_lines.append(f"  {cn:<50} sample: {val_str}")
                print(f"  {cn}: {val_str}")

            output_lines.append(f"\nSAMPLE ROWS ({len(rows)}):")
            output_lines.append(json.dumps(rows, indent=2, default=str))
        else:
            output_lines.append("\n(Could not fetch sample rows via DAX)")

        output_lines.append("")
        print()

    output = "\n".join(output_lines) + "\n"
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "BC-COLUMNS.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Saved to: {out_path}")


if __name__ == "__main__":
    main()
