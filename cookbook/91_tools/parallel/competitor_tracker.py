"""
Monitor API — Competitive Intelligence
=======================================

Track competitors for product launches, news, and strategic moves.

USE CASES:
- Product launches and feature announcements
- Executive changes and key hires
- Partnership announcements
- Pricing changes
- Press coverage and sentiment

Monitors detect NEW information and alert you to changes.

Two-phase usage:
    python competitor_tracker.py            # Phase 1: create monitors
    python competitor_tracker.py check      # Phase 2: pull events (re-run later)

Wait at least one monitor cycle (default_monitor_frequency) between phases so
the monitors have time to run and detect changes.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

import sys

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# =============================================================================
# COMPETITOR TRACKING CONFIGURATION
# =============================================================================

# Hourly tracking for fast-moving markets
competitor_monitor = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_monitor=True,
    default_monitor_frequency="1h",
    default_monitor_processor="lite",
)

# Daily tracking for general competitive intel
daily_monitor = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_monitor=True,
    default_monitor_frequency="1d",
    default_monitor_processor="base",
)

# =============================================================================
# COMPETITIVE INTELLIGENCE AGENT
# =============================================================================

competitive_intel_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[competitor_monitor],
    markdown=True,
    instructions="""You track competitors and market activity.

    Tips for effective monitoring:
    - Be specific: "OpenAI product launches and API updates" not "OpenAI news"
    - Include company context: "Anthropic (Claude AI) funding and partnerships"
    - Focus on actionable signals: "competitor pricing changes" not "competitor mentions"

    Available tools:
    - create_monitor(query): Start tracking
    - list_monitors(): See active monitors
    - get_monitor_events(monitor_id): Get recent events
    - cancel_monitor(monitor_id): Stop tracking
    """,
)

# =============================================================================
# RUN
# =============================================================================
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        # Phase 2: read what monitors have detected so far
        competitive_intel_agent.print_response(
            "List my active monitors. For each one, fetch the latest events with "
            "get_monitor_events and summarize any new competitive activity. "
            "Flag anything that looks strategically significant.",
            stream=True,
        )
    else:
        # Phase 1: stand up the monitors
        competitive_intel_agent.print_response(
            "Create monitors to track OpenAI and Anthropic for product launches, "
            "API updates, and major announcements.",
            stream=True,
        )
        print(
            "\nMonitors created. Wait at least one cycle "
            "(see default_monitor_frequency), then run:\n"
            "    python competitor_tracker.py check"
        )
