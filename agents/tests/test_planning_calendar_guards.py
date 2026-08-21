"""Regression tests for N-08: a zero-item generation must never wipe the
stored calendar, and batch failures must surface as a failed run instead of a
silent empty success."""

import asyncio
import json
import os
import sys

# Add the agents directory to the path so workflows/shared can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import workflows.planning.nodes as planning_nodes


# ── store_calendar: empty generation never purges ────────────────────


def _store_state(items):
    return {
        "brand_id": "brand-1",
        "calendar_items": items,
        "enabled_channels": ["instagram"],
        "strategy_document": "",
        "scope_weeks": 4,
    }


def _record_db(monkeypatch, calls, stored_ids=("id-1",)):
    async def _delete(*args, **kwargs):
        calls.append(("delete", args, kwargs))
        return 5

    async def _store(db_items, **kwargs):
        calls.append(("store", db_items, kwargs))
        return list(stored_ids)

    async def _summary(*args, **kwargs):
        return ""

    monkeypatch.setattr(planning_nodes, "delete_planned_calendar_items", _delete)
    monkeypatch.setattr(planning_nodes, "store_calendar_items", _store)
    monkeypatch.setattr(planning_nodes, "generate_executive_summary_plain", _summary)


def test_store_calendar_empty_list_aborts_without_purge(monkeypatch):
    calls = []
    _record_db(monkeypatch, calls)

    result = asyncio.run(planning_nodes.store_calendar(_store_state([])))

    assert result["status"] == "failed"
    assert any("untouched" in e for e in result["errors"])
    assert calls == []  # neither the purge nor the insert ran


def test_store_calendar_all_invalid_items_aborts_without_purge(monkeypatch):
    calls = []
    _record_db(monkeypatch, calls)
    # No scheduled_date → CalendarItemValidator rejects every item.
    items = [{"theme": "broken"}, {"theme": "also broken"}]

    result = asyncio.run(planning_nodes.store_calendar(_store_state(items)))

    assert result["status"] == "failed"
    assert calls == []


def test_store_calendar_valid_items_still_purge_and_store(monkeypatch):
    calls = []
    _record_db(monkeypatch, calls)
    items = [
        {
            "scheduled_date": "2026-08-24",
            "scheduled_time": "10:00",
            "platform": "instagram",
            "content_type": "post",
            "theme": "Launch",
            "content_brief": "One valid item.",
        }
    ]

    result = asyncio.run(planning_nodes.store_calendar(_store_state(items)))

    assert result["status"] == "completed"
    assert result["calendar_item_ids"] == ["id-1"]
    ops = [c[0] for c in calls]
    assert ops == ["delete", "store"]  # purge happens, but only with items in hand
    stored = calls[1][1]
    assert len(stored) == 1 and stored[0]["theme"] == "Launch"


# ── generate_calendar: batch failure / zero items ⇒ failed ───────────


def _gen_state():
    return {
        "brand_id": "brand-1",
        "campaigns": [],
        "strategy": {"cadence": {"instagram": {"posts_per_week": 1}}},
        "strategy_document": "",
        "enabled_channels": ["instagram"],
        "existing_items": [],
        "events": [],
        "brand_context": "",
        "scope_weeks": 1,
        "content_format": "posts_only",
    }


def _no_products(monkeypatch):
    async def _get_products(brand_id):
        return []

    monkeypatch.setattr(planning_nodes, "get_products", _get_products)


def test_generate_calendar_batch_failure_marks_run_failed(monkeypatch):
    _no_products(monkeypatch)

    async def _chat(*args, **kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(planning_nodes, "chat_completion", _chat)

    result = asyncio.run(planning_nodes.generate_calendar(_gen_state()))

    assert result["status"] == "failed"
    assert result["calendar_items"] == []
    assert any("LLM down" in e for e in result["errors"])


def test_generate_calendar_zero_items_marks_run_failed(monkeypatch):
    _no_products(monkeypatch)

    async def _chat(*args, **kwargs):
        return "[]"  # LLM "succeeds" but produces nothing

    monkeypatch.setattr(planning_nodes, "chat_completion", _chat)

    result = asyncio.run(planning_nodes.generate_calendar(_gen_state()))

    assert result["status"] == "failed"
    assert result["calendar_items"] == []


def test_generate_calendar_success_path_returns_items(monkeypatch):
    _no_products(monkeypatch)
    item = {
        "campaign_name": "C",
        "scheduled_date": "2026-08-24",
        "scheduled_time": "10:00",
        "platform": "instagram",
        "content_type": "post",
        "pillar": "P",
        "theme": "T",
        "weekly_sub_theme": "S",
        "target_audience": "A",
        "content_brief": "A distinct brief.",
        "visual_direction": "V",
        "cta_type": "shop",
        "product_name": None,
    }

    async def _chat(*args, **kwargs):
        return json.dumps([item])  # exactly posts_per_week=1 → no retry

    monkeypatch.setattr(planning_nodes, "chat_completion", _chat)

    result = asyncio.run(planning_nodes.generate_calendar(_gen_state()))

    assert result.get("status") != "failed"
    assert len(result["calendar_items"]) == 1
    assert result["calendar_items"][0]["platform"] == "instagram"
