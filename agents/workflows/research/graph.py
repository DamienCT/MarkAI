"""Research workflow LangGraph definition."""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from workflows.research.state import ResearchState
from workflows.research.nodes import (
    crawl_website,
    analyze_social,
    analyze_competitors,
    identify_gaps,
    build_personas,
    store_results,
)


def _check_failed(state: ResearchState) -> str:
    """Route to END early if a prior node set status='failed'."""
    return "end" if state.get("status") == "failed" else "continue"


builder = StateGraph(ResearchState)

builder.add_node("crawl_website", crawl_website)
builder.add_node("analyze_social", analyze_social)
builder.add_node("analyze_competitors", analyze_competitors)
builder.add_node("identify_gaps", identify_gaps)
builder.add_node("build_personas", build_personas)
builder.add_node("store_results", store_results)

builder.set_entry_point("crawl_website")
builder.add_conditional_edges("crawl_website", _check_failed, {"end": END, "continue": "analyze_social"})
builder.add_conditional_edges("analyze_social", _check_failed, {"end": END, "continue": "analyze_competitors"})
builder.add_conditional_edges("analyze_competitors", _check_failed, {"end": END, "continue": "identify_gaps"})
builder.add_conditional_edges("identify_gaps", _check_failed, {"end": END, "continue": "build_personas"})
builder.add_conditional_edges("build_personas", _check_failed, {"end": END, "continue": "store_results"})
builder.add_conditional_edges("store_results", _check_failed, {"end": END, "continue": END})

research_graph = builder.compile()
