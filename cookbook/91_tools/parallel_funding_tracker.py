"""
Parallel Funding Tracker
=============================

Track topics over time and get notified of changes.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: Create and manage monitors
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools(enable_monitor=True)],
    markdown=True,
)

# Example 2: Monitor with hourly frequency
frequent_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_monitor=True,
            default_monitor_frequency="1h",
        )
    ],
    markdown=True,
)

# Example 3: Monitor with thorough analysis
thorough_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_monitor=True,
            default_monitor_processor="base",
            default_monitor_frequency="1d",
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Create a monitor to track 'AI startup funding announcements'. "
        "Then list all my active monitors.",
        stream=True,
    )
