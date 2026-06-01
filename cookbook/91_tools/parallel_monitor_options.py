"""
Parallel Monitor API Options
============================

Comprehensive examples of all Monitor API configuration options.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Monitor Frequency
# ---------------------------------------------------------------------------
# How often the monitor checks for changes:
#
# - "1h"  : Every hour (minimum)
# - "6h"  : Every 6 hours
# - "12h" : Every 12 hours
# - "1d"  : Daily (default)
# - "1w"  : Weekly
# - "30d" : Monthly (maximum)
# ---------------------------------------------------------------------------

# Example 1: Hourly monitoring for fast-moving topics
hourly_tools = ParallelTools(
    enable_monitor=True,
    default_monitor_frequency="1h",
)

# Example 2: Daily monitoring (default)
daily_tools = ParallelTools(
    enable_monitor=True,
    default_monitor_frequency="1d",
)

# Example 3: Weekly monitoring for slower topics
weekly_tools = ParallelTools(
    enable_monitor=True,
    default_monitor_frequency="1w",
)

# ---------------------------------------------------------------------------
# Monitor Processor
# ---------------------------------------------------------------------------
# Monitor API only supports "lite" and "base" processors (not "pro"):
#
# - "lite" : Faster, cheaper, basic change detection (default)
# - "base" : More thorough analysis of changes
# ---------------------------------------------------------------------------

# Example 4: Lite processor for cost-effective monitoring
lite_monitor_tools = ParallelTools(
    enable_monitor=True,
    default_monitor_processor="lite",
)

# Example 5: Base processor for detailed change analysis
base_monitor_tools = ParallelTools(
    enable_monitor=True,
    default_monitor_processor="base",
)

# ---------------------------------------------------------------------------
# Output Schema for Monitor Events
# ---------------------------------------------------------------------------
# Same schema options as Task API apply to monitor events:
#
# - {"type": "auto"} - Parallel determines structure
# - {"type": "json", "json_schema": {...}} - Strict JSON structure
# - "string description" - Natural language description
# ---------------------------------------------------------------------------

# Example 6: Auto schema (default)
auto_monitor_tools = ParallelTools(
    enable_monitor=True,
    default_output_schema={"type": "auto"},
)

# Example 7: JSON schema for structured event data
structured_monitor_tools = ParallelTools(
    enable_monitor=True,
    default_output_schema={
        "type": "json",
        "json_schema": {
            "type": "object",
            "properties": {
                "event_summary": {"type": "string"},
                "company": {"type": "string"},
                "amount": {"type": "string"},
                "investors": {"type": "array", "items": {"type": "string"}},
                "date": {"type": "string"},
            },
        },
    },
)

# Example 8: String schema
string_monitor_tools = ParallelTools(
    enable_monitor=True,
    default_output_schema="Return the company name, funding amount, investor names, and announcement date",
)

# ---------------------------------------------------------------------------
# Combined Configurations
# ---------------------------------------------------------------------------

# Example 9: High-frequency monitoring for breaking news
breaking_news_tools = ParallelTools(
    enable_monitor=True,
    default_monitor_frequency="1h",
    default_monitor_processor="lite",
)

# Example 10: Thorough weekly analysis
weekly_analysis_tools = ParallelTools(
    enable_monitor=True,
    default_monitor_frequency="1w",
    default_monitor_processor="base",
    default_output_schema={
        "type": "json",
        "json_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "key_developments": {"type": "array", "items": {"type": "string"}},
                "market_impact": {"type": "string"},
            },
        },
    },
)

# ---------------------------------------------------------------------------
# Create Agents with Different Configurations
# ---------------------------------------------------------------------------

# Breaking news monitor
news_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[breaking_news_tools],
    instructions="""You are a news monitoring assistant.
    Use create_monitor to track topics, get_monitor_events to check for updates,
    and list_monitors to see active monitors.""",
    markdown=True,
)

# Weekly analysis monitor
analysis_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[weekly_analysis_tools],
    instructions="""You are a market analysis assistant.
    Use create_monitor for weekly tracking, get_monitor to check status,
    update_monitor to change settings, and cancel_monitor when done.""",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Examples
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Example 1: Create a monitor for AI funding news")
    print("-" * 50)
    news_agent.print_response(
        "Create a monitor to track AI startup funding announcements",
        stream=True,
    )

    print("\n\nExample 2: List active monitors")
    print("-" * 50)
    news_agent.print_response(
        "Show me all my active monitors",
        stream=True,
    )
