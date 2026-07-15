"""
Slack Team HITL — User Input Required (Simple)
===============================================

Simple port of AgentOS human_in_the_loop/team/user_input_required.py.

A team member's tool requires additional user input before it can execute.
The run pauses and Slack shows input fields. The user fills them and submits.

Try in Slack:
  @bot plan a vacation for me

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.team import Team
from agno.tools import tool

db = SqliteDb(
    db_file="tmp/team_hitl_user_input_simple.db",
    session_table="team_sessions",
    approvals_table="approvals",
)


@tool(requires_user_input=True, user_input_fields=["destination", "budget"])
def plan_trip(destination: str = "", budget: str = "") -> str:
    """Plan a trip based on user preferences."""
    return (
        f"Trip planned to {destination} with a budget of {budget}. "
        "Includes flights, hotel, and activities."
    )


travel_agent = Agent(
    name="TravelAgent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[plan_trip],
    instructions=[
        "You MUST call the plan_trip tool immediately with whatever information you have.",
        "Do NOT ask clarifying questions - the tool will pause and request any missing "
        "information from the user.",
    ],
    db=db,
    telemetry=False,
)

team = Team(
    id="travel-team-hitl-simple",
    name="TravelTeam",
    model=OpenAIResponses(id="gpt-5.4"),
    members=[travel_agent],
    instructions=[
        "Delegate all travel and vacation requests to the TravelAgent immediately."
    ],
    db=db,
    add_history_to_context=True,
    telemetry=False,
)

agent_os = AgentOS(
    description="Slack Team HITL — user input (simple)",
    teams=[team],
    db=db,
    interfaces=[
        Slack(
            team=team,
            reply_to_mentions_only=True,
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="team_hitl_user_input_simple:app", reload=True)
