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
builder.add_edge("generate_hook", "generate_caption")
builder.add_edge("generate_caption", "generate_hashtags")
builder.add_edge("generate_hashtags", "source_product_image")
builder.add_edge("source_product_image", "generate_background")
builder.add_edge("generate_background", "apply_branding")
builder.add_edge("apply_branding", "adapt_platforms")
builder.add_edge("adapt_platforms", "generate_mockups")
builder.add_edge("generate_mockups", "store_content")
builder.add_edge("store_content", END)

content_graph = builder.compile()
