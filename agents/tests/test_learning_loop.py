"""Regression tests for the learning loop and persistence contracts.

Covers P0-06 / N-10 (evaluation → adaptation queue plumbing, no fake
auto-apply), N-18 (store_content null-byte sanitation) and the SQL side of
N-06 (upsert_product persists image_url + metadata).
"""

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import shared.tools.database as db
import workflows.adaptation.nodes as adaptation_nodes
import workflows.evaluation.nodes as evaluation_nodes


# ── Fake session plumbing ────────────────────────────────────────────


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    @property
    def rowcount(self):
        return len(self._rows)


class FakeSession:
    """Captures (sql, params) pairs; hands out queued results in order."""

    def __init__(self, results=None):
        self.executed = []
        self.commits = 0
        self._results = list(results or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params))
        return self._results.pop(0) if self._results else FakeResult()

    async def commit(self):
        self.commits += 1


def _patch_session(monkeypatch, session):
    monkeypatch.setattr(db, "async_session_factory", lambda: session)


# ── P0-06: notes-encoded rows are lifted and pass the tier filter ────


def test_notes_encoded_row_is_lifted_and_passes_tier_filter(monkeypatch):
    notes = json.dumps(
        {
            "tier": 1,
            "confidence": 0.9,
            # historical rows double-encode data as a JSON string
            "data": json.dumps({"title": "Post at 6pm"}),
        }
    )
    row = {
        "id": "a1",
        "adaptation_notes": notes,
        "adapted_text": "Shift posting time to 6pm",
        "status": "proposed",
    }
    session = FakeSession([FakeResult([row])])
    _patch_session(monkeypatch, session)

    rows = asyncio.run(db.get_pending_adaptations("b-1"))

    assert rows[0]["tier"] == 1
    assert rows[0]["confidence"] == pytest.approx(0.9)
    assert rows[0]["data"] == {"title": "Post at 6pm"}
    assert rows[0]["description"] == "Shift posting time to 6pm"
    # The exact filters the adaptation nodes run:
    assert [a for a in rows if a.get("tier") == 1]
    assert not [a for a in rows if a.get("tier") in (2, 3)]


def test_lift_tolerates_legacy_free_text_notes(monkeypatch):
    row = {
        "id": "a2",
        "adaptation_notes": "shortened for stories",
        "adapted_text": "Legacy variant",
        "status": "queued",
    }
    session = FakeSession([FakeResult([row])])
    _patch_session(monkeypatch, session)

    rows = asyncio.run(db.get_pending_adaptations("b-1"))

    assert rows[0]["tier"] == 2  # unknown → human review
    assert rows[0]["confidence"] == pytest.approx(0.5)
    assert rows[0]["data"] == {}


def test_pending_query_excludes_decided_history(monkeypatch):
    session = FakeSession([FakeResult([])])
    _patch_session(monkeypatch, session)

    asyncio.run(db.get_pending_adaptations("b-1"))

    sql = session.executed[0][0]
    assert "'proposed'" in sql
    assert "auto_applied" not in sql
    assert "'applied'" not in sql
    assert "'rejected'" not in sql


# ── P0-06: inserts are never auto_applied ────────────────────────────


def test_store_adaptations_never_inserts_auto_applied(monkeypatch):
    session = FakeSession()
    _patch_session(monkeypatch, session)

    ids = asyncio.run(
        db.store_adaptations(
            [
                {
                    "brand_id": "b-1",
                    "tier": 1,
                    "source_content_id": "c-1",
                    "description": "shift posting time",
                    "confidence": 0.9,
                    "data": {"k": "v"},
                    "status": "auto_applied",  # hostile caller — must be coerced
                },
                {
                    "brand_id": "b-1",
                    "tier": 2,
                    "source_content_id": "c-1",
                    "description": "tone shift",
                },
            ]
        )
    )

    assert len(ids) == 2
    statuses = [p["status"] for _, p in session.executed]
    assert statuses == ["proposed", "proposed"]
    # data is embedded once, not double-encoded
    notes = json.loads(session.executed[0][1]["notes"])
    assert notes["tier"] == 1
    assert notes["data"] == {"k": "v"}


