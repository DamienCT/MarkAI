"""Adaptation workflow LangGraph definition with interrupts for tier 2 and tier 3."""

from __future__ import annotations

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from workflows.adaptation.state import AdaptationState
from workflows.adaptation.nodes import (
    load_adaptations,
    apply_tier1,
    propose_tier2,
    propose_tier3,
)

builder = StateGraph(AdaptationState)

builder.add_node("load_adaptations", load_adaptations)
builder.add_node("apply_tier1", apply_tier1)
builder.add_node("propose_tier2", propose_tier2)
builder.add_node("propose_tier3", propose_tier3)

builder.set_entry_point("load_adaptations")
builder.add_edge("load_adaptations", "apply_tier1")
builder.add_edge("apply_tier1", "propose_tier2")
builder.add_edge("propose_tier2", "propose_tier3")
builder.add_edge("propose_tier3", END)

# Compile with checkpointer to support interrupt/resume at tier2 and tier3
adaptation_graph = builder.compile(checkpointer=MemorySaver())
