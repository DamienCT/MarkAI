"""Tests for the video workflow's shot planning (plan_shots JSON parsing)."""

import asyncio
import json
import sys
import os

import pytest

# Add the agents directory to the path so workflows/shared can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import workflows.video.nodes as video_nodes
from workflows.video.nodes import (
    MAX_PLAN_TOTAL_S,
    MAX_SHOTS,
    MIN_PLAN_SHOTS,
    _build_video_prompt,
    _extract_first_frame,
    _normalize_shot_plan,
    plan_shots,
)


def _scene(first_frame: str = "A hand lifts the open jar toward the camera") -> str:
    return (
        "SCENE CONTEXT: sunlit kitchen counter, breakfast spread\n"
        f"FIRST FRAME: {first_frame}\n"
        "CAMERA/OPTICS: 35mm, shallow depth of field, slow push-in\n"
        "LIGHTING: warm morning window light\n"
        "AUDIO: soft clink of glass on marble\n"
        "STYLE: premium food commercial\n"
        "LOCKS: jar identity, marble counter, warm palette"
    )


def _canned_plan() -> dict:
    return {
        "hook_line": "Breakfast, upgraded",
        "shots": [
            {"index": 1, "duration_s": 2.5, "scene": _scene()},
            {"index": 2, "duration_s": 2.0, "scene": _scene("A knife spreads a thick layer")},
            {"index": 3, "duration_s": 2.0, "scene": _scene("The jar back in place, lid catching the light")},
        ],
        "caption": "The shortcut to a slow morning. One jar, zero effort.",
        "hashtags": ["#Breakfast", "brunch time!", ""],
        "cta": "Try it today",
    }


def _state() -> dict:
    # No run_id on purpose: update_agent_run_step no-ops without one,
    # keeping the test fully offline.
    return {
        "brand_id": "brand-1",
        "calendar_item_id": "item-1",
        "brand": {"name": "FancyFinds"},
        "calendar_item": {
            "channel": "instagram",
            "theme": "Slow mornings",
            "content_brief": "Reel for the hazelnut spread jar at breakfast",
        },
        "positioning": {"brand_voice": "warm, sensory"},
        "relevant_audience": {"name": "Home foodies"},
        "product": {"name": "Hazelnut Spread", "description": "Slow-roasted hazelnut spread"},
        "sub_brand": "FancyFinds",
    }


