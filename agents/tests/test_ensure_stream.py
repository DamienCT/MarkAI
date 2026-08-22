"""_ensure_stream converges subjects without clobbering the stream config.

Pins the fix for a live 2026-08-22 incident: updating WORKFLOWS by kwargs
built a fresh StreamConfig whose retention defaulted to 'limits', and the
server refused the workqueue→limits change (err_code 10052) — so the worker
could never add its missing subjects. The update must send the FETCHED
config object, mutated only in its subjects, so retention (and every other
field) survives; and it must union-merge, never replace, because the
backend's nats_service owns subjects of its own on this stream.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import worker


def _fake_js(existing_subjects):
    config = SimpleNamespace(
        subjects=list(existing_subjects),
        retention="workqueue",
        max_age=86400 * 7,
    )
    js = SimpleNamespace(
        find_stream_name_by_subject=AsyncMock(return_value=worker.STREAM_NAME),
        stream_info=AsyncMock(return_value=SimpleNamespace(config=config)),
        update_stream=AsyncMock(),
        add_stream=AsyncMock(),
    )
    return js, config


def test_missing_subjects_update_preserves_retention():
    existing = ["research.>", "strategy.>", "backend.owned.>"]
    js, config = _fake_js(existing)
    consumer = SimpleNamespace(js=js)

    asyncio.run(worker._ensure_stream(consumer))

    js.update_stream.assert_awaited_once()
    kwargs = js.update_stream.await_args.kwargs
    # The fetched config object itself is sent back — retention intact.
    assert kwargs["config"] is config
    assert kwargs["config"].retention == "workqueue"
    # Union-merge: everything required is added, nothing existing stripped.
    assert set(config.subjects) >= set(worker.REQUIRED_SUBJECTS)
    assert "backend.owned.>" in config.subjects
    js.add_stream.assert_not_awaited()


def test_fully_converged_stream_is_left_alone():
    js, _ = _fake_js(list(worker.REQUIRED_SUBJECTS) + ["backend.owned.>"])
    consumer = SimpleNamespace(js=js)

    asyncio.run(worker._ensure_stream(consumer))

    js.update_stream.assert_not_awaited()
    js.add_stream.assert_not_awaited()
