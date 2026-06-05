"""
Settings
========

Shared runtime objects. Keep model ids in one place.
"""

from agno.models.google import Gemini
from agno.models.openai import OpenAIResponses


def default_model() -> OpenAIResponses:
    """Top-level agent model."""
    return OpenAIResponses(id="gpt-5.5")


def sub_agent_model() -> OpenAIResponses:
    """Model for the context-provider sub-agents (read/write tool-routing work)."""
    return OpenAIResponses(id="gpt-5.5")


def gemini_flash() -> Gemini:
    """Gemini 3.5 Flash — swap in per agent for heavier multimodal (audio, video)
    when its quota allows."""
    return Gemini(id="gemini-3.5-flash")
