"""Why the product swap invented labels: it was never given the pack.

Rendered Naturespan reels showed real products carrying invented copy — a
correct "KAOKA" wordmark above "Sliry Sniilzo Sci Cooira", "AIMLO / Miheell"
where the pack says Emile Noel, "AIIE NOEL / Far Riz" for Autour du Riz. The
wordmark survives and the body copy does not, which is the signature of an
editor working from a reference too small to contain the small print.

Two independent bugs produced that, and neither was visible in a log line:

1. reference_supports_swap ran AFTER prepare_product_reference. That step grows
   the short edge to REFERENCE_MIN_EDGE (1024), four times MIN_SWAPPABLE_EDGE
   (256), so a 120px thumbnail was upscaled into "large enough" and the check
   could never fail. A LANCZOS upscale adds no letterforms — it only makes the
   absent lettering look like it is there.

2. product_name read calendar_item["product_name"], a column calendar_items
   does not have, so it resolved to the literal string "product" on every run.
   The editor was never told which pack it was copying, and the text guard's
   allow-list read ["product", vendor].
"""

import inspect

import pytest
from PIL import Image

from shared.product_swap import (
    MIN_SWAPPABLE_EDGE,
    REFERENCE_MIN_EDGE,
    prepare_product_reference,
    reference_supports_swap,
)
from workflows.content import nodes


class TestTheUpscaleLaundersTheCheck:
    def test_the_constants_make_a_post_upscale_check_impossible(self):
        assert REFERENCE_MIN_EDGE > MIN_SWAPPABLE_EDGE, (
            "if preparation can only grow the reference, a check made after it "
            "can never fail"
        )

    def test_a_thumbnail_fails_the_check_before_preparation(self):
        thumb = Image.new("RGB", (120, 120), (240, 240, 240))
        assert not reference_supports_swap(thumb)

    def test_the_same_thumbnail_passes_after_preparation(self):
        """The bug, demonstrated rather than described."""
        from io import BytesIO

        buf = BytesIO()
        Image.new("RGB", (120, 120), (240, 240, 240)).save(buf, format="PNG")
        prepared = Image.open(BytesIO(prepare_product_reference(buf.getvalue())))
        assert reference_supports_swap(prepared), (
            "this is what the old ordering asked, and it always answered yes"
        )


class TestCallSitesCheckBeforePreparing:
    def test_check_precedes_preparation(self):
        # Match the CALL sites, not the names: both appear in the module's
        # import block, in the other order.
        from shared.product_swap import swap_product_into_image

        src = inspect.getsource(swap_product_into_image)
        i_check = src.index("reference_supports_swap(raw_reference)")
        i_prep = src.index("prepare_product_reference(product_image_data)")
        assert i_check < i_prep, "the thumbnail check must run on the RAW reference"

    def test_there_is_only_one_swap_implementation(self):
        # worker.py and the content workflow each carried their own copy, and
        # they drifted: the regeneration path — the button a reviewer presses
        # BECAUSE the image was wrong — lost the fabrication guard entirely.
        import worker

        for module in (worker, nodes):
            src = inspect.getsource(module)
            assert "reference_supports_swap(" not in src, (
                f"{module.__name__} is reimplementing the swap instead of "
                "calling shared.product_swap.swap_product_into_image"
            )
            assert "prepare_product_reference(" not in src

    def test_both_paths_call_the_shared_swap(self):
        import worker

        for module in (worker, nodes):
            assert "swap_product_into_image(" in inspect.getsource(module)


class TestTheEditorIsToldWhichPack:
    def test_product_name_no_longer_reads_a_column_that_does_not_exist(self):
        src = inspect.getsource(nodes._replace_product_in_generated_image)
        assert 'calendar_item", {}).get("product_name"' not in src, (
            "calendar_items has no product_name column, so this resolved to "
            "the literal 'product' on every run"
        )
        assert '.get("name")' in src, "the name must come from the product row"

    def test_the_fallback_chain_is_name_then_title_then_generic(self):
        src = inspect.getsource(nodes._replace_product_in_generated_image)
        # A generic default is still needed, but it must be LAST. Match the
        # fallback expression itself — the bare word appears in the comment
        # above it explaining the old bug.
        assert src.index('_prod.get("name")') < src.index('or "product"')
