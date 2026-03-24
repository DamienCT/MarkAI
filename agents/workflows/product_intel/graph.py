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

builder = StateGraph(ProductIntelState)

builder.add_node("discover_brands", discover_brands)
builder.add_node("research_brand", research_brand)
builder.add_node("match_products_to_brands", match_products_to_brands)
builder.add_node("source_product_images", source_product_images_node)
builder.add_node("flag_promotable", flag_promotable)

builder.set_entry_point("discover_brands")
builder.add_edge("discover_brands", "research_brand")
builder.add_edge("research_brand", "match_products_to_brands")
builder.add_edge("match_products_to_brands", "source_product_images")
builder.add_edge("source_product_images", "flag_promotable")
builder.add_edge("flag_promotable", END)

product_intel_graph = builder.compile()