def _patch_llm(monkeypatch, response: str) -> dict:
    """Monkeypatch chat_completion with a canned response; returns call capture."""
    captured: dict = {}

    async def fake_chat_completion(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return response

    monkeypatch.setattr(video_nodes, "chat_completion", fake_chat_completion)
    return captured


class TestPlanShots:
    def test_parses_canned_response(self, monkeypatch):
        captured = _patch_llm(monkeypatch, json.dumps(_canned_plan()))
        result = asyncio.run(plan_shots(_state()))

        assert result.get("status") != "failed"
        plan = result["shot_plan"]
        assert len(plan["shots"]) == 3
        assert plan["shots"][0]["duration_s"] == 2.5
        assert sum(s["duration_s"] for s in plan["shots"]) <= 10
        # Content fields mapped into state for the store tail
        assert result["hook"] == "Breakfast, upgraded"
        assert result["caption"].startswith("The shortcut")
        assert result["cta"] == "Try it today"
        # Hashtags cleaned: '#' stripped, spaces/punctuation removed, empties dropped
        assert result["hashtags"] == ["Breakfast", "brunchtime"]
        # The LLM was asked for strict JSON
        assert captured["kwargs"].get("response_format") == {"type": "json_object"}

    def test_parses_fenced_response(self, monkeypatch):
        _patch_llm(monkeypatch, f"```json\n{json.dumps(_canned_plan())}\n```")
        result = asyncio.run(plan_shots(_state()))
        assert result.get("status") != "failed"
        assert len(result["shot_plan"]["shots"]) == 3

    def test_over_budget_durations_are_scaled(self, monkeypatch):
        plan = _canned_plan()
        for shot in plan["shots"]:
            shot["duration_s"] = 30.0  # 90s total — way over the plan cap
        _patch_llm(monkeypatch, json.dumps(plan))
        result = asyncio.run(plan_shots(_state()))

        assert result.get("status") != "failed"
        shots = result["shot_plan"]["shots"]
        assert sum(s["duration_s"] for s in shots) <= MAX_PLAN_TOTAL_S
        assert shots[0]["duration_s"] >= 2.0

    def test_over_budget_plan_keeps_every_beat(self):
        # Scaling down must never truncate the shot list: the render fitter
        # needs 6-8 beats to land on the ~30s target.
        plan = {
            "hook_line": "h",
            "shots": [
                {"index": i + 1, "duration_s": 12.0, "scene": _scene()}
                for i in range(8)
            ],
            "caption": "c",
            "hashtags": [],
            "cta": "go",
        }
        normalized = _normalize_shot_plan(plan)
        assert len(normalized["shots"]) == 8
        assert sum(s["duration_s"] for s in normalized["shots"]) <= MAX_PLAN_TOTAL_S
        assert all(s["duration_s"] >= 0.5 for s in normalized["shots"])
        assert normalized["shots"][0]["duration_s"] >= 2.0

    def test_more_than_max_shots_are_truncated(self):
        plan = {
            "hook_line": "h",
            "shots": [
                {"index": i + 1, "duration_s": 4.0, "scene": _scene()}
                for i in range(12)
            ],
            "caption": "c",
            "hashtags": [],
            "cta": "go",
        }
        normalized = _normalize_shot_plan(plan)
        assert len(normalized["shots"]) == MAX_SHOTS

    def test_prompt_asks_for_the_full_story_arc(self, monkeypatch):
        captured = _patch_llm(monkeypatch, json.dumps(_canned_plan()))
        asyncio.run(plan_shots(_state()))
        system = captured["messages"][0]["content"]
        assert f"{MIN_PLAN_SHOTS} to {MAX_SHOTS}" in system
        for beat in ("HOOK", "TENSION", "REVEAL", "PROOF", "USE MOMENT",
                     "PAYOFF", "CTA"):
            assert beat in system
        assert "30 second" in system

    def test_prompt_has_room_for_a_max_shots_plan(self, monkeypatch):
        # MAX_SHOTS beats x a 7-label structured scene + overlay/caption/tags
        # does not fit in 4096 tokens; truncation used to fail the item.
        captured = _patch_llm(monkeypatch, json.dumps(_canned_plan()))
        asyncio.run(plan_shots(_state()))
        assert captured["kwargs"]["max_tokens"] == video_nodes._SHOT_PLAN_MAX_TOKENS
        assert video_nodes._SHOT_PLAN_MAX_TOKENS >= 8192

    def test_truncated_plan_is_repaired_instead_of_failing_the_item(self, monkeypatch):
        """One JSON-repair retry, like the campaign path — not an instant _fail."""
        calls: list[list[dict]] = []
        truncated = json.dumps(_canned_plan())[:-40]

        async def fake_chat_completion(messages, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                return truncated
            return json.dumps(_canned_plan())

        monkeypatch.setattr(video_nodes, "chat_completion", fake_chat_completion)
        result = asyncio.run(plan_shots(_state()))

        assert result.get("status") != "failed"
        assert len(result["shot_plan"]["shots"]) == 3
        assert len(calls) == 2
        assert "You repair malformed JSON" in calls[1][0]["content"]

    def test_prompt_carries_the_temporal_context(self, monkeypatch):
        """The video graph never runs generate_hook/generate_caption, so this
        is the only place a reel's own copy meets the temporal guard — and
        'opening soon' burned into a 30s master is the worst instance."""
        state = _state()
        state["calendar_item"] = {
            **state["calendar_item"],
            "scheduled_date": "2026-09-15",
        }
        state["events"] = [
            {"title": "Grand Baie Store Opening", "start": "2026-09-01", "end": None},
            {"title": "Diwali", "start": "2026-11-08", "end": None},
        ]
        captured = _patch_llm(monkeypatch, json.dumps(_canned_plan()))
        asyncio.run(plan_shots(state))

        system = captured["messages"][0]["content"]
        user = captured["messages"][1]["content"]
        assert "TEMPORAL RULES" in system
        assert "TEMPORAL CONTEXT" in user
        assert "Grand Baie Store Opening" in user  # already happened by then
        assert "Diwali" in user  # still ahead

    def test_bad_json_fails_workflow(self, monkeypatch):
        _patch_llm(monkeypatch, "sorry, I cannot produce a plan")

        async def fake_execute_update(query, params=None):
            return 0

        # _fail writes calendar_items + video_jobs via execute_update — keep
        # the test offline.
        monkeypatch.setattr(video_nodes, "execute_update", fake_execute_update)
        result = asyncio.run(plan_shots(_state()))

        assert result["status"] == "failed"
        assert any("plan_shots failed" in e for e in result["errors"])
        # Raw media bytes are always cleared on failure
        assert result["video_bytes"] is None
        assert result["keyframe_bytes"] is None


class TestNormalizeShotPlan:
    def test_first_shot_floor_is_two_seconds(self):
        plan = _canned_plan()
        plan["shots"][0]["duration_s"] = 0.8
        normalized = _normalize_shot_plan(plan)
        assert normalized["shots"][0]["duration_s"] == 2.0

    def test_missing_shots_raises(self):
        with pytest.raises(ValueError):
            _normalize_shot_plan({"hook_line": "x", "shots": []})

    def test_non_dict_raises(self):
        with pytest.raises(ValueError):
            _normalize_shot_plan(["not", "a", "plan"])

    def test_shots_without_scene_text_raise(self):
        with pytest.raises(ValueError):
            _normalize_shot_plan({"shots": [{"index": 1, "duration_s": 3, "scene": ""}]})

    def test_shot_cap(self):
        plan = _canned_plan()
        plan["shots"] = [
            {"index": i, "duration_s": 1.0, "scene": _scene()} for i in range(10)
        ]
        normalized = _normalize_shot_plan(plan)
        assert len(normalized["shots"]) <= video_nodes.MAX_SHOTS


class TestPromptHelpers:
    def test_extract_first_frame(self):
        assert (
            _extract_first_frame(_scene("The jar hero shot"))
            == "The jar hero shot"
        )

    def test_extract_first_frame_missing_returns_empty(self):
        assert _extract_first_frame("just a plain scene description") == ""

    def test_build_video_prompt_joins_shots_with_cut_markers(self):
        plan = _normalize_shot_plan(_canned_plan())
        prompt = _build_video_prompt(plan)
        assert prompt.count("CUT TO:") == len(plan["shots"]) - 1
        assert "SHOT 1 (2.5s):" in prompt
        assert "9:16" in prompt
