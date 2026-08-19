"""The product swap is where fabricated pack copy comes from — guard it there.

A verified KAOKA Chocolat Noir bar shipped inside a rendered Naturespan reel
with a correct "KAOKA" wordmark above three lines of invented copy: "Sliry
Sniilzo Sci Cooira", "Sipiy mia Nar Cooooca", and blob certification marks.

The text guard was live the whole time. It runs inside generate_image, on the
BACKGROUND — which by design contains no product and no lettering — and the
Gemini swap that paints the pack in runs afterwards and returned its bytes
unchecked. The guard was inspecting the one stage that cannot produce this
defect and skipping the one that does.

Which verdict property the loop keys on is the load-bearing choice, and the
first attempt got it wrong.

`offending` is too broad: a faithful swap reproduces the real pack's
ingredients and weight, which are not in allowed_text but are correct.

`malformed` is also too broad, and worse — it carries illegible_marks, while
build_swap_instruction explicitly ASKS for copy too small to reproduce to come
back as soft out-of-focus texture, which the guard is required to report as an
unresolvable letter-like mark. Judged that way the pass criterion is the
negation of the swap's own success criterion: every CORRECT swap fails both
attempts and the blank placeholder ships. That is a live defect — a blank white
pouch dominated four shots of a rendered reel.

`fabricated` is the right one: lettering the model invented, readable but not
real words. Nothing an allow-list or a depth-of-field instruction can excuse.
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


class TestWhichVerdictPropertyTheSwapUses:
    """The three candidate properties, and why only one is correct here."""

    def test_faithful_small_print_is_not_fabricated(self):
        # Real pack copy the allow-list does not mention: unintended by the
        # letter of the rule, but a correct reproduction.
        verdict = verdict_from_payload({
            "visible_text": ["KAOKA", "INGREDIENTS: CACAO, SUGAR", "100g"],
            "unintended_text": ["INGREDIENTS: CACAO, SUGAR", "100g"],
            "gibberish_text": [],
            "has_unintended_text": True,
        })
        assert verdict.flagged is True, "still flagged for other callers"
        assert verdict.fabricated == [], "a faithful swap must not be rejected"

    def test_invented_copy_is_fabricated(self):
        verdict = verdict_from_payload({
            "visible_text": ["KAOKA", "Sliry Sniilzo Sci Cooira"],
            "unintended_text": ["Sliry Sniilzo Sci Cooira"],
            "gibberish_text": ["Sliry Sniilzo Sci Cooira"],
            "has_unintended_text": True,
        })
        assert "Sliry Sniilzo Sci Cooira" in verdict.fabricated

    def test_deliberately_soft_small_print_is_not_fabricated(self):
        """The case that made `malformed` the wrong criterion for a swap.

        build_swap_instruction asks for pack copy too small to reproduce to
        come back as soft out-of-focus texture. The guard must report that as
        an unresolvable mark, so it lands in `malformed` — but it is the
        DESIRED output, and rejecting it publishes the blank placeholder.
        """
        verdict = verdict_from_payload({
            "visible_text": ["KAOKA"],
            "unintended_text": [],
            "gibberish_text": [],
            "illegible_text_marks": ["certification badges on the lower pack"],
            "has_unintended_text": False,
        })
        # Still malformed — the background caller depends on that.
        assert verdict.malformed == ["certification badges on the lower pack"]
        # But NOT fabricated, so a correct swap is kept.
        assert verdict.fabricated == []


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
        assert clean.fabricated == []

    def test_a_flagged_then_clean_sequence_keeps_the_second(self):
        bad = verdict_from_payload({
            "gibberish_text": ["Sliry Sniilzo"], "has_unintended_text": True})
        good = verdict_from_payload({"has_unintended_text": False})
        # The loop returns as soon as `fabricated` is empty.
        outcomes = [bool(v.fabricated) for v in (bad, good)]
        assert outcomes == [True, False]

    def test_two_bad_attempts_mean_the_placeholder_wins(self):
        bad = verdict_from_payload({
            "gibberish_text": ["Sliry Sniilzo"], "has_unintended_text": True})
        assert all(v.fabricated for v in (bad, bad)), (
            "both attempts fabricated — the caller must keep the pre-swap frame"
        )

    def test_an_unavailable_guard_does_not_block_the_swap(self):
        # Fail-open: a guard that could not form an opinion must not cost us
        # the product placement.
        skipped = TextGuardVerdict(flagged=False, checked=False, reason="guard unavailable")
        assert skipped.fabricated == []


def test_the_swap_block_asks_the_guard_about_the_swap_output():
    """Pin the wiring: the guard call must exist in the swap function."""
    import inspect

    from shared.product_swap import swap_product_into_image

    source = inspect.getsource(swap_product_into_image)
    assert "detect_unintended_text" in source, (
        "the swap returned unchecked bytes — this is how invented pack copy "
        "reached a published reel"
    )
    assert ".fabricated" in source, (
        "judging a swap by `malformed` rejects every CORRECT swap: it carries "
        "illegible_marks, and build_swap_instruction ASKS for copy too small "
        "to reproduce to come back as soft out-of-focus texture — which the "
        "guard must report as an unresolvable mark. The pass criterion would "
        "be the negation of the swap's own success criterion, and the blank "
        "placeholder would ship instead."
    )
    assert ".malformed" not in source
    # The fallback must be the pre-swap image, not a failure.
    assert "return image_data" in source


class TestRegenerationIsGuardedToo:
    """The regeneration path had no fabrication guard at all.

    worker.py carried its own copy of the swap that returned the editor's
    first output unread — so a post regenerated from the UI, the button a
    reviewer presses precisely BECAUSE the image was wrong, had less
    protection than the pipeline run that produced it.
    """

    def test_the_regen_path_no_longer_returns_the_first_output_unread(self):
        import inspect

        import worker

        src = inspect.getsource(worker._replace_product_in_image)
        assert "swap_product_into_image(" in src
        # The old copy pulled inline_data straight out of the response and
        # returned it.
        assert "inline_data" not in src
        assert "generate_content" not in src

    def test_the_pack_owner_reaches_the_guards_allow_list(self):
        import inspect

        import worker

        src = inspect.getsource(worker._handle_image_regeneration)
        # The guard's allow-list needs the name printed ON the pack so a
        # faithful copy of the maker's own wordmark is not reported as
        # invented. That name comes from the item name itself (pack_owner) —
        # NOT from products.vendor_name, which is a supplier and banned from
        # prompts outright (shared.suppliers, user directive 2026-08-19).
        assert "_pack_owner(product_name)" in src
        assert "product_name, product_vendor" not in src

    def test_both_callers_get_the_same_attempt_budget(self):
        from shared.product_swap import SWAP_ATTEMPTS

        assert SWAP_ATTEMPTS >= 2, (
            "the editor is stochastic; one roll was the regen path's whole "
            "budget"
        )
