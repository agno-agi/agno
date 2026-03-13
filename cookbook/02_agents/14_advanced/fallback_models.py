"""
Fallback Models
=============================

Example demonstrating how to configure fallback models for an Agent
using FallbackConfig.

- models: tried on any error from the primary model.
- rate_limit_models: tried specifically on rate-limit (429) errors.
- context_window_models: tried specifically on context-window-exceeded errors.

When a specific fallback list (rate_limit_models or context_window_models)
is configured and matches the error type, it takes priority over models.
"""

from agno.agent import Agent
from agno.agent.fallback_config import FallbackConfig
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Basic fallback: try a different model on any failure
# ---------------------------------------------------------------------------
agent_with_fallback = Agent(
    model=OpenAIChat(id="gpt-4o"),
    fallback_config=FallbackConfig(
        models=[Claude(id="claude-sonnet-4-20250514")],
    ),
)

# ---------------------------------------------------------------------------
# Error-specific fallbacks
# ---------------------------------------------------------------------------
agent_with_specific_fallbacks = Agent(
    model=OpenAIChat(id="gpt-4o"),
    fallback_config=FallbackConfig(
        # On rate-limit errors, try these models (in order)
        rate_limit_models=[
            OpenAIChat(id="gpt-4o-mini"),
            Claude(id="claude-sonnet-4-20250514"),
        ],
        # On context-window-exceeded errors, try a model with a larger context window
        context_window_models=[
            Claude(id="claude-sonnet-4-20250514"),
        ],
        # General fallback for all other errors
        models=[
            Claude(id="claude-sonnet-4-20250514"),
        ],
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_with_fallback.print_response("What is the meaning of life?")
