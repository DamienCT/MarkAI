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
            shot["duration_s"] = 6.0  # 18s total — way over the 10s cap
        _patch_llm(monkeypatch, json.dumps(plan))
        result = asyncio.run(plan_shots(_state()))

        assert result.get("status") != "failed"
        shots = result["shot_plan"]["shots"]
        assert sum(s["duration_s"] for s in shots) <= 10
        assert shots[0]["duration_s"] >= 2.0

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
