"""A shot plan in the wrong language must not reach the renderer.

On 2026-08-18 five Naturespan reels rendered with French burned onto the
master — overlay lines and the CTA card. ENGLISH_ONLY_RULE was already at the
top of the shot-plan system prompt; the model mirrored a French brief anyway.

The retry exists because of where the cost sits: a wrong-language plan is
caught for the price of one text call, while the render it precedes costs tens
of GPU-minutes and produces an asset nobody can publish.
"""

import asyncio

import pytest

from workflows.video import nodes


def _plan(hook="Proof you can see", cta="Open today", overlays=("Certified", "In store")):
    return {
        "hook_line": hook,
        "caption": "A short caption.",
        "hashtags": ["#organic"],
        "cta": cta,
        "shots": [
            {"index": i + 1, "duration_s": 4.0, "overlay_text": t, "scene": "SCENE: x"}
            for i, t in enumerate(overlays)
        ],
    }


class TestFlagging:
    def test_english_plan_has_no_flags(self):
        assert nodes._plan_language_flags(_plan(), []) == {}

    def test_french_cta_is_flagged(self):
        # REAL — this exact CTA was burned onto a rendered reel.
        flags = nodes._plan_language_flags(
            _plan(cta="Rendez-vous le 1er septembre à Grand Baie"), ["Grand Baie"]
        )
        assert "cta" in flags

    def test_a_french_overlay_is_located_by_index(self):
        flags = nodes._plan_language_flags(
            _plan(overlays=("Certified", "Vos repères bio")), []
        )
        assert "shots[1].overlay_text" in flags
        assert "shots[0].overlay_text" not in flags

    def test_product_and_brand_names_are_allowed(self):
        flags = nodes._plan_language_flags(
            _plan(hook="Le Pain des Fleurs, in stock"), ["Le Pain des Fleurs"]
        )
        assert flags == {}


class TestRetry:
    def test_english_plan_skips_the_retry_entirely(self, monkeypatch):
        calls = []

        async def fake_chat(*a, **k):
            calls.append(1)
            return "{}"

        monkeypatch.setattr(nodes, "chat_completion", fake_chat)
        plan = _plan()
        out = asyncio.run(nodes._enforce_plan_language(plan, "sys", "usr", allow=[]))
        assert out is plan and not calls, "spent a text call on a clean plan"

    def test_french_plan_is_replaced_by_the_english_retry(self, monkeypatch):
        async def fake_chat(*a, **k):
            return (
                '{"hook_line": "Proof you can see", "caption": "A caption.",'
                ' "hashtags": ["#organic"], "cta": "Open today",'
                ' "shots": [{"index": 1, "duration_s": 4.0,'
                ' "overlay_text": "Certified", "scene": "SCENE: x"}]}'
            )

        monkeypatch.setattr(nodes, "chat_completion", fake_chat)
        out = asyncio.run(
            nodes._enforce_plan_language(
                _plan(cta="Rendez-vous à Grand Baie"), "sys", "usr", allow=["Grand Baie"]
            )
        )
        assert out["cta"] == "Open today"
        assert nodes._plan_language_flags(out, []) == {}

    def test_a_failed_retry_keeps_the_original_and_still_renders(self, monkeypatch):
        async def boom(*a, **k):
            raise RuntimeError("provider down")

        monkeypatch.setattr(nodes, "chat_completion", boom)
        plan = _plan(cta="Rendez-vous à Grand Baie")
        out = asyncio.run(nodes._enforce_plan_language(plan, "s", "u", allow=[]))
        assert out is plan, "a hole in the calendar is worse than a flagged reel"

    def test_a_still_french_retry_is_warned_about_not_dropped(self, monkeypatch, caplog):
        async def still_french(*a, **k):
            return (
                '{"hook_line": "Du bio vérifiable", "caption": "Une caption.",'
                ' "hashtags": ["#bio"], "cta": "Rendez-vous demain",'
                ' "shots": [{"index": 1, "duration_s": 4.0,'
                ' "overlay_text": "Vos repères", "scene": "SCENE: x"}]}'
            )

        monkeypatch.setattr(nodes, "chat_completion", still_french)
        with caplog.at_level("WARNING"):
            out = asyncio.run(
                nodes._enforce_plan_language(
                    _plan(cta="Rendez-vous demain"), "s", "u", allow=[]
                )
            )
        assert out["shots"], "plan survived"
        assert any("STILL not English" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("field", ["hook_line", "caption", "cta"])
def test_every_viewer_facing_field_is_checked(field):
    plan = _plan()
    plan[field] = "Vos repères bio, certifiés et clairs"
    assert field in nodes._plan_language_flags(plan, [])
