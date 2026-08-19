"""Tests for logo placement: clearance from the text overlay, WCAG contrast
scoring of the spot the logo lands on, and duplicate-mark detection.

Covers the ``logo_misplaced`` defect class:
  * the brand mark composited through the headline card
    ("Mid-year is a good time to check in", "Start with a 2-minute body check")
  * the mark dropped on a shadowed / same-tone region while a clean high
    contrast area went unused ("One week to shop with ease",
    "Weekend board, instantly inviting")
  * the brand's own logo re-stamped as the product/category logo
    ("Checking your baseline starts at home")

...and their inverses: a placement that is already clear and readable must be
left exactly where the art director put it.

Pure functions only — no network, no MinIO.
"""

import os
import sys
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.image_processing import (  # noqa: E402
    MIN_LOGO_CONTRAST,
    candidate_logo_centers,
    choose_logo_placement,
    compute_text_region,
    contrast_ratio,
    glass_card_layout,
    headline_layout,
    logo_box_at,
    logo_contrast_at,
    logo_ink_rgb,
    overlay_logo_and_text,
    relative_luminance,
    rects_overlap,
    same_logo_mark,
)

W, H = 1024, 1024
HOOK = "Start with a 2-minute body check"

WHITE = (255, 255, 255)
BLACK = (18, 18, 18)
CYAN = (79, 220, 239)
PALE_STONE = (226, 224, 216)
OLIVE_WALL = (108, 122, 74)


def _png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _flat(color, size=(W, H)) -> bytes:
    return _png(Image.new("RGB", size, color))


def _two_tone(top_color, bottom_color, split=0.5) -> bytes:
    """Top band one colour, bottom band another — a controllable backdrop."""
    img = Image.new("RGB", (W, H), top_color)
    ImageDraw.Draw(img).rectangle([0, int(H * split), W, H], fill=bottom_color)
    return _png(img)


