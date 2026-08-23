"""
Use Member Tool Results as Fallback
===================================

Demonstrates suppressing raw tool results at a Team's non-streaming delegation
boundary when a member returns no usable text. With fallback disabled, the
leader receives a generic no-response diagnostic instead. Stored tool records
remain unchanged.

The setting is evaluated per Team. It does not affect streaming, task mode,
shared member-interaction context, or a nested Team's internal delegations.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools import tool


@tool(stop_after_tool_call=True, show_result=False)
def lookup_weather(city: str) -> str:
    """Return a sample raw weather-provider payload."""
    return f'{{"city": "{city}", "temperature_c": 21, "provider": "example-weather"}}'


# ---------------------------------------------------------------------------
# Create Member
# ---------------------------------------------------------------------------
weather_agent = Agent(
    name="Weather Agent",
    role="Look up weather data",
    tools=[lookup_weather],
    instructions=dedent("""
        Always call lookup_weather for the requested city.
        Do not answer from memory.
    """).strip(),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
weather_team = Team(
    name="Weather Team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[weather_agent],
    instructions=dedent("""
        Delegate weather lookups to the Weather Agent.
        If the member returns no usable response, say that weather data could not
        be retrieved. Do not reproduce raw provider payloads.
    """).strip(),
    # Return a generic no-response diagnostic instead of exposing a tool-only
    # member's raw provider payload to this Team's leader.
    use_member_tool_results_as_fallback=False,
    markdown=True,
    show_members_responses=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The fallback policy is applied to non-streaming member delegation.
    weather_team.print_response("What is the weather in London?", stream=False)
