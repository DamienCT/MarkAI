"""Regression tests for verifier-identified residuals (backend API cluster).

Covers:
- FLAG-DISPLAY: the kill-switch GET fails closed on a malformed
  system_flags value, matching the enforcement path (never shows
  "enabled" while dispatch is blocked)
- QUALITY-FLAGS-COMPLETE: _video_job_quality_flags reads label_guard from
  params (chained/single-call lanes) as well as the generation ledger

(The PUBLISHED-AT-CLAMP tests that lived here died with the n8n publish
callback — direct publishers stamp published_at server-side in
record_publish_result, so no externally supplied timestamp exists anymore.)
"""

from types import SimpleNamespace

from app.api.v1.content import _video_job_quality_flags
from app.api.v1.system import _flag_enabled

# ── FLAG-DISPLAY: kill-switch GET decode fails closed ───────────────────


def test_flag_enabled_absent_means_enabled():
    assert _flag_enabled(None) is True


def test_flag_enabled_decodes_dict_and_json():
    assert _flag_enabled({"enabled": False}) is False
    assert _flag_enabled({"enabled": True}) is True
    assert _flag_enabled('{"enabled": false}') is False
    assert _flag_enabled('{"enabled": true}') is True


def test_flag_enabled_malformed_fails_closed():
    """Enforcement (publish_service.is_publishing_enabled) fails closed on a
    malformed flag — the display must agree, never show enabled while
    dispatch is blocked."""
    assert _flag_enabled("{not valid json") is False
    assert _flag_enabled("") is False


# ── QUALITY-FLAGS-COMPLETE: label_guard from params + ledger ────────────


def test_quality_flags_reads_label_guard_from_params():
    job = SimpleNamespace(
        params={"label_guard": {"status": "flagged", "frames": 3}},
        generation_ledger=None,
    )
    flags = _video_job_quality_flags(job)
    assert flags["label_guard"] == {"status": "flagged", "frames": 3}


def test_quality_flags_ledger_still_wins_for_native_lane():
    job = SimpleNamespace(
        params={"label_guard": {"status": "params"}, "audio_finish": "trimmed"},
        generation_ledger=[{"label_guard": {"status": "ledger"}}],
    )
    flags = _video_job_quality_flags(job)
    assert flags["label_guard"] == {"status": "ledger"}
    assert flags["audio_finish"] == "trimmed"
