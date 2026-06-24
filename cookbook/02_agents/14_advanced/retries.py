"""
Retries
=============================

Example demonstrating how to set up retries with an Agent.
"""

from agno.agent import Agent
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Web Search Agent",
    role="Search the web for information",
    tools=[WebSearchTools()],
    retries=3,  # The Agent run will be retried 3 times in case of error.
    delay_between_retries=1,  # Delay between retries in seconds.
    exponential_backoff=True,  # If True, the delay between retries is doubled each time.
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What exactly is an AI Agent?",
        stream=True,
    )
