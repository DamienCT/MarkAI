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


def test_english_rule_scopes_its_own_exception():
    """The foreign-word exception must not read as a general licence.

    The earlier wording allowed foreign phrases "as proper nouns (e.g.
    'magasin bio')". The model generalised that from names to ordinary nouns —
    goûter, rentrée, produits certifiés — and then to whole titles: five
    Naturespan items shipped in French on 2026-08-18, one of them mid-render.
    So the rule now has to say which words qualify AND name the ones that
    don't.
    """
    rule = brand_context.ENGLISH_ONLY_RULE.lower()
    # Only names, and specifically a name that identifies one particular thing.
    assert "supplier" in rule and "certification" in rule
    # Ordinary nouns are called out by example, because the abstract rule alone
    # did not hold.
    assert "rentrée" in rule and "goûter" in rule
    assert "magasin bio" in rule, "the phrase that was previously licensed"
    # And it must state that a mixed-language line is a defect, not a style.
    assert "defect" in rule


def test_video_plan_shots_prompt_carries_the_rule():
    """The shot-plan prompt used to enforce English with ad-hoc wording."""
    import inspect

    source = inspect.getsource(video_nodes.plan_shots)
    assert "_ENGLISH_ONLY_RULE" in source
