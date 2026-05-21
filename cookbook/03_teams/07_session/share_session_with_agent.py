"""
Share Session With Agent
========================

Demonstrates sharing one session across team and single-agent interactions.
"""

import uuid

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = InMemoryDb()


def get_weather(city: str) -> str:
    """Get the weather for the given city."""
    return f"The weather in {city} is sunny."


def get_activities(city: str) -> str:
    """Get the activities for the given city."""
    return f"The activities in {city} are swimming and hiking."


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
agent = Agent(
    name="City Planner Agent",
    id="city-planner-agent-id",
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    tools=[get_weather, get_activities],
    add_history_to_context=True,
)

weather_agent = Agent(
    name="Weather Agent",
    id="weather-agent-id",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[get_weather],
)

activities_agent = Agent(
    name="Activities Agent",
    id="activities-agent-id",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[get_activities],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="City Planner Team",
    id="city-planner-team-id",
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    members=[weather_agent, activities_agent],
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = str(uuid.uuid4())

    agent.print_response("What is the weather like in Tokyo?", session_id=session_id)
    team.print_response("What activities can I do there?", session_id=session_id)
    agent.print_response(
        "What else can you tell me about the city? Should I visit?",
        session_id=session_id,
    )