def test_update_adaptation_status_refuses_auto_applied(monkeypatch):
    session = FakeSession()
    _patch_session(monkeypatch, session)

    with pytest.raises(ValueError):
        asyncio.run(db.update_adaptation_status("a1", "auto_applied"))
    assert session.executed == []

    # human decisions pass through
    asyncio.run(db.update_adaptation_status("a1", "applied"))
    asyncio.run(db.update_adaptation_status("a1", "rejected"))
    assert [p["status"] for _, p in session.executed] == ["applied", "rejected"]


def test_evaluation_store_node_marks_all_tiers_proposed(monkeypatch):
    captured = {}

    async def fake_store(records):
        captured["records"] = records
        return [f"id-{i}" for i in range(len(records))]

    async def fake_resolve(item_ids):
        return "content-1"

    monkeypatch.setattr(evaluation_nodes, "store_adaptations", fake_store)
    monkeypatch.setattr(
        evaluation_nodes, "resolve_current_content_id", fake_resolve
    )

    state = {
        "brand_id": "b-1",
        "adaptations": [
            {"tier": 1, "title": "low risk", "confidence": 0.9},
            {"tier": "2", "title": "medium"},
            {"tier": 3, "title": "major"},
        ],
        "performance_data": [
            {"calendar_item_id": "ci-1", "content_id": "c-9", "engagement_rate": 1.5}
        ],
    }
    result = asyncio.run(evaluation_nodes.store_adaptations_node(state))

    assert result["status"] == "completed"
    recs = captured["records"]
    assert [r["status"] for r in recs] == ["proposed", "proposed", "proposed"]
    assert recs[1]["tier"] == 2  # string tier coerced to int
    assert isinstance(recs[0]["data"], dict)  # no pre-serialisation


def test_evaluation_nodes_have_no_auto_apply_path():
    import inspect

    src = inspect.getsource(evaluation_nodes)
    assert '"auto_applied"' not in src


# ── P0-06: adaptation nodes wait for a human ─────────────────────────


def test_apply_tier1_never_touches_the_database(monkeypatch):
    calls = []

    async def fake_update(aid, status):
        calls.append((aid, status))

    monkeypatch.setattr(adaptation_nodes, "update_adaptation_status", fake_update)

    state = {
        "brand_id": "b-1",
        "adaptations": [{"id": "a1", "tier": 1, "description": "low"}],
    }
    result = asyncio.run(adaptation_nodes.apply_tier1(state))

    assert calls == []
    assert result["applied_changes"] == []


def test_propose_tier2_reviews_tiers_1_and_2_on_a_blanket_approval(
    monkeypatch,
):
    # The pinned agent.resume.run contract carries ONE decision for the whole
    # pause: approving applies every recommendation the pause presented (the
    # explicit human decision P0-06 demands); tier 3 is not part of this gate.
    calls = []

    async def fake_update(aid, status):
        calls.append((aid, status))

    payloads = []

    def fake_interrupt(payload):
        payloads.append(payload)
        return {"decision": "approved", "feedback": None}

    monkeypatch.setattr(adaptation_nodes, "update_adaptation_status", fake_update)
    monkeypatch.setattr(adaptation_nodes, "interrupt", fake_interrupt)

    state = {
        "brand_id": "b-1",
        "adaptations": [
            {"id": "a1", "tier": 1, "description": "low"},
            {"id": "a2", "tier": 2, "description": "medium"},
            {"id": "a3", "tier": 2, "description": "also medium"},
            {"id": "a4", "tier": 3, "description": "major"},
        ],
    }
    result = asyncio.run(adaptation_nodes.propose_tier2(state))

    # tier 1 goes through the same human gate as tier 2; tier 3 does not
    reviewed = {a["id"] for a in payloads[0]["adaptations"]}
    assert reviewed == {"a1", "a2", "a3"}
    assert calls == [("a1", "applied"), ("a2", "applied"), ("a3", "applied")]
    assert [c["id"] for c in result["applied_changes"]] == ["a1", "a2", "a3"]


def test_propose_tier2_rejection_writes_nothing_and_asks_for_revision(
    monkeypatch,
):
    calls = []

    async def fake_update(aid, status):
        calls.append((aid, status))

    def fake_interrupt(payload):
        return {"decision": "rejected", "feedback": "bad timing"}

    monkeypatch.setattr(adaptation_nodes, "update_adaptation_status", fake_update)
    monkeypatch.setattr(adaptation_nodes, "interrupt", fake_interrupt)

    state = {
        "brand_id": "b-1",
        "adaptations": [{"id": "a1", "tier": 2, "description": "medium"}],
    }
    result = asyncio.run(adaptation_nodes.propose_tier2(state))

    # A rejection decides nothing in the DB — rows stay 'proposed' and the
    # graph loops through the revision node instead.
    assert calls == []
    assert result["status"] == "needs_revision"
    assert result["revision_feedback"] == "bad timing"


