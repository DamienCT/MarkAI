"""Content generation workflow LangGraph definition."""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from workflows.content.state import ContentState
from workflows.content.nodes import (
    load_context,
    generate_hook,
    generate_caption,
    generate_hashtags,
    source_product_image_node,
    generate_background,
    adapt_platforms,
    apply_branding,
    generate_mockups_node,
    store_content_node,
)


def _check_failed(state: ContentState) -> str:
    """Route to END early if a prior node set status='failed'."""
    return "end" if state.get("status") == "failed" else "continue"


builder = StateGraph(ContentState)

builder.add_node("load_context", load_context)
builder.add_node("generate_hook", generate_hook)
builder.add_node("generate_caption", generate_caption)
builder.add_node("generate_hashtags", generate_hashtags)
builder.add_node("source_product_image", source_product_image_node)
builder.add_node("generate_background", generate_background)
builder.add_node("adapt_platforms", adapt_platforms)
builder.add_node("apply_branding", apply_branding)
builder.add_node("generate_mockups", generate_mockups_node)
builder.add_node("store_content", store_content_node)

builder.set_entry_point("load_context")
builder.add_conditional_edges("load_context", _check_failed, {"end": END, "continue": "generate_hook"})
builder.add_conditional_edges("generate_hook", _check_failed, {"end": END, "continue": "generate_caption"})
builder.add_conditional_edges("generate_caption", _check_failed, {"end": END, "continue": "generate_hashtags"})
builder.add_conditional_edges("generate_hashtags", _check_failed, {"end": END, "continue": "source_product_image"})
builder.add_conditional_edges("source_product_image", _check_failed, {"end": END, "continue": "generate_background"})
builder.add_conditional_edges("generate_background", _check_failed, {"end": END, "continue": "apply_branding"})
builder.add_conditional_edges("apply_branding", _check_failed, {"end": END, "continue": "adapt_platforms"})
builder.add_conditional_edges("adapt_platforms", _check_failed, {"end": END, "continue": "generate_mockups"})
builder.add_conditional_edges("generate_mockups", _check_failed, {"end": END, "continue": "store_content"})
builder.add_edge("store_content", END)

content_graph = builder.compile()
