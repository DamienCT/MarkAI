"""Video generation workflow LangGraph definition."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine

from langgraph.graph import StateGraph, END

from workflows.video.nodes import (
    VideoState,
    enrich_user_brief,
    load_video_context,
    make_keyframe,
    plan_shots,
    render_video,
    source_product_image_for_video,
    store_video,
)

logger = logging.getLogger(__name__)

# Ordered pipeline steps — used by the frontend workflow tracker
VIDEO_PIPELINE_STEPS = [
    "load_context",
    "enrich_user_brief",
    "source_product_image",
    "plan_shots",
    "make_keyframe",
    "render_video",
    "store_video",
]


def _with_step_tracking(
    step_name: str,
    step_index: int,
    node_fn: Callable[..., Coroutine[Any, Any, dict[str, Any]]],
) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
    """Wrap a node function to update the calendar item's generation_metadata
    with the current pipeline step before executing the node."""

    async def wrapper(state: VideoState) -> dict[str, Any]:
        item_id = state.get("calendar_item_id")
        if item_id:
            try:
                from shared.tools.database import execute_update, execute_query

                # Read current metadata, merge in step info
                rows = await execute_query(
                    "SELECT generation_metadata FROM calendar_items WHERE id = :id",
                    {"id": item_id},
                )
                meta = {}
                if rows and rows[0].get("generation_metadata"):
                    raw = rows[0]["generation_metadata"]
                    meta = raw if isinstance(raw, dict) else json.loads(raw)

                meta["current_step"] = step_name
                meta["step_index"] = step_index
                meta["total_steps"] = len(VIDEO_PIPELINE_STEPS)

                await execute_update(
                    "UPDATE calendar_items SET generation_metadata = :meta WHERE id = :id",
                    {"meta": json.dumps(meta), "id": item_id},
                )
            except Exception as exc:
                logger.debug("Step tracking update failed: %s", exc)

        return await node_fn(state)

    wrapper.__name__ = node_fn.__name__
    return wrapper


def _check_failed(state: VideoState) -> str:
    """Route to END early if a prior node set status='failed'."""
    return "end" if state.get("status") == "failed" else "continue"


# Build nodes with step tracking wrappers
_nodes = [
    ("load_context", load_video_context),
    ("enrich_user_brief", enrich_user_brief),
    ("source_product_image", source_product_image_for_video),
    ("plan_shots", plan_shots),
    ("make_keyframe", make_keyframe),
    ("render_video", render_video),
    ("store_video", store_video),
]

builder = StateGraph(VideoState)

for idx, (name, fn) in enumerate(_nodes):
    builder.add_node(name, _with_step_tracking(name, idx, fn))

builder.set_entry_point("load_context")
builder.add_conditional_edges(
    "load_context", _check_failed, {"end": END, "continue": "enrich_user_brief"}
)
builder.add_conditional_edges(
    "enrich_user_brief", _check_failed, {"end": END, "continue": "source_product_image"}
)
builder.add_conditional_edges(
    "source_product_image", _check_failed, {"end": END, "continue": "plan_shots"}
)
builder.add_conditional_edges(
    "plan_shots", _check_failed, {"end": END, "continue": "make_keyframe"}
)
builder.add_conditional_edges(
    "make_keyframe", _check_failed, {"end": END, "continue": "render_video"}
)
builder.add_conditional_edges(
    "render_video", _check_failed, {"end": END, "continue": "store_video"}
)
builder.add_conditional_edges(
    "store_video", _check_failed, {"end": END, "continue": END}
)

video_graph = builder.compile()
