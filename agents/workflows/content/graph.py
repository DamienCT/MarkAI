"""Content generation workflow LangGraph definition."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine

from langgraph.graph import StateGraph, END

from workflows.content.state import ContentState
from workflows.content.nodes import (
    load_context,
    enrich_user_brief,
    generate_hook,
    generate_caption,
    generate_hashtags,
    source_product_image_node,
    enhance_image_prompt,
    generate_background,
    apply_branding,
    review_branding,
    adapt_platforms,
    generate_mockups_node,
    store_content_node,
)

logger = logging.getLogger(__name__)

# Ordered pipeline steps — used by the frontend workflow tracker
CONTENT_PIPELINE_STEPS = [
    "load_context",
    "enrich_user_brief",
    "generate_hook",
    "generate_caption",
    "generate_hashtags",
    "source_product_image",
    "enhance_image_prompt",
    "generate_background",
    "apply_branding",
    "review_branding",
    "adapt_platforms",
    "generate_mockups",
    "store_content",
]


def _with_step_tracking(
    step_name: str,
    step_index: int,
    node_fn: Callable[..., Coroutine[Any, Any, dict[str, Any]]],
) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
    """Wrap a node function to update the calendar item's generation_metadata
    with the current pipeline step before executing the node."""

    async def wrapper(state: ContentState) -> dict[str, Any]:
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
                meta["total_steps"] = len(CONTENT_PIPELINE_STEPS)

                await execute_update(
                    "UPDATE calendar_items SET generation_metadata = :meta WHERE id = :id",
                    {"meta": json.dumps(meta), "id": item_id},
                )
            except Exception as exc:
                logger.debug("Step tracking update failed: %s", exc)

        return await node_fn(state)

    wrapper.__name__ = node_fn.__name__
    return wrapper


def _check_failed(state: ContentState) -> str:
    """Route to END early if a prior node set status='failed'."""
    return "end" if state.get("status") == "failed" else "continue"


# Build nodes with step tracking wrappers
_nodes = [
    ("load_context", load_context),
    ("enrich_user_brief", enrich_user_brief),
    ("generate_hook", generate_hook),
    ("generate_caption", generate_caption),
    ("generate_hashtags", generate_hashtags),
    ("source_product_image", source_product_image_node),
    ("enhance_image_prompt", enhance_image_prompt),
    ("generate_background", generate_background),
    ("apply_branding", apply_branding),
    ("review_branding", review_branding),
    ("adapt_platforms", adapt_platforms),
    ("generate_mockups", generate_mockups_node),
    ("store_content", store_content_node),
]

builder = StateGraph(ContentState)

for idx, (name, fn) in enumerate(_nodes):
    builder.add_node(name, _with_step_tracking(name, idx, fn))

builder.set_entry_point("load_context")
builder.add_conditional_edges(
    "load_context", _check_failed, {"end": END, "continue": "enrich_user_brief"}
)
builder.add_conditional_edges(
    "enrich_user_brief", _check_failed, {"end": END, "continue": "generate_hook"}
)
builder.add_conditional_edges(
    "generate_hook", _check_failed, {"end": END, "continue": "generate_caption"}
)
builder.add_conditional_edges(
    "generate_caption", _check_failed, {"end": END, "continue": "generate_hashtags"}
)
builder.add_conditional_edges(
    "generate_hashtags", _check_failed, {"end": END, "continue": "source_product_image"}
)
builder.add_conditional_edges(
    "source_product_image",
    _check_failed,
    {"end": END, "continue": "enhance_image_prompt"},
)
builder.add_conditional_edges(
    "enhance_image_prompt",
    _check_failed,
    {"end": END, "continue": "generate_background"},
)
builder.add_conditional_edges(
    "generate_background",
    _check_failed,
    {"end": END, "continue": "apply_branding"},
)
builder.add_conditional_edges(
    "apply_branding", _check_failed, {"end": END, "continue": "review_branding"}
)
builder.add_conditional_edges(
    "review_branding", _check_failed, {"end": END, "continue": "adapt_platforms"}
)
builder.add_conditional_edges(
    "adapt_platforms", _check_failed, {"end": END, "continue": "generate_mockups"}
)
builder.add_conditional_edges(
    "generate_mockups", _check_failed, {"end": END, "continue": "store_content"}
)
builder.add_conditional_edges(
    "store_content", _check_failed, {"end": END, "continue": END}
)

content_graph = builder.compile()
