"""
Multi-Modal Recipe Agent
========================

A multi-modal RAG agent that retrieves recipes from a knowledge base
and generates step-by-step visual instruction manuals using image generation.

Example:
    from recipe_agent import recipe_agent, get_visual_recipe

    # Get a recipe with visual guide
    result = get_visual_recipe("Thai green curry")
"""

from recipe_agent.agent import get_visual_recipe, recipe_agent

__all__ = [
    "recipe_agent",
    "get_visual_recipe",
]
