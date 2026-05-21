"""
Settings
========

Shared runtime objects. Keep model ids in one place.
"""

from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses


def default_model() -> OpenAIResponses:
    """Fresh OpenAI model — avoids shared-state footguns."""
    return OpenAIResponses(id="gpt-5.5")


def sub_agent_model() -> OpenAIResponses:
    """Smaller OpenAI model for context-provider sub-agents (tool-routing work)."""
    return OpenAIResponses(id="gpt-5.4-mini")


def anthropic_model() -> Claude:
    """Anthropic Claude — used by the Swarm team to diversify across providers."""
    return Claude(id="claude-opus-4-7")
