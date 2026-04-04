"""
Fallback Models — Error-Specific
==================================

Use FallbackConfig for error-specific fallback routing.

- on_error: tried on any error from the primary model.
- on_rate_limit: tried specifically on rate-limit (429) errors.
- on_context_overflow: tried on context-window-exceeded errors.

When a specific fallback list matches the error type, it takes
priority over the general on_error list.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.fallback import FallbackConfig
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Agent with error-specific fallbacks
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    fallback_config=FallbackConfig(
        # On rate-limit errors, try these models (in order)
        on_rate_limit=[
            OpenAIChat(id="gpt-4o-mini"),
            Claude(id="claude-sonnet-4-20250514"),
        ],
        # On context-window-exceeded errors, try a model with a larger window
        on_context_overflow=[
            Claude(id="claude-sonnet-4-20250514"),
        ],
        # General fallback for all other errors
        on_error=[
            Claude(id="claude-sonnet-4-20250514"),
        ],
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is the meaning of life?", stream=True)
