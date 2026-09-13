"""
Monitor API — Investment Tracking
=================================

Track funding announcements, M&A activity, and market movements.

USE CASES:
- Startup funding rounds (Series A, B, C, etc.)
- M&A announcements and acquisitions
- IPO filings and market debuts
- Earnings releases and guidance changes

Monitors run on a schedule and detect NEW information.
Each event includes confidence scores and source citations.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# =============================================================================
# INVESTMENT MONITOR CONFIGURATION
# =============================================================================

# Daily funding tracker — catches most announcements
funding_monitor = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_monitor=True,
    default_monitor_frequency="1d",
    default_monitor_processor="base",
)

# Hourly M&A tracker — for time-sensitive deals
ma_monitor = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_monitor=True,
    default_monitor_frequency="1h",
    default_monitor_processor="lite",
)

# =============================================================================
# INVESTMENT TRACKING AGENT
# =============================================================================

investment_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[funding_monitor],
    markdown=True,
    instructions="""You track investment activity. Available actions:
    - create_monitor(query): Start tracking a topic
    - list_monitors(): See all active monitors
    - get_monitor_events(monitor_id): Get detected changes
    - get_monitor(monitor_id): Get monitor details
    - cancel_monitor(monitor_id): Stop tracking

    Use natural language queries like:
    "AI startup Series A and B funding announcements"
    NOT keyword searches like "AI AND funding AND Series"
    """,
)

# =============================================================================
# RUN
# =============================================================================
if __name__ == "__main__":
    # Create a funding monitor
    investment_agent.print_response(
        "Create a monitor to track AI startup funding announcements. "
        "Focus on Series A, B, and C rounds.",
        stream=True,
    )
