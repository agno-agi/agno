"""
Tool Choice
===========

Demonstrates using `tool_choice` to force the Team to execute a specific tool.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools import tool


@tool()
def get_city_timezone(city: str) -> str:
    """Return a known timezone identifier for a supported city."""
    city_to_timezone = {
        "new york": "America/New_York",
        "london": "Europe/London",
        "tokyo": "Asia/Tokyo",
        "sydney": "Australia/Sydney",
    }
    return city_to_timezone.get(city.lower(), "Unsupported city for this example")


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
agent = Agent(
    name="Operations Analyst",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "Use the tool output to answer timezone questions.",
        "Do not invent values that are not in the tool output.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
teams_timezone = Team(
    name="Tool Choice Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[agent],
    tools=[get_city_timezone],
    tool_choice={
        "type": "function",
        "function": {"name": "get_city_timezone"},
    },
    instructions=[
        "You are a logistics assistant.",
        "For every request, resolve the city timezone using the available tool.",
        "Return the timezone identifier only in one sentence.",
    ],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    teams_timezone.print_response("What is the timezone for London?", stream=True)
