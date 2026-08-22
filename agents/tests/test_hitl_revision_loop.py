"""The rejected→revise→re-review loop, driven through the REAL graphs.

The resume contract (agent.resume.run) hands interrupt() a payload of
{"decision": "approved"|"rejected", "feedback": str|None}. Approved finalizes
as before; rejected routes through a revision node and back to review, at
most MAX_REVISIONS times — the next rejection FAILS the run instead of
burning another loop. These tests execute the actual compiled strategy and
adaptation graphs (LLM/DB calls monkeypatched at the nodes-module level, the
interrupt/Command machinery real) so the routing, the counters and the
checkpointer wiring are all exercised together.
"""

import asyncio
import itertools
import json

import pytest
from langgraph.types import Command

from workflows.adaptation import nodes as adaptation_nodes
from workflows.adaptation.graph import adaptation_graph
from workflows.strategy import nodes as strategy_nodes
from workflows.strategy.graph import strategy_graph

_thread_ids = itertools.count(1)


def _cfg():
    return {"configurable": {"thread_id": f"hitl-loop-{next(_thread_ids)}"}}


def _interrupt_value(result):
    interrupts = result.get("__interrupt__") or []
    assert interrupts, f"expected an interrupt, got {result}"
    return interrupts[0].value


# ── Strategy ─────────────────────────────────────────────────────────────


@pytest.fixture()
def strategy_wired(monkeypatch):
    """Real strategy graph; LLM + DB stubbed at the nodes-module level."""
    stored: list[dict] = []
    chats: list[list[dict]] = []

    async def fake_brand_config(brand_id):
        return {"name": "Naturespan", "brand_guidelines": {}}

    async def fake_research(brand_id):
        return {"output_payload": {"personas": []}}

    async def fake_chat(prompt, **kwargs):
        chats.append(prompt)
        # Generic JSON that every node's parser accepts; the revision pass
        # returns a recognizable pillar so the merge is observable.
        return json.dumps(
            {
                "value_proposition": "v",
                "content_pillars": [{"name": f"Pillar r{len(chats)}"}],
            }
        )

    async def fake_summary(kind, data):
        return "plain summary"

    async def fake_store(brand_id, data, agent_type="strategy"):
        stored.append(data)
        return "stored-run-id"

    async def fake_get_brand(brand_id):
        return {"brand_guidelines": {}}

    async def fake_events(brand_id, months_ahead=12):
        return []

    monkeypatch.setattr(strategy_nodes, "get_brand_config", fake_brand_config)
    monkeypatch.setattr(strategy_nodes, "get_latest_research", fake_research)
    monkeypatch.setattr(strategy_nodes, "chat_completion", fake_chat)
    monkeypatch.setattr(
        strategy_nodes, "generate_executive_summary_plain", fake_summary
    )
    monkeypatch.setattr(strategy_nodes, "store_strategy", fake_store)
    monkeypatch.setattr(
        strategy_nodes, "get_events_for_research", fake_events
    )
    import shared.tools.database as db

    monkeypatch.setattr(db, "get_brand", fake_get_brand)
    return {"stored": stored, "chats": chats}


def _run_strategy(config, state=None, resume=None):
    payload = (
        Command(resume=resume)
        if resume is not None
        else {"brand_id": "b-1", "trigger": "manual", "status": "running"}
    )
    if state is not None:
        payload = state
    return asyncio.run(strategy_graph.ainvoke(payload, config=config))


class TestStrategyRevisionLoop:
    def test_approve_stores_and_ends(self, strategy_wired):
        cfg = _cfg()
        paused = _run_strategy(cfg)
        assert _interrupt_value(paused)["type"] == "strategy_review"
        assert _interrupt_value(paused)["revision_count"] == 0

        done = _run_strategy(
            cfg, resume={"decision": "approved", "feedback": None}
        )
        assert "__interrupt__" not in done
        assert done["status"] == "approved"
        assert done["human_approved"] is True
        assert len(strategy_wired["stored"]) == 1

    def test_reject_revises_and_re_reviews_then_caps(self, strategy_wired):
        cfg = _cfg()
        paused = _run_strategy(cfg)
        base_chats = len(strategy_wired["chats"])

        # Rejection 1 → revision pass 1 → re-review (a NEW pause).
        paused = _run_strategy(
            cfg, resume={"decision": "rejected", "feedback": "too generic"}
        )
        value = _interrupt_value(paused)
        assert value["revision_count"] == 1
        # The revision made exactly one LLM call, with the feedback in it.
        assert len(strategy_wired["chats"]) == base_chats + 1
        assert "too generic" in strategy_wired["chats"][-1][1]["content"]

        # Rejection 2 → revision pass 2 → re-review.
        paused = _run_strategy(
            cfg, resume={"decision": "rejected", "feedback": "still generic"}
        )
        assert _interrupt_value(paused)["revision_count"] == 2

        # Rejection 3 → the cap: the run FAILS, no third revision runs.
        done = _run_strategy(
            cfg, resume={"decision": "rejected", "feedback": "no"}
        )
        assert "__interrupt__" not in done
        assert done["status"] == "failed"
        assert "strategy rejected after 2 revisions" in done["errors"]
        assert len(strategy_wired["chats"]) == base_chats + 2
        assert strategy_wired["stored"] == []

    def test_revision_merges_returned_components_only(self, strategy_wired):
        cfg = _cfg()
        _run_strategy(cfg)
        paused = _run_strategy(
            cfg, resume={"decision": "rejected", "feedback": "fix pillars"}
        )
        strategy = _interrupt_value(paused)["strategy"]
        # The revision returned content_pillars (and no themes): pillars are
        # replaced, everything it stayed silent on is preserved.
        assert strategy["content_pillars"][0]["name"].startswith("Pillar r")
        assert strategy["positioning"] == {
            "value_proposition": "v",
            "content_pillars": [{"name": "Pillar r1"}],
        }

    def test_ambiguous_resume_is_a_rejection(self, strategy_wired):
        # Fail closed: anything that is not an explicit approval loops to
        # revision, never to store_strategy.
        cfg = _cfg()
        _run_strategy(cfg)
        paused = _run_strategy(cfg, resume={"approved": True})  # legacy shape
        assert _interrupt_value(paused)["revision_count"] == 1
        assert strategy_wired["stored"] == []

    def test_event_trigger_auto_approves_without_pausing(
        self, strategy_wired
    ):
        cfg = _cfg()
        done = _run_strategy(
            cfg,
            state={"brand_id": "b-1", "trigger": "event", "status": "running"},
        )
        assert "__interrupt__" not in done
        assert done["status"] == "approved"
        assert len(strategy_wired["stored"]) == 1


