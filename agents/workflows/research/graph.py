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

builder = StateGraph(ResearchState)

builder.add_node("crawl_website", crawl_website)
builder.add_node("analyze_social", analyze_social)
builder.add_node("analyze_competitors", analyze_competitors)
builder.add_node("identify_gaps", identify_gaps)
builder.add_node("build_personas", build_personas)
builder.add_node("store_results", store_results)

builder.set_entry_point("crawl_website")
builder.add_edge("crawl_website", "analyze_social")
builder.add_edge("analyze_social", "analyze_competitors")
builder.add_edge("analyze_competitors", "identify_gaps")
builder.add_edge("identify_gaps", "build_personas")
builder.add_edge("build_personas", "store_results")
builder.add_edge("store_results", END)

research_graph = builder.compile()
