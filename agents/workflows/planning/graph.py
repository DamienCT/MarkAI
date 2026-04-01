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


def _check_failed(state: PlanningState) -> str:
    """Route to END early if a prior node set status='failed'."""
    return "end" if state.get("status") == "failed" else "continue"


builder = StateGraph(PlanningState)

builder.add_node("load_strategy", load_strategy)
builder.add_node("generate_campaigns", generate_campaigns)
builder.add_node("generate_calendar", generate_calendar)
builder.add_node("assign_products", assign_products)
builder.add_node("store_calendar", store_calendar)

builder.set_entry_point("load_strategy")
builder.add_conditional_edges(
    "load_strategy", _check_failed, {"end": END, "continue": "generate_campaigns"}
)
builder.add_conditional_edges(
    "generate_campaigns", _check_failed, {"end": END, "continue": "generate_calendar"}
)
builder.add_conditional_edges(
    "generate_calendar", _check_failed, {"end": END, "continue": "assign_products"}
)
builder.add_conditional_edges(
    "assign_products", _check_failed, {"end": END, "continue": "store_calendar"}
)
builder.add_conditional_edges(
    "store_calendar", _check_failed, {"end": END, "continue": END}
)

planning_graph = builder.compile()
