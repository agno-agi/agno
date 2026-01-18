"""
This example shows how a session can be shared between a team and an agent.

This is useful if you have a team that is more scalable (since it manages the size of the context more efficiently), but want to sometimes use a single agent for speed.

A single session is shared across all the runs below.
"""

import uuid

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team

db = InMemoryDb()


def get_weather(city: str) -> str:
    """Get the weather for the given city."""
    return f"The weather in {city} is sunny."


def get_activities(city: str) -> str:
    """Get the activities for the given city."""
    return f"The activities in {city} are swimming and hiking."


# Create a single agent that is faster, but has a larger context
agent = Agent(
    name="City Planner Agent",
    id="city-planner-agent-id",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[get_weather, get_activities],
    add_history_to_context=True,
)


# Create a team for coordination
team = Team(
    name="City Planner Team",
    id="city-planner-team-id",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    members=[
        Agent(
            name="Weather Agent",
            id="weather-agent-id",
            model=OpenAIChat(id="gpt-4o"),
            tools=[get_weather],
        ),
        Agent(
            name="Activities Agent",
            id="activities-agent-id",
            model=OpenAIChat(id="gpt-4o"),
            tools=[get_activities],
        ),
    ],
    add_history_to_context=True,
)


session_id = str(uuid.uuid4())

# Ask first question to the agent
agent.print_response("What is the weather like in Tokyo?", session_id=session_id)

# Follow up question to the team
team.print_response("What activities can I do there?", session_id=session_id)

# Follow up question to the agent
agent.print_response(
    "What else can you tell me about the city? Should I visit?", session_id=session_id
)