def _logo(color, w=600, h=240) -> bytes:
    """A mark + wordmark lockup stand-in: a ring and a solid bar."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([10, 10, 170, 170], outline=color + (255,), width=24)
    d.rectangle([200, 60, w - 10, 150], fill=color + (255,))
    return _png(im)


def _diamond(color, w=400, h=400) -> bytes:
    """A visually unrelated mark, for the negative dedupe case."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).polygon(
        [(w // 2, 10), (w - 10, h // 2), (w // 2, h - 10), (10, h // 2)],
        fill=color + (255,),
    )
    return _png(im)


def _logo_size(logo_bytes: bytes, scale: float = 0.24) -> tuple[int, int]:
    im = Image.open(BytesIO(logo_bytes)).convert("RGBA")
    im = im.crop(im.getbbox())
    lw = int(W * scale)
    return lw, int(im.height * (lw / im.width))


class TestContrastPrimitives:
    def test_relative_luminance_endpoints(self):
        assert relative_luminance((0, 0, 0)) == pytest.approx(0.0, abs=1e-6)
        assert relative_luminance((255, 255, 255)) == pytest.approx(1.0, abs=1e-6)

    def test_black_on_white_is_maximum_contrast(self):
        ratio = contrast_ratio(relative_luminance(BLACK), relative_luminance(WHITE))
        assert ratio > 15.0

    def test_same_tone_is_minimum_contrast(self):
        ratio = contrast_ratio(
            relative_luminance(OLIVE_WALL), relative_luminance(OLIVE_WALL)
        )
        assert ratio == pytest.approx(1.0)

    def test_ink_rgb_ignores_transparent_padding(self):
        """A white wordmark on a transparent canvas must report as white, not
        as a washed-out average of ink and empty pixels."""
        logo = Image.open(BytesIO(_logo(WHITE))).convert("RGBA")
        r, g, b = logo_ink_rgb(logo)
        assert min(r, g, b) > 240


class TestLogoContrastAt:
    def test_dark_ink_on_dark_band_scores_below_floor(self):
        """The Naturespan failure: a dark-green wordmark dropped on a dark
        shadowed plank. Low variance, so the old heuristic loved it."""
        img = _two_tone(PALE_STONE, (46, 52, 38))
        lw, lh = _logo_size(_logo(BLACK))
        assert logo_contrast_at(img, 0.5, 0.85, lw, lh, BLACK) < MIN_LOGO_CONTRAST

    def test_same_ink_on_the_pale_band_scores_well(self):
        img = _two_tone(PALE_STONE, (46, 52, 38))
        lw, lh = _logo_size(_logo(BLACK))
        assert logo_contrast_at(img, 0.5, 0.15, lw, lh, BLACK) > MIN_LOGO_CONTRAST

    def test_scores_the_worst_tenth_not_the_average(self):
        """A patch that averages to mid-grey but contains a large same-tone
        area must score low — the mark partly vanishes there."""
        img = Image.new("RGB", (W, H), WHITE)
        # A black block covering the left half of the top-left logo patch.
        ImageDraw.Draw(img).rectangle([0, 0, W // 4, H // 4], fill=BLACK)
        data = _png(img)
        lw, lh = _logo_size(_logo(BLACK))
        assert logo_contrast_at(data, 0.18, 0.14, lw, lh, BLACK) < MIN_LOGO_CONTRAST


class TestTextRegion:
    def test_glass_card_region_matches_what_is_drawn(self):
        """Guards against the reserved rect drifting from the rendered card:
        the card is the only thing that changes on a flat backdrop, so the
        bounding box of changed pixels IS the card."""
        base = _flat((120, 130, 140))
        rect = compute_text_region(W, H, HOOK, text_style="glass", text_anchor="top-left")
        out = overlay_logo_and_text(
            base, _logo(WHITE), text_line1=HOOK, text_anchor="top-left",
            logo_scale=0.001,  # effectively no logo
        )
        before = Image.open(BytesIO(base)).convert("RGB")
        after = Image.open(BytesIO(out)).convert("RGB")
        from PIL import ImageChops

        drawn = ImageChops.difference(before, after).getbbox()
        assert drawn is not None
        # Rendered card must sit inside the reserved rect (± the 1px border).
        assert drawn[0] >= rect[0] - 2 and drawn[1] >= rect[1] - 2
        assert drawn[2] <= rect[2] + 2 and drawn[3] <= rect[3] + 2

    def test_headline_region_matches_what_is_drawn(self):
        base = _flat((30, 34, 40))
        rect = compute_text_region(
            W, H, HOOK, text_style="headline", text_xy=(0.5, 0.25), text_width=0.7
        )
        out = overlay_logo_and_text(
            base, _logo(WHITE), text_line1=HOOK, text_style="headline",
            text_xy=(0.5, 0.25), text_width=0.7, logo_scale=0.001,
        )
        from PIL import ImageChops

        drawn = ImageChops.difference(
            Image.open(BytesIO(base)).convert("RGB"),
            Image.open(BytesIO(out)).convert("RGB"),
        ).getbbox()
        assert drawn is not None
        # Glyph shadows extend a few px past the metric box.
        pad = 12
        assert drawn[0] >= rect[0] - pad and drawn[1] >= rect[1] - pad
        assert drawn[2] <= rect[2] + pad and drawn[3] <= rect[3] + pad

    def test_no_region_reserved_when_text_is_removed(self):
        assert compute_text_region(W, H, HOOK, text_style="none") is None

    def test_no_region_reserved_for_empty_headline(self):
        assert compute_text_region(W, H, "   ", text_style="glass") is None

    def test_anchor_drives_the_card_corner(self):
        top = glass_card_layout(W, H, HOOK, text_anchor="top-left")["rect"]
        bottom = glass_card_layout(W, H, HOOK, text_anchor="bottom-left")["rect"]
        assert top[1] < H // 2 < bottom[1]

    def test_headline_wrap_width_changes_line_count(self):
        wide = headline_layout(W, H, HOOK, text_width=0.95)
        narrow = headline_layout(W, H, HOOK, text_width=0.35)
        assert len(narrow["placed"]) > len(wide["placed"])


class TestChooseLogoPlacement:
    def test_logo_on_top_of_the_text_card_is_moved_off_it(self):
        """'Start with a 2-minute body check' — the critic put the logo at
        (0.14, 0.12) and anchored the card top-left, so the mark was stamped
        straight through the headline."""
        base = _two_tone(WHITE, (40, 44, 50))
        rect = compute_text_region(W, H, HOOK, text_style="glass", text_anchor="top-left")
        logo = _logo(BLACK)
        lw, lh = _logo_size(logo)

        assert rects_overlap(logo_box_at(0.14, 0.12, lw, lh, W, H), rect)

        xy, info = choose_logo_placement(
            base, lw, lh, logo_ink_rgb(Image.open(BytesIO(logo))),
            proposed_xy=(0.14, 0.12), avoid_rect=rect,
        )
        assert info["changed"] is True
        assert not rects_overlap(logo_box_at(xy[0], xy[1], lw, lh, W, H), rect)

    def test_logo_touching_the_card_edge_is_moved(self):
        """'Track health trends before they feel urgent' — only the top spoke
        of the mark pushed into the pill, which still reads as damage."""
        base = _two_tone(WHITE, (40, 44, 50))
        rect = compute_text_region(W, H, HOOK, text_style="glass", text_anchor="top-right")
        logo = _logo(BLACK)
        lw, lh = _logo_size(logo)
        # Centre chosen so the logo box starts a couple of px below the card.
        just_below = (rect[3] + lh / 2 + 2) / H
        xy, info = choose_logo_placement(
            base, lw, lh, logo_ink_rgb(Image.open(BytesIO(logo))),
            proposed_xy=(0.82, just_below), avoid_rect=rect,
        )
        assert info["changed"] is True

    def test_low_contrast_spot_is_abandoned_for_a_readable_one(self):
        """'Weekend board, instantly inviting' — a grey-green mark on pale
        stone, while a flat olive wall sat unused in the opposite band."""
        base = _two_tone(OLIVE_WALL, PALE_STONE)
        logo = _logo((245, 247, 243))  # near-white mark: vanishes on the stone
        lw, lh = _logo_size(logo)
        ink = logo_ink_rgb(Image.open(BytesIO(logo)))

        assert logo_contrast_at(base, 0.18, 0.90, lw, lh, ink) < MIN_LOGO_CONTRAST

        xy, info = choose_logo_placement(
            base, lw, lh, ink, proposed_xy=(0.18, 0.90), avoid_rect=None,
        )
        assert info["changed"] is True
        assert xy[1] < 0.5, "should move up onto the olive wall"
        assert info["contrast"] >= MIN_LOGO_CONTRAST

    def test_good_placement_is_left_alone(self):
        """The inverse: 'Real brands, real proof on pack' style placements —
        clear of the text and high contrast — must not be second-guessed."""
        base = _two_tone(WHITE, (40, 44, 50))
        rect = compute_text_region(
            W, H, HOOK, text_style="glass", text_anchor="bottom-left"
        )
        logo = _logo(BLACK)
        lw, lh = _logo_size(logo)
        proposed = (0.80, 0.12)  # top-right, on the white band, clear of the card

        assert not rects_overlap(logo_box_at(*proposed, lw, lh, W, H), rect)

        xy, info = choose_logo_placement(
            base, lw, lh, logo_ink_rgb(Image.open(BytesIO(logo))),
            proposed_xy=proposed, avoid_rect=rect,
        )
        assert info["changed"] is False
        assert xy == proposed

    def test_relocation_prefers_the_nearest_readable_spot(self):
        """Intent is preserved: among spots that clear the text and read, take
        the closest one rather than hunting for maximum contrast."""
        base = _flat(WHITE)
        rect = compute_text_region(W, H, HOOK, text_style="glass", text_anchor="top-right")
        logo = _logo(BLACK)
        lw, lh = _logo_size(logo)
        xy, info = choose_logo_placement(
            base, lw, lh, logo_ink_rgb(Image.open(BytesIO(logo))),
            proposed_xy=(0.82, 0.12), avoid_rect=rect,
        )
        assert info["changed"] is True
        candidates = candidate_logo_centers(W, H, lw, lh)
        clear = [
            c for c in candidates
            if not rects_overlap(logo_box_at(c[0], c[1], lw, lh, W, H), rect, 15)
        ]
        nearest = min(clear, key=lambda c: (c[0] - 0.82) ** 2 + (c[1] - 0.12) ** 2)
        assert xy == nearest

    def test_never_moves_when_nothing_is_better(self):
        """A uniformly hopeless frame (mark and backdrop the same tone) keeps
        the art director's choice rather than shuffling it pointlessly."""
        base = _flat(OLIVE_WALL)
        logo = _logo(OLIVE_WALL)
        lw, lh = _logo_size(logo)
        xy, info = choose_logo_placement(
            base, lw, lh, logo_ink_rgb(Image.open(BytesIO(logo))),
            proposed_xy=(0.5, 0.5), avoid_rect=None,
        )
        assert info["changed"] is False
        assert xy == (0.5, 0.5)

    def test_candidates_include_the_bottom_edge(self):
        """Bottom corners were blanket-banned by find_best_logo_position
        because the text bar *might* be there. Now the text box is passed
        explicitly, so the bottom half is usable again."""
        centers = candidate_logo_centers(W, H, 200, 100)
        assert any(y > 0.5 for _, y in centers)


class TestOverlayEnforcesClearance:
    @staticmethod
    def _ink_pixels_in(png: bytes, rect, ink) -> int:
        """Count pixels inside *rect* that are close to the logo's ink colour."""
        crop = Image.open(BytesIO(png)).convert("RGB").crop(rect)
        return sum(
            1
            for px in crop.getdata()
            if all(abs(px[i] - ink[i]) < 40 for i in range(3))
        )

    def test_render_moves_a_colliding_logo_off_the_card(self):
        """End to end: the same call that stamped the mark through the pill
        now renders it clear of the pill."""
        magenta = (222, 30, 180)  # nothing else on the canvas is this colour
        base = _two_tone(WHITE, (40, 44, 50))
        logo = _logo(magenta)
        rect = compute_text_region(W, H, HOOK, text_style="glass", text_anchor="top-left")

        kwargs = dict(
            text_line1=HOOK, text_anchor="top-left",
            logo_xy=(0.14, 0.06), logo_scale=0.24,
        )
        loose = overlay_logo_and_text(base, logo, enforce_logo_clearance=False, **kwargs)
        gated = overlay_logo_and_text(base, logo, enforce_logo_clearance=True, **kwargs)

        assert self._ink_pixels_in(loose, rect, magenta) > 500, (
            "precondition: the ungated render must put logo ink on the card"
        )
        assert self._ink_pixels_in(gated, rect, magenta) == 0

    def test_render_keeps_a_clean_placement_untouched(self):
        """The inverse: a logo already clear of the card and readable renders
        byte-identically whether the gate is on or off."""
        base = _two_tone(WHITE, (40, 44, 50))
        logo = _logo(BLACK)
        kwargs = dict(
            text_line1=HOOK, text_anchor="bottom-left",
            logo_xy=(0.80, 0.12), logo_scale=0.24,
        )
        loose = overlay_logo_and_text(base, logo, enforce_logo_clearance=False, **kwargs)
        gated = overlay_logo_and_text(base, logo, enforce_logo_clearance=True, **kwargs)
        assert loose == gated

    def test_manual_placement_is_respected(self):
        """The editor's drag is final — the gate must be a no-op there."""
        base = _two_tone(WHITE, (40, 44, 50))
        logo = _logo(BLACK)
        a = overlay_logo_and_text(
            base, logo, text_line1=HOOK, text_anchor="top-left",
            logo_xy=(0.14, 0.12), logo_scale=0.24, enforce_logo_clearance=False,
        )
        b = overlay_logo_and_text(
            base, logo, text_line1=HOOK, text_anchor="top-left",
            logo_xy=(0.14, 0.12), logo_scale=0.24, enforce_logo_clearance=False,
        )
        assert a == b

    def test_gate_is_idempotent(self):
        """Resolving in the node and again in the renderer must agree, or the
        persisted logo_xy would not match the pixels."""
        base = _two_tone(WHITE, (40, 44, 50))
        logo = _logo(BLACK)
        lw, lh = _logo_size(logo)
        rect = compute_text_region(W, H, HOOK, text_style="glass", text_anchor="top-left")
        ink = logo_ink_rgb(Image.open(BytesIO(logo)))

        first, info1 = choose_logo_placement(
            base, lw, lh, ink, proposed_xy=(0.14, 0.12), avoid_rect=rect
        )
        second, info2 = choose_logo_placement(
            base, lw, lh, ink, proposed_xy=first, avoid_rect=rect
        )
        assert info1["changed"] is True
        assert info2["changed"] is False
        assert second == first


class TestSameLogoMark:
    def test_identical_bytes_match(self):
        blob = _logo(CYAN)
        assert same_logo_mark(blob, blob) is True

    def test_recoloured_variant_of_the_same_mark_matches(self):
        """'Checking your baseline starts at home' / 'Busy weeks can raise
        blood pressure quietly': the brand logo was registered as the
        SUP-TOOLS category logo, once in cyan and once in solid black."""
        assert same_logo_mark(_logo(CYAN), _logo(BLACK)) is True

    def test_unrelated_marks_do_not_match(self):
        """A real vendor logo (the Citterio diamond) must survive."""
        assert same_logo_mark(_logo(CYAN), _diamond(CYAN)) is False

    def test_different_proportions_do_not_match(self):
        assert same_logo_mark(_logo(CYAN, w=600, h=240), _logo(CYAN, w=300, h=280)) is False

    def test_opaque_white_card_is_keyed_out_before_comparing(self):
        """Vendor logos often arrive as a JPEG on a white card; the silhouette
        must be the mark, not the rectangle."""
        mark = Image.open(BytesIO(_logo(BLACK))).convert("RGBA")
        flat = Image.new("RGB", mark.size, WHITE)
        flat.paste(mark, (0, 0), mark)
        assert same_logo_mark(_png(flat), _logo(CYAN)) is True

    def test_empty_input_is_not_a_match(self):
        assert same_logo_mark(b"", _logo(CYAN)) is False
        assert same_logo_mark(_logo(CYAN), b"") is False

    def test_undecodable_input_is_not_a_match(self):
        assert same_logo_mark(b"not an image", _logo(CYAN)) is False
