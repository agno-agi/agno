"""
Competitive Intelligence Monitor - Track Changes Over Time
==========================================================

The Monitor API watches a topic on a schedule and records events when
something changes. This turns "research once" into "stay informed".

Here an agent sets up a monitor, lists what is active, and reports on any
events the monitor has detected - the core loop of a standing intelligence
desk.

Note: monitors run server-side on their own schedule, so a freshly created
monitor will not have events yet. Re-run later to see detected changes.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Tools - Monitor API
# ---------------------------------------------------------------------------
monitor_tools = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_monitor=True,
    default_monitor_frequency="1d",
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
intel_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[monitor_tools],
    markdown=True,
    instructions=[
        "You run a competitive-intelligence desk.",
        "Use create_monitor to start tracking a topic, list_monitors to see "
        "what is active, and get_monitor_events to report detected changes.",
        "Summarize events clearly and cite the sources behind each change.",
    ],
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    intel_agent.print_response(
        "Start monitoring new AI model and product launches by frontier labs, "
        "then show me what is currently being tracked.",
        stream=True,
    )
