"""Calendar planning workflow LangGraph definition."""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from workflows.planning.state import PlanningState
from workflows.planning.nodes import (
    load_strategy,
    generate_campaigns,
    generate_calendar,
    assign_products,
    store_calendar,
)

builder = StateGraph(PlanningState)

builder.add_node("load_strategy", load_strategy)
builder.add_node("generate_campaigns", generate_campaigns)
builder.add_node("generate_calendar", generate_calendar)
builder.add_node("assign_products", assign_products)
builder.add_node("store_calendar", store_calendar)

builder.set_entry_point("load_strategy")
builder.add_edge("load_strategy", "generate_campaigns")
builder.add_edge("generate_campaigns", "generate_calendar")
builder.add_edge("generate_calendar", "assign_products")
builder.add_edge("assign_products", "store_calendar")
builder.add_edge("store_calendar", END)

planning_graph = builder.compile()
