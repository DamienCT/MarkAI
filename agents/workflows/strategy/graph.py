"""Strategy workflow LangGraph definition with human-in-the-loop interrupt."""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from shared.checkpointer import get_checkpointer
from workflows.strategy.state import StrategyState
from workflows.strategy.nodes import (
    load_research,
    generate_positioning,
    define_pillars,
    define_audiences,
    plan_cadence,
    generate_themes,
    human_review,
    revise_strategy,
)


def _check_failed(state: StrategyState) -> str:
    """Route to END early if a prior node set status='failed'."""
    return "end" if state.get("status") == "failed" else "continue"


def _route_after_review(state: StrategyState) -> str:
    """Approved and failed both end; a rejection goes through revision."""
    return "revise" if state.get("status") == "needs_revision" else "end"


builder = StateGraph(StrategyState)

builder.add_node("load_research", load_research)
builder.add_node("generate_positioning", generate_positioning)
builder.add_node("define_pillars", define_pillars)
builder.add_node("define_audiences", define_audiences)
builder.add_node("plan_cadence", plan_cadence)
builder.add_node("generate_themes", generate_themes)
builder.add_node("human_review", human_review)
builder.add_node("revise_strategy", revise_strategy)

builder.set_entry_point("load_research")
builder.add_conditional_edges(
    "load_research", _check_failed, {"end": END, "continue": "generate_positioning"}
)
builder.add_conditional_edges(
    "generate_positioning", _check_failed, {"end": END, "continue": "define_pillars"}
)
builder.add_conditional_edges(
    "define_pillars", _check_failed, {"end": END, "continue": "define_audiences"}
)
builder.add_conditional_edges(
    "define_audiences", _check_failed, {"end": END, "continue": "plan_cadence"}
)
builder.add_conditional_edges(
    "plan_cadence", _check_failed, {"end": END, "continue": "generate_themes"}
)
builder.add_conditional_edges(
    "generate_themes", _check_failed, {"end": END, "continue": "human_review"}
)
# approved → END (stored in the node); rejected → revise → re-review, capped
# by nodes.MAX_REVISIONS (the cap turns status to 'failed', which ends here).
builder.add_conditional_edges(
    "human_review", _route_after_review, {"end": END, "revise": "revise_strategy"}
)
builder.add_conditional_edges(
    "revise_strategy", _check_failed, {"end": END, "continue": "human_review"}
)

# Checkpointer required for interrupt() in human_review. get_checkpointer()
# hands out the process-wide saver (MemorySaver at import time); the worker's
# startup swaps in the durable Postgres saver via shared.checkpointer.
strategy_graph = builder.compile(checkpointer=get_checkpointer())
