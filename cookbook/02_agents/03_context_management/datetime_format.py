"""
Custom Datetime Format
======================

Customize the datetime format injected into the agent's system context.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    add_datetime_to_context=True,
    datetime_format="%Y-%m-%dT%H:%M:%SZ",  # ISO 8601 format in UTC (e.g., 2026-03-09T14:30:00Z)
    timezone_identifier="US/Eastern",
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is the current time and timezone?", stream=True)
