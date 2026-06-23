"""AgentOS HITL: User Input Required

AgentOS equivalent of cookbook/03_teams/20_human_in_the_loop/user_input_required.py

A team member's tool requires additional user input before it can execute.
The run pauses and the API response includes the input schema. The client
collects the values and sends them back via continue_run.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/hitl/user_input_required.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

db = SqliteDb(
    db_file="tmp/agent_os_hitl.db",
    session_table="hitl_user_input_sessions",
)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(requires_user_input=True, user_input_fields=["destination", "budget"])
def plan_trip(destination: str = "", budget: str = "") -> str:
    """Plan a trip based on user preferences."""
    return (
        f"Trip planned to {destination} with a budget of {budget}. "
        "Includes flights, hotel, and activities."
    )


# ---------------------------------------------------------------------------
# Create members
# ---------------------------------------------------------------------------

travel_agent = Agent(
    name="TravelAgent",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[plan_trip],
    instructions=(
        "You MUST call the plan_trip tool immediately with whatever information you have. "
        "Do NOT ask clarifying questions - the tool will pause and request any missing "
        "information from the user."
    ),
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create team
# ---------------------------------------------------------------------------

team = Team(
    id="hitl-user-input-team",
    name="TravelTeam",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[travel_agent],
    instructions="Delegate all travel and vacation requests to the TravelAgent immediately.",
    db=db,
    telemetry=False,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="hitl-user-input-required",
    description="AgentOS HITL: collecting user input before tool execution",
    agents=[travel_agent],
    teams=[team],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="user_input_required:app", port=7777, reload=True)
