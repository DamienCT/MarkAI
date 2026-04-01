"""Evaluation workflow LangGraph definition."""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from workflows.evaluation.state import EvaluationState
from workflows.evaluation.nodes import (
    load_performance,
    analyze_patterns,
    generate_recommendations,
    classify_adaptations,
    store_adaptations_node,
)


def _check_failed(state: EvaluationState) -> str:
    """Route to END early if a prior node set status='failed'."""
    return "end" if state.get("status") == "failed" else "continue"


builder = StateGraph(EvaluationState)

builder.add_node("load_performance", load_performance)
builder.add_node("analyze_patterns", analyze_patterns)
builder.add_node("generate_recommendations", generate_recommendations)
builder.add_node("classify_adaptations", classify_adaptations)
builder.add_node("store_adaptations", store_adaptations_node)

builder.set_entry_point("load_performance")
builder.add_conditional_edges(
    "load_performance", _check_failed, {"end": END, "continue": "analyze_patterns"}
)
builder.add_conditional_edges(
    "analyze_patterns",
    _check_failed,
    {"end": END, "continue": "generate_recommendations"},
)
builder.add_conditional_edges(
    "generate_recommendations",
    _check_failed,
    {"end": END, "continue": "classify_adaptations"},
)
builder.add_conditional_edges(
    "classify_adaptations", _check_failed, {"end": END, "continue": "store_adaptations"}
)
builder.add_conditional_edges(
    "store_adaptations", _check_failed, {"end": END, "continue": END}
)

evaluation_graph = builder.compile()
