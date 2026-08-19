"""Tests for the English-everywhere output-language hard rule.

All generated copy (captions, hooks, hashtags, adaptations, briefs, calendar
items, campaigns, strategy docs, themes, shot plans / on-screen overlay lines,
research prose, personas, competitor profiles, gaps, enhanced image prompts)
must be English for every brand — brand voice controls tone, not language.
These tests guard that the rule constant reaches every copy-producing module
and stays identical, so a drift in one module can't silently weaken the
directive. The canonical text lives in shared.brand_context.
"""

import sys
import os

# Add the agents directory to the path so workflows/shared can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import shared.brand_context as brand_context
import shared.prompt_enhancer as prompt_enhancer
import workflows.content.nodes as content_nodes
import workflows.planning.nodes as planning_nodes
import workflows.product_intel.nodes as product_intel_nodes
import workflows.research.discover_competitors as discover_competitors
import workflows.research.nodes as research_nodes
import workflows.strategy.nodes as strategy_nodes
import workflows.video.nodes as video_nodes

# Every module that builds a system prompt for user-visible text.
COPY_MODULES = (
    content_nodes,
    planning_nodes,
    strategy_nodes,
    video_nodes,
    research_nodes,
    product_intel_nodes,
    discover_competitors,
    prompt_enhancer,
)


def test_english_rule_defined_in_all_copy_modules():
    for mod in COPY_MODULES:
        rule = getattr(mod, "_ENGLISH_ONLY_RULE", "")
        assert rule, f"{mod.__name__} is missing _ENGLISH_ONLY_RULE"


def test_english_rule_identical_across_modules():
    for mod in COPY_MODULES:
        assert (
            mod._ENGLISH_ONLY_RULE == brand_context.ENGLISH_ONLY_RULE
        ), f"{mod.__name__} has drifted from the canonical rule"


def test_english_rule_wording():
    rule = brand_context.ENGLISH_ONLY_RULE
    # The load-bearing clauses of the user directive.
    assert "ALWAYS English" in rule
    assert "tone, not language" in rule
    assert "proper nouns" in rule


def test_video_plan_shots_prompt_carries_the_rule():
    """The shot-plan prompt used to enforce English with ad-hoc wording."""
    import inspect

    source = inspect.getsource(video_nodes.plan_shots)
    assert "_ENGLISH_ONLY_RULE" in source