# ── Adaptation ───────────────────────────────────────────────────────────


@pytest.fixture()
def adaptation_wired(monkeypatch):
    decisions: list[tuple[str, str]] = []

    async def fake_pending(brand_id):
        return [
            {"id": "a-1", "tier": 2, "description": "post later", "confidence": 0.8, "data": {}},
            {"id": "a-2", "tier": 3, "description": "drop a pillar", "confidence": 0.6, "data": {}},
        ]

    async def fake_update_status(aid, status):
        decisions.append((aid, status))

    monkeypatch.setattr(
        adaptation_nodes, "get_pending_adaptations", fake_pending
    )
    monkeypatch.setattr(
        adaptation_nodes, "update_adaptation_status", fake_update_status
    )
    return {"decisions": decisions}


def _run_adaptation(config, resume=None):
    payload = (
        Command(resume=resume)
        if resume is not None
        else {"brand_id": "b-1", "status": "running"}
    )
    return asyncio.run(adaptation_graph.ainvoke(payload, config=config))


class TestAdaptationReviewLoop:
    def test_approve_applies_all_presented_then_pauses_for_tier3(
        self, adaptation_wired
    ):
        cfg = _cfg()
        paused = _run_adaptation(cfg)
        assert _interrupt_value(paused)["type"] == "tier2_review"

        paused = _run_adaptation(
            cfg, resume={"decision": "approved", "feedback": None}
        )
        # tier 1-2 applied, and the graph moved on to the tier-3 pause.
        assert ("a-1", "applied") in adaptation_wired["decisions"]
        assert _interrupt_value(paused)["type"] == "tier3_review"

        done = _run_adaptation(
            cfg, resume={"decision": "approved", "feedback": None}
        )
        assert "__interrupt__" not in done
        assert done["status"] == "completed"
        assert ("a-2", "applied") in adaptation_wired["decisions"]

    def test_reject_re_presents_with_feedback_then_caps(
        self, adaptation_wired
    ):
        cfg = _cfg()
        _run_adaptation(cfg)

        paused = _run_adaptation(
            cfg, resume={"decision": "rejected", "feedback": "wrong timing"}
        )
        value = _interrupt_value(paused)
        assert value["type"] == "tier2_review"
        assert value["revision_count"] == 1
        assert value["operator_feedback"] == "wrong timing"

        paused = _run_adaptation(
            cfg, resume={"decision": "rejected", "feedback": "still wrong"}
        )
        assert _interrupt_value(paused)["revision_count"] == 2

        done = _run_adaptation(
            cfg, resume={"decision": "rejected", "feedback": "no"}
        )
        assert "__interrupt__" not in done
        assert done["status"] == "failed"
        assert (
            "tier 1-2 recommendations rejected after 2 revisions"
            in done["errors"]
        )
        # A failed run wrote NO decisions — the rows stay 'proposed'.
        assert adaptation_wired["decisions"] == []

    def test_tier3_has_its_own_revision_counter(self, adaptation_wired):
        cfg = _cfg()
        _run_adaptation(cfg)
        # Burn both tier-2 revisions, then approve tier 2.
        _run_adaptation(cfg, resume={"decision": "rejected", "feedback": "a"})
        _run_adaptation(cfg, resume={"decision": "rejected", "feedback": "b"})
        paused = _run_adaptation(
            cfg, resume={"decision": "approved", "feedback": None}
        )
        value = _interrupt_value(paused)
        # Tier 3 starts fresh: its counter is independent of tier 2's, and
        # tier 2's stale rejection feedback does not leak into its payload.
        assert value["type"] == "tier3_review"
        assert value["revision_count"] == 0
        assert value["operator_feedback"] is None

        paused = _run_adaptation(
            cfg, resume={"decision": "rejected", "feedback": "tier3 concern"}
        )
        assert _interrupt_value(paused)["revision_count"] == 1
        assert _interrupt_value(paused)["operator_feedback"] == "tier3 concern"
