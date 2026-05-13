"""
Slack Team HITL — Member Agent Confirmation
============================================

Ported from: cookbook/03_teams/20_human_in_the_loop/confirmation_required.py

Member agent (WeatherAgent) has an HITL tool. When the member calls
`@tool(requires_confirmation=True)`, the pause propagates to the team
and Slack shows Approve / Deny buttons.

Try in Slack:
  @bot what is the weather in Tokyo?

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.team import Team
from agno.tools import tool


@tool(requires_confirmation=True)
def get_the_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"It is currently 70 degrees and cloudy in {city}"


db = SqliteDb(
    db_file="tmp/team_hitl_confirmation.db",
    session_table="team_sessions",
)

weather_agent = Agent(
    name="WeatherAgent",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[get_the_weather],
    db=db,
    telemetry=False,
)

weather_team = Team(
    id="weather-team-hitl",
    name="WeatherTeam",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[weather_agent],
    db=db,
    add_history_to_context=True,
    telemetry=False,
)

agent_os = AgentOS(
    description="Slack Team HITL — member agent confirmation",
    teams=[weather_team],
    db=db,
    interfaces=[
        Slack(
            team=weather_team,
            reply_to_mentions_only=True,
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="team_hitl_confirmation:app", reload=True)
