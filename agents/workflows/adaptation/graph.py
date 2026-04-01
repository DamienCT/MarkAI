"""Adaptation workflow LangGraph definition with interrupts for tier 2 and tier 3."""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from workflows.adaptation.state import AdaptationState
from workflows.adaptation.nodes import (
    load_adaptations,
    apply_tier1,
    propose_tier2,
    propose_tier3,
)


def _check_failed(state: AdaptationState) -> str:
    """Route to END early if a prior node set status='failed'."""
    return "end" if state.get("status") == "failed" else "continue"


builder = StateGraph(AdaptationState)

builder.add_node("load_adaptations", load_adaptations)
builder.add_node("apply_tier1", apply_tier1)
builder.add_node("propose_tier2", propose_tier2)
builder.add_node("propose_tier3", propose_tier3)

builder.set_entry_point("load_adaptations")
builder.add_conditional_edges(
    "load_adaptations", _check_failed, {"end": END, "continue": "apply_tier1"}
)
builder.add_conditional_edges(
    "apply_tier1", _check_failed, {"end": END, "continue": "propose_tier2"}
)
builder.add_conditional_edges(
    "propose_tier2", _check_failed, {"end": END, "continue": "propose_tier3"}
)
builder.add_conditional_edges(
    "propose_tier3", _check_failed, {"end": END, "continue": END}
)

# Compile without checkpointer — these are one-shot linear workflows
adaptation_graph = builder.compile()
