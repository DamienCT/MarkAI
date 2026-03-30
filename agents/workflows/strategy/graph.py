"""Strategy workflow LangGraph definition with human-in-the-loop interrupt."""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from workflows.strategy.state import StrategyState
from workflows.strategy.nodes import (
    load_research,
    generate_positioning,
    define_pillars,
    define_audiences,
    plan_cadence,
    generate_themes,
    human_review,
)


def _check_failed(state: StrategyState) -> str:
    """Route to END early if a prior node set status='failed'."""
    return "end" if state.get("status") == "failed" else "continue"


builder = StateGraph(StrategyState)

builder.add_node("load_research", load_research)
builder.add_node("generate_positioning", generate_positioning)
builder.add_node("define_pillars", define_pillars)
builder.add_node("define_audiences", define_audiences)
builder.add_node("plan_cadence", plan_cadence)
builder.add_node("generate_themes", generate_themes)
builder.add_node("human_review", human_review)

builder.set_entry_point("load_research")
builder.add_conditional_edges("load_research", _check_failed, {"end": END, "continue": "generate_positioning"})
builder.add_conditional_edges("generate_positioning", _check_failed, {"end": END, "continue": "define_pillars"})
builder.add_conditional_edges("define_pillars", _check_failed, {"end": END, "continue": "define_audiences"})
builder.add_conditional_edges("define_audiences", _check_failed, {"end": END, "continue": "plan_cadence"})
builder.add_conditional_edges("plan_cadence", _check_failed, {"end": END, "continue": "generate_themes"})
builder.add_conditional_edges("generate_themes", _check_failed, {"end": END, "continue": "human_review"})
builder.add_conditional_edges("human_review", _check_failed, {"end": END, "continue": END})

# Compile without checkpointer — these are one-shot linear workflows
strategy_graph = builder.compile()
