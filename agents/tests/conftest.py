"""Shared test fixtures.

The native-multishot capability probe (shared.video.forge_supports_multishot)
is a live HTTP GET against the forge gateway, and a developer box often has a
REAL forge listening on VIDEO_FORGE_URL — a suite that quietly routes
render_video through whatever that box happens to advertise is not a test
suite. Every test therefore starts with the probe answering False (chained
path, the pre-native behaviour every existing test was written against);
native-branch tests opt in by patching the probe to answer True themselves.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _no_native_multishot_probe(monkeypatch):
    import shared.video as shared_video

    async def _no_forge_multishot():
        return False

    monkeypatch.setattr(
        shared_video, "forge_supports_multishot", _no_forge_multishot
    )
