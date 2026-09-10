"""
FXMacroData Tools - Macroeconomic, FX and Central-Bank Data

FXMacroData aggregates official publishers - statistical agencies, central banks
and exchanges - across 18 currencies behind a single contract, and stamps every
observation with the instant it was published. That publication timestamp is
what lets an agent reason about what was knowable at a point in time, instead of
only describing the present.

USD needs no API key, so the first example below runs as-is. A key widens the
history window and unlocks the other seventeen currencies plus FX rates, rate
differentials, COT positioning and commodities:

    export FXMACRODATA_API_KEY=...
"""

from agno.agent import Agent
from agno.tools.fxmacrodata import FXMacroDataTools

# ---------------------------------------------------------------------------
# Example 1: US macro briefing - no API key required
# ---------------------------------------------------------------------------

briefing_agent = Agent(
    tools=[FXMacroDataTools()],
    description="You are a macroeconomic analyst covering the United States.",
    instructions=[
        "Call search_indicators first if you do not know the indicator slug.",
        "get_latest_macro_snapshot returns every indicator in one call - prefer it "
        "over fetching series one at a time.",
        "Always report the announcement timestamp alongside a value, so the reader "
        "knows when the figure became public.",
        "Format your response using markdown and use tables to display data.",
    ],
    markdown=True,
)

briefing_agent.print_response(
    "Summarise the current state of the US economy: inflation, unemployment and "
    "the policy rate, with the date each figure was published.",
    stream=True,
)

# ---------------------------------------------------------------------------
# Example 2: Event risk ahead of a trading session - no API key required
# ---------------------------------------------------------------------------

calendar_agent = Agent(
    tools=[
        FXMacroDataTools(include_tools=["get_release_calendar", "get_market_sessions"])
    ],
    description="You flag scheduled macro event risk before a trading session.",
    instructions=[
        "Use get_release_calendar to find what is scheduled and when.",
        "Use get_market_sessions to say which FX sessions are open.",
        "Call out top-tier releases specifically - they are the ones that move price.",
    ],
    markdown=True,
)

calendar_agent.print_response(
    "What US macro releases are scheduled next, and which FX sessions are open now?",
    stream=True,
)

# ---------------------------------------------------------------------------
# Example 3: Carry and positioning for a pair - requires an API key
# ---------------------------------------------------------------------------

pair_agent = Agent(
    tools=[FXMacroDataTools()],
    description="You analyse currency pairs using rate differentials and positioning.",
    instructions=[
        "Use get_rate_differential for carry and get_cot_positioning for crowding.",
        "State plainly when a reading is stale or unavailable rather than guessing.",
    ],
    markdown=True,
)

pair_agent.print_response(
    "How does USD/JPY look on carry and positioning right now?",
    stream=True,
)
