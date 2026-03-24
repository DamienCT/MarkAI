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

builder = StateGraph(EvaluationState)

builder.add_node("load_performance", load_performance)
builder.add_node("analyze_patterns", analyze_patterns)
builder.add_node("generate_recommendations", generate_recommendations)
builder.add_node("classify_adaptations", classify_adaptations)
builder.add_node("store_adaptations", store_adaptations_node)

builder.set_entry_point("load_performance")
builder.add_edge("load_performance", "analyze_patterns")
builder.add_edge("analyze_patterns", "generate_recommendations")
builder.add_edge("generate_recommendations", "classify_adaptations")
builder.add_edge("classify_adaptations", "store_adaptations")
builder.add_edge("store_adaptations", END)

evaluation_graph = builder.compile()
