"""Nothing is ever composited over the product.

A delivered Naturespan post shipped with the brand logo stamped dead-centre
ON the jam jar: the jar's white label was the highest-contrast backdrop in
frame, the placer only knew to avoid the TEXT block, and (0.5, bottom) is a
legal conventional spot. The product region is now protected like the text —
measured by the vision planner when possible, assumed central otherwise.
"""

import asyncio
from io import BytesIO

import pytest
from PIL import Image

from shared import placement
from shared.image_processing import choose_logo_placement, _fit_feed_aspect


def _png(w=800, h=800, color=(255, 255, 255)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


class TestLogoAvoidsTheProduct:
    def test_a_proposal_on_the_product_is_moved_despite_perfect_contrast(self):
        # White image, dark ink: every spot reads. Only the protected rect
        # can reject the proposal — and it must.
        product_rect = (240, 240, 560, 720)
        xy, info = choose_logo_placement(
            _png(),
            logo_w=160,
            logo_h=80,
            ink_rgb=(20, 20, 20),
            proposed_xy=(0.5, 0.9),  # centre-bottom: inside the rect
            avoid_rect=None,
            avoid_rects=[product_rect],
        )
        assert info["changed"], "a logo on the product must be moved"
        # The chosen spot's box must clear the product rect.
        cx, cy = int(xy[0] * 800), int(xy[1] * 800)
        assert not (
            product_rect[0] - 80 <= cx <= product_rect[2] + 80
            and product_rect[1] - 40 <= cy <= product_rect[3] + 40
        )

    def test_a_clear_proposal_is_left_alone(self):
        xy, info = choose_logo_placement(
            _png(),
            logo_w=160,
            logo_h=80,
            ink_rgb=(20, 20, 20),
            proposed_xy=(0.12, 0.08),  # top-left corner, well clear
            avoid_rect=None,
            avoid_rects=[(240, 240, 560, 720)],
        )
        assert not info["changed"]
        assert xy == (0.12, 0.08)

    def test_the_resolver_defaults_to_the_central_product_box(self):
        import inspect

        from workflows.content import nodes as content_nodes

        src = inspect.getsource(content_nodes._resolve_logo_placement)
        assert "DEFAULT_PRODUCT_BOX" in src
        assert "avoid_rects=[product_rect]" in src

    def test_apply_branding_threads_the_measured_box(self):
        import inspect

        from workflows.content import nodes as content_nodes

        src = inspect.getsource(content_nodes.apply_branding)
        assert "product_box=product_box" in src

    def test_the_regen_path_unpacks_the_box_and_gates_the_logo(self):
        # plan_headline_placement grew a 7th element; the regen path's
        # 6-tuple unpack raised ValueError into its except and silently
        # disabled placement on every ad regen. It must unpack the box AND
        # gate the planner's logo spot like the first render does.
        import inspect

        import worker

        src = inspect.getsource(worker._handle_image_regeneration)
        assert "_product_box)" in src
        assert "choose_logo_placement" in src
        assert "DEFAULT_PRODUCT_BOX" in src


class TestVisionPlannerProductBox:
    def _plan(self, monkeypatch, payload: dict):
        import shared.llm as llm

        async def fake_chat(*a, **k):
            import json

            return json.dumps(payload)

        monkeypatch.setattr(llm, "chat_completion", fake_chat)
        return asyncio.run(
            placement.vision_headline_placement(_png(), "Fresh press, real proof")
        )

    def test_a_measured_box_comes_through(self, monkeypatch):
        out = self._plan(
            monkeypatch,
            {
                "text_xy": {"x": 0.5, "y": 0.15},
                "text_size": "m",
                "text_width": 0.8,
                "font_family": "Montserrat",
                "logo_xy": {"x": 0.9, "y": 0.9},
                "product_box": {"x0": 0.3, "y0": 0.4, "x1": 0.7, "y1": 0.95},
            },
        )
        assert out is not None
        assert out[6] == (0.3, 0.4, 0.7, 0.95)

    def test_a_degenerate_box_is_rejected(self, monkeypatch):
        out = self._plan(
            monkeypatch,
            {
                "text_xy": {"x": 0.5, "y": 0.15},
                "text_size": "m",
                "text_width": 0.8,
                "product_box": {"x0": 0.5, "y0": 0.5, "x1": 0.5, "y1": 0.9},
            },
        )
        assert out is not None
        assert out[6] is None

    def test_colors_are_always_empty_from_the_pipeline(self, monkeypatch):
        # A delivered ad shipped white/green/near-black words in ONE headline
        # (the dark word unreadable over a plant). One ink, measured at draw
        # time; per-word color stays an editor-only override.
        out = self._plan(
            monkeypatch,
            {
                "text_xy": {"x": 0.5, "y": 0.15},
                "text_size": "l",
                "text_width": 0.5,
                "text_colors": {"1": "#00ff00", "4": "#0a2a0a"},
            },
        )
        assert out is not None
        assert out[3] == {}

    def test_variance_fallback_reports_no_box(self):
        out = placement.variance_headline_placement(_png())
        assert out[6] is None
        assert placement.DEFAULT_PRODUCT_BOX[0] < 0.5 < placement.DEFAULT_PRODUCT_BOX[2]


class TestHonestMockups:
    def test_landscape_keeps_its_aspect(self):
        img = Image.new("RGB", (1536, 1024))
        out = _fit_feed_aspect(img, 780)
        assert out.width == 780
        assert out.height == pytest.approx(780 * 1024 / 1536, abs=2)

    def test_only_beyond_platform_bounds_is_cropped(self):
        # 9:16 is taller than any feed shows — clamped to 4:5, like the
        # platform itself does. Nothing else is cropped.
        tall = _fit_feed_aspect(Image.new("RGB", (1080, 1920)), 780)
        assert tall.height == pytest.approx(780 * 1.25, abs=2)
        ultra_wide = _fit_feed_aspect(Image.new("RGB", (2400, 1000)), 780)
        assert ultra_wide.height == pytest.approx(780 * 0.5236, abs=3)

    def test_no_mockup_square_crops_the_post(self):
        import inspect

        import shared.image_processing as ip

        for fn in (ip._mockup_instagram, ip._mockup_facebook,
                   ip._mockup_linkedin, ip._mockup_x):
            src = inspect.getsource(fn)
            assert "_center_crop_square(post_img" not in src, fn.__name__
            assert "_fit_feed_aspect(post_img" in src, fn.__name__


class TestHeadlineInk:
    def test_ink_flips_dark_on_a_pale_band(self):
        import inspect

        import shared.image_processing as ip

        src = inspect.getsource(ip.overlay_logo_and_text)
        # The measured switch exists and drives both ink and shadow.
        assert "band_luma > 175.0" in src
        assert "default_ink = (26, 26, 26, 255)" in src
        assert "shadow_fill" in src
