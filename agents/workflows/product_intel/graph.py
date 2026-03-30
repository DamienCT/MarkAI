"""Product intelligence workflow LangGraph definition."""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from workflows.product_intel.state import ProductIntelState
from workflows.product_intel.nodes import (
    discover_brands,
    research_brand,
    match_products_to_brands,
    source_product_images_node,
    flag_promotable,
)

def _check_failed(state: ProductIntelState) -> str:
    """Route to END early if a prior node set status='failed'."""
    return "end" if state.get("status") == "failed" else "continue"


builder = StateGraph(ProductIntelState)

builder.add_node("discover_brands", discover_brands)
builder.add_node("research_brand", research_brand)
builder.add_node("match_products_to_brands", match_products_to_brands)
builder.add_node("source_product_images", source_product_images_node)
builder.add_node("flag_promotable", flag_promotable)

builder.set_entry_point("discover_brands")
builder.add_conditional_edges("discover_brands", _check_failed, {"end": END, "continue": "research_brand"})
builder.add_conditional_edges("research_brand", _check_failed, {"end": END, "continue": "match_products_to_brands"})
builder.add_conditional_edges("match_products_to_brands", _check_failed, {"end": END, "continue": "source_product_images"})
builder.add_conditional_edges("source_product_images", _check_failed, {"end": END, "continue": "flag_promotable"})
builder.add_conditional_edges("flag_promotable", _check_failed, {"end": END, "continue": END})

product_intel_graph = builder.compile()
