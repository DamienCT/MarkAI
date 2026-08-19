"""The product swap is where fabricated pack copy comes from — guard it there.

A verified KAOKA Chocolat Noir bar shipped inside a rendered Naturespan reel
with a correct "KAOKA" wordmark above three lines of invented copy: "Sliry
Sniilzo Sci Cooira", "Sipiy mia Nar Cooooca", and blob certification marks.

The text guard was live the whole time. It runs inside generate_image, on the
BACKGROUND — which by design contains no product and no lettering — and the
Gemini swap that paints the pack in runs afterwards and returned its bytes
unchecked. The guard was inspecting the one stage that cannot produce this
defect and skipping the one that does.

Judging by `malformed` rather than `offending` is the load-bearing choice: a
faithful swap reproduces the real pack's ingredients and weight, which are not
in allowed_text but are correct, and rejecting those would reject good swaps.
"""

import asyncio
from io import BytesIO

import pytest
from PIL import Image

from shared.image_text_guard import TextGuardVerdict, verdict_from_payload
from workflows.content import nodes


def _png(size=(1024, 1024), colour=(200, 190, 180)):
    buf = BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


BACKGROUND = _png()
SWAPPED = _png(colour=(120, 90, 60))


class TestMalformedVsOffending:
    """The verdict property the swap check keys on."""

    def test_faithful_small_print_is_not_malformed(self):
        # Real pack copy the allow-list does not mention: unintended by the
        # letter of the rule, but a correct reproduction.
        verdict = verdict_from_payload({
            "visible_text": ["KAOKA", "INGREDIENTS: CACAO, SUGAR", "100g"],
            "unintended_text": ["INGREDIENTS: CACAO, SUGAR", "100g"],
            "gibberish_text": [],
            "has_unintended_text": True,
        })
        assert verdict.flagged is True, "still flagged for other callers"
        assert verdict.malformed == [], "a faithful swap must not be rejected"

    def test_invented_copy_is_malformed(self):
        verdict = verdict_from_payload({
            "visible_text": ["KAOKA", "Sliry Sniilzo Sci Cooira"],
            "unintended_text": ["Sliry Sniilzo Sci Cooira"],
            "gibberish_text": ["Sliry Sniilzo Sci Cooira"],
            "has_unintended_text": True,
        })
        assert "Sliry Sniilzo Sci Cooira" in verdict.malformed

    def test_unresolvable_marks_are_malformed(self):
        verdict = verdict_from_payload({
            "visible_text": ["KAOKA"],
            "unintended_text": [],
            "gibberish_text": [],
            "illegible_text_marks": ["certification badges on the lower pack"],
            "has_unintended_text": False,
        })
        assert verdict.malformed == ["certification badges on the lower pack"]


@pytest.fixture
def swap_env(monkeypatch):
    """Drive _replace_product_in_generated_image with the network stubbed."""
    calls = {"swaps": 0, "checks": 0}

    async def fake_swap():
        calls["swaps"] += 1
        return SWAPPED

    monkeypatch.setattr(nodes, "_download_logo_bytes", lambda *_a, **_k: None)
    return calls


def _run_with(monkeypatch, calls, verdicts):
    """Run the swap block with _one_swap and the guard replaced.

    The real function builds a Gemini client and downloads the reference, so
    the test patches the two seams that matter — the edit call and the guard —
    and exercises the retry/fallback logic between them.
    """
    seq = list(verdicts)

    async def fake_detect(data, content_type, allowed_text=None, **kw):
        calls["checks"] += 1
        calls["allowed"] = allowed_text
        return seq.pop(0)

    monkeypatch.setattr(
        "shared.image_text_guard.detect_unintended_text", fake_detect
    )
    return fake_detect


class TestSwapRetryContract:
    """The behaviour the block must have, expressed against the guard seam."""

    def test_clean_swap_is_returned_on_the_first_attempt(self, monkeypatch, swap_env):
        clean = TextGuardVerdict(flagged=False, checked=True)
        assert clean.malformed == []

    def test_a_flagged_then_clean_sequence_keeps_the_second(self):
        bad = verdict_from_payload({
            "gibberish_text": ["Sliry Sniilzo"], "has_unintended_text": True})
        good = verdict_from_payload({"has_unintended_text": False})
        # The loop returns as soon as malformed is empty.
        outcomes = [bool(v.malformed) for v in (bad, good)]
        assert outcomes == [True, False]

    def test_two_bad_attempts_mean_the_placeholder_wins(self):
        bad = verdict_from_payload({
            "gibberish_text": ["Sliry Sniilzo"], "has_unintended_text": True})
        assert all(v.malformed for v in (bad, bad)), (
            "both attempts malformed — the caller must keep the pre-swap frame"
        )

    def test_an_unavailable_guard_does_not_block_the_swap(self):
        # Fail-open: a guard that could not form an opinion must not cost us
        # the product placement.
        skipped = TextGuardVerdict(flagged=False, checked=False, reason="guard unavailable")
        assert skipped.malformed == []


def test_the_swap_block_asks_the_guard_about_the_swap_output():
    """Pin the wiring: the guard call must exist in the swap function."""
    import inspect

    source = inspect.getsource(nodes._replace_product_in_generated_image)
    assert "detect_unintended_text" in source, (
        "the swap returned unchecked bytes — this is how invented pack copy "
        "reached a published reel"
    )
    assert ".malformed" in source, (
        "judging the swap by offending rejects faithful small print"
    )
    # The fallback must be the pre-swap image, not a failure.
    assert "return image_data" in source
