"""Adaptation workflow LangGraph definition with interrupts for tier 2 and tier 3."""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from shared.checkpointer import get_checkpointer
from workflows.adaptation.state import AdaptationState
from workflows.adaptation.nodes import (
    load_adaptations,
    apply_tier1,
    propose_tier2,
    propose_tier3,
    revise_tier2,
    revise_tier3,
)


def _check_failed(state: AdaptationState) -> str:
    """Route to END early if a prior node set status='failed'."""
    return "end" if state.get("status") == "failed" else "continue"


def _route_review(state: AdaptationState) -> str:
    """Rejected → revision loop; approved continues; failed (cap hit) ends."""
    if state.get("status") == "needs_revision":
        return "revise"
    return "end" if state.get("status") == "failed" else "continue"


builder = StateGraph(AdaptationState)

builder.add_node("load_adaptations", load_adaptations)
builder.add_node("apply_tier1", apply_tier1)
builder.add_node("propose_tier2", propose_tier2)
builder.add_node("revise_tier2", revise_tier2)
builder.add_node("propose_tier3", propose_tier3)
builder.add_node("revise_tier3", revise_tier3)

builder.set_entry_point("load_adaptations")
builder.add_conditional_edges(
    "load_adaptations", _check_failed, {"end": END, "continue": "apply_tier1"}
)
builder.add_conditional_edges(
    "apply_tier1", _check_failed, {"end": END, "continue": "propose_tier2"}
)
# Each review stage loops through its own revision node on rejection (capped
# by nodes.MAX_REVISIONS, which flips status to 'failed' → end).
builder.add_conditional_edges(
    "propose_tier2",
    _route_review,
    {"end": END, "revise": "revise_tier2", "continue": "propose_tier3"},
)
builder.add_conditional_edges(
    "revise_tier2", _check_failed, {"end": END, "continue": "propose_tier2"}
)
builder.add_conditional_edges(
    "propose_tier3",
    _route_review,
    {"end": END, "revise": "revise_tier3", "continue": END},
)
builder.add_conditional_edges(
    "revise_tier3", _check_failed, {"end": END, "continue": "propose_tier3"}
)

# Checkpointer required for interrupt() in propose_tier2 and propose_tier3.
# get_checkpointer() hands out the process-wide saver (MemorySaver at import
# time); the worker's startup swaps in the durable Postgres saver.
adaptation_graph = builder.compile(checkpointer=get_checkpointer())