def test_propose_tier3_ambiguous_resume_is_not_an_approval(monkeypatch):
    # Fail closed: anything but decision == "approved" (a legacy per-id
    # payload included) writes nothing and routes to revision.
    calls = []

    async def fake_update(aid, status):
        calls.append((aid, status))

    def fake_interrupt(payload):
        return {"decisions": {"a4": True}}  # legacy shape, no blanket decision

    monkeypatch.setattr(adaptation_nodes, "update_adaptation_status", fake_update)
    monkeypatch.setattr(adaptation_nodes, "interrupt", fake_interrupt)

    state = {
        "brand_id": "b-1",
        "adaptations": [
            {"id": "a4", "tier": 3, "description": "major"},
            {"id": "a5", "tier": 3, "description": "another"},
        ],
    }
    result = asyncio.run(adaptation_nodes.propose_tier3(state))

    assert calls == []
    assert result["status"] == "needs_revision"


# ── N-18: store_content survives null bytes ──────────────────────────


def test_store_content_survives_null_bytes(monkeypatch):
    session = FakeSession()
    _patch_session(monkeypatch, session)

    content_id = asyncio.run(
        db.store_content(
            {
                "brand_id": "b-1",
                "calendar_item_id": "ci-1",
                "headline": "Head\x00line",
                "caption": "Cap\x00tion",
                "cta": "Buy\x00now",
                "hashtags": ["#a\x00b", "#c"],
                "metadata": {"note": "meta\x00data"},
            }
        )
    )

    assert content_id
    insert_sql, params = session.executed[-1]
    assert "INSERT INTO content" in insert_sql
    for value in params.values():
        if isinstance(value, str):
            assert "\x00" not in value
            assert "\\u0000" not in value
        elif isinstance(value, list):
            for element in value:
                assert "\x00" not in element
    assert params["caption"] == "Caption"
    assert params["headline"] == "Headline"
    assert params["cta_text"] == "Buynow"
    assert params["hashtags"] == ["#ab", "#c"]


# ── N-06 (SQL side): upsert_product persists image_url + metadata ────


def test_upsert_product_persists_image_url_and_metadata(monkeypatch):
    session = FakeSession([FakeResult([("prod-1",)])])
    _patch_session(monkeypatch, session)

    pid = asyncio.run(
        db.upsert_product(
            {
                "brand_id": "b-1",
                "bc_item_no": "IT-1",
                "name": "Olive Oil 500ml",
                "description": "extra virgin",
                "category": "food",
                "vendor_no": "V1",
                "unit_price": 10,
                "bc_company": "co",
                "bc_location": "loc",
                "remaining_qty": 5,
                "image_url": "https://cdn.example/olive.png",
                # match_products_to_brands pre-serialises metadata
                "metadata": json.dumps(
                    {"brand_name": "NatureSpan", "is_promotable": True}
                ),
            }
        )
    )

    assert pid == "prod-1"
    sql, params = session.executed[0]
    assert params["primary_image_url"] == "https://cdn.example/olive.png"
    assert json.loads(params["metadata"]) == {
        "brand_name": "NatureSpan",
        "is_promotable": True,
    }
    # new image wins only when non-null; existing metadata keys survive
    assert "COALESCE(EXCLUDED.primary_image_url, products.primary_image_url)" in sql
    assert "|| EXCLUDED.metadata" in sql


def test_upsert_product_absent_image_keeps_existing_and_missing_keys_ok(
    monkeypatch,
):
    session = FakeSession([FakeResult([("prod-2",)])])
    _patch_session(monkeypatch, session)

    pid = asyncio.run(
        db.upsert_product({"brand_id": "b-1", "bc_item_no": "IT-2", "name": "X"})
    )

    assert pid == "prod-2"
    _, params = session.executed[0]
    assert params["primary_image_url"] is None  # SQL COALESCE keeps the old one
    assert json.loads(params["metadata"]) == {}
