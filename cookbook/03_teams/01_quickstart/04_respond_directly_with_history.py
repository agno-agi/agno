"""
Respond Directly With History
=============================

Demonstrates direct member responses with team history persisted in SQLite.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team, TeamMode


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
def get_weather(city: str) -> str:
    return f"The weather in {city} is sunny."


weather_agent = Agent(
    name="Weather Agent",
    role="You are a weather agent that can answer questions about the weather.",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[get_weather],
)


def get_news(topic: str) -> str:
    return f"The news about {topic} is that it is going well!"


news_agent = Agent(
    name="News Agent",
    role="You are a news agent that can answer questions about the news.",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[get_news],
)


def get_activities(city: str) -> str:
    return f"The activities in {city} are that it is going well!"


activities_agent = Agent(
    name="Activities Agent",
    role="You are a activities agent that can answer questions about the activities.",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[get_activities],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
geo_search_team = Team(
    name="Geo Search Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    mode=TeamMode.route,
    members=[
        weather_agent,
        news_agent,
        activities_agent,
    ],
    instructions="You are a geo search agent that can answer questions about the weather, news and activities in a city.",
    use_instruction_tags=True,
    db=SqliteDb(
        db_file="tmp/geo_search_team.db"
    ),  # Add a database to store the conversation history
    add_history_to_context=True,  # Ensure that the team leader knows about previous requests
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    geo_search_team.print_response(
        "I am doing research on Tokyo. What is the weather like there?", stream=True
    )

    geo_search_team.print_response(
        "Is there any current news about that city?", stream=True
    )

    geo_search_team.print_response("What are the activities in that city?", stream=True)
