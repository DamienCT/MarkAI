"""label_guard reaches video_jobs for every render lane (LABEL-GUARD-PERSIST).

The chained and single-call lanes recorded the invented-label guard verdict
only in the in-memory meta dict; store_video's video_jobs params omitted it,
so the review banner (which reads video_jobs) could never show the flags for
those lanes. The native lane rides the guard on its whole-reel ledger entry,
which store_video persists as generation_ledger. These tests pin all three
persistence paths through store_video itself.
"""

import asyncio
import json
from uuid import uuid4

import shared.tools.database as db
import workflows.video.nodes as nodes

_GUARD = {
    "flagged": True,
    "flags": [{"t": 1.0, "shot": 1, "text": ["ENILLE OIL"]}],
}


def _run_store(monkeypatch, meta):
    """Drive store_video with everything external stubbed out."""
    updates: list[tuple[str, dict]] = []

    async def fake_step(*args, **kwargs):
        return None

    async def fake_upload(*args, **kwargs):
        return None

    async def fake_thumb(*args, **kwargs):
        return None

    async def fake_store_content(record):
        return str(uuid4())

    async def fake_update(sql, params=None):
        updates.append((sql, params or {}))
        return 1

    async def fake_query(sql, params=None):
        return []

    async def fake_notify(**kwargs):
        return None

    monkeypatch.setattr(nodes, "update_agent_run_step", fake_step)
    monkeypatch.setattr(nodes, "async_upload_file", fake_upload)
    monkeypatch.setattr(nodes, "_extract_thumbnail", fake_thumb)
    monkeypatch.setattr(nodes, "store_content", fake_store_content)
    monkeypatch.setattr(nodes, "execute_update", fake_update)
    monkeypatch.setattr(nodes, "execute_query", fake_query)
    # store_video imports these lazily from shared.tools.database.
    monkeypatch.setattr(db, "create_notification", fake_notify)
    monkeypatch.setattr(db, "notify_admins", fake_notify)

    state = {
        "run_id": str(uuid4()),
        "brand_id": str(uuid4()),
        "calendar_item_id": str(uuid4()),
        "video_bytes": b"\x00\x00mp4",
        "video_meta": meta,
        "shot_plan": {},
        "hook": "Hook",
        "caption": "A reel caption",
        "hashtags": [],
        "cta": "",
    }
    result = asyncio.run(nodes.store_video(state))
    job_params = next(
        p for sql, p in updates if "INSERT INTO video_jobs" in sql
    )
    return result, job_params


class TestLabelGuardPersistence:
    def test_meta_level_guard_lands_in_video_jobs_params(self, monkeypatch):
        # Chained and single-call lanes both put the guard at meta top level.
        result, job = _run_store(monkeypatch, {"label_guard": _GUARD})
        assert result["status"] == "in_review"
        assert json.loads(job["params"])["label_guard"] == _GUARD

    def test_missing_guard_is_none_not_a_crash(self, monkeypatch):
        result, job = _run_store(monkeypatch, {"provider": "video-forge"})
        assert result["status"] == "in_review"
        assert json.loads(job["params"])["label_guard"] is None

    def test_native_lane_guard_rides_the_generation_ledger(self, monkeypatch):
        # The native multishot lane records the guard on its whole-reel
        # ledger entry — store_video persists that as generation_ledger,
        # which is where the review flags reader already looks.
        meta = {"ledger": [{"shot": 0, "label_guard": _GUARD}]}
        result, job = _run_store(monkeypatch, meta)
        assert result["status"] == "in_review"
        ledger = json.loads(job["ledger"])
        assert ledger[0]["label_guard"] == _GUARD


class TestLaneMetaStillCarriesTheGuard:
    def test_chained_and_single_call_lanes_write_meta_and_store_reads_it(self):
        # The persistence contract has two halves: the lanes stamp
        # meta["label_guard"] (pinned functionally in test_f3_video_forge)
        # and store_video copies meta into the video_jobs params row.
        import inspect

        src = inspect.getsource(nodes.store_video)
        assert '"label_guard": meta.get("label_guard")' in src
