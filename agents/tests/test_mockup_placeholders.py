"""Platform mockups stop fabricating engagement metrics (MOCKUP-METRICS).

The mockup builders shipped with invented numbers baked into every preview:
"2,847 likes", "View all 42 comments", "89 comments · 34 shares",
"Health & Wellness · 1,234 followers" (a hardcoded WRONG industry), "12K"
impressions, and so on. A preview that fabricates metrics reads as a lie the
moment it lands in a review UI or a client deck. These tests pin the
replacement contract: no hardcoded engagement counts anywhere in the module
source, and the LinkedIn header line carries the brand's REAL industry when
one is passed — omitted entirely when it is not.
"""

import inspect
import re
from io import BytesIO

import pytest

import shared.image_processing as ip

_SOURCE = inspect.getsource(ip)

# A digit (optionally 1,234 / 1.2K shaped) followed by an engagement word.
_METRIC_RE = re.compile(
    r"\d[\d,.]*\s*K?\s+(likes?|comments?|shares?|reposts?|followers?)",
    re.IGNORECASE,
)


class TestNoFabricatedMetricsInSource:
    def test_no_hardcoded_engagement_counts(self):
        hits = [
            line.strip()
            for line in _SOURCE.splitlines()
            if _METRIC_RE.search(line)
        ]
        assert hits == [], f"fabricated engagement counts in mockups: {hits}"

    def test_the_specific_fabrications_are_gone(self):
        # The exact strings the audit flagged (as they appeared in source,
        # including the escaped-emoji count labels of the X action row).
        for needle in [
            "2,847",
            "View all 42",
            "1.2K",
            "89 comments",
            "34 shares",
            "1,234",
            "Health & Wellness",
            "52 comments",
            "18 reposts",
            "12K",
            r"\U0001f4ac 42",
            r"\U0001f501 128",
            "\\u2661 847",
        ]:
            assert needle not in _SOURCE, f"fabricated metric survives: {needle}"


class TestLinkedInIndustryLine:
    def test_generate_mockup_accepts_a_real_industry(self):
        sig = inspect.signature(ip.generate_mockup)
        assert "industry" in sig.parameters
        assert sig.parameters["industry"].default == ""
        li_sig = inspect.signature(ip._mockup_linkedin)
        assert "industry" in li_sig.parameters
        assert li_sig.parameters["industry"].default == ""

    @pytest.mark.parametrize("industry", ["", "Food & Beverage"])
    def test_linkedin_mockup_renders_with_and_without_industry(self, industry):
        # The line must be optional: blank industry omits it rather than
        # inventing one, and neither path may crash the render.
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (200, 200), (200, 200, 200)).save(buf, format="PNG")
        out = ip.generate_mockup(
            buf.getvalue(),
            "A caption",
            "linkedin",
            display_name="NatureSpan",
            industry=industry,
        )
        assert out[:8] == b"\x89PNG\r\n\x1a\n"
