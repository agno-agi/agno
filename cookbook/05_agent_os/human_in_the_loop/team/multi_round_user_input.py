"""AgentOS HITL: Multi-Round User Input

AgentOS equivalent of cookbook/03_teams/20_human_in_the_loop/multi_round_user_input.py

A team member has multiple tools that require user input. The run pauses
for each tool, creating a chained HITL flow where the member pauses multiple
times during a single team execution.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/human_in_the_loop/team/multi_round_user_input.py
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
    session_table="hitl_multi_round_sessions",
)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(requires_user_input=True, user_input_fields=["name"])
def collect_name(name: str = "") -> str:
    """Collect the user's name."""
    return f"User's name is: {name}"


@tool(requires_user_input=True, user_input_fields=["cuisine", "budget"])
def collect_preferences(cuisine: str = "", budget: str = "") -> str:
    """Collect user's dining preferences."""
    return f"User prefers {cuisine} cuisine with a {budget} budget."


# ---------------------------------------------------------------------------
# Create members
# ---------------------------------------------------------------------------

survey_agent = Agent(
    name="SurveyAgent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[collect_name, collect_preferences],
    instructions=(
        "You MUST call collect_name first, then collect_preferences. "
        "Do NOT ask clarifying questions - the tools will pause and request input."
    ),
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create team
# ---------------------------------------------------------------------------

team = Team(
    id="hitl-multi-round-team",
    name="RestaurantTeam",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[survey_agent],
    instructions="Delegate all restaurant requests to the SurveyAgent immediately.",
    db=db,
    telemetry=False,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="hitl-multi-round-user-input",
    description="AgentOS HITL: chained user input across multiple tool calls",
    agents=[survey_agent],
    teams=[team],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="multi_round_user_input:app", port=7777, reload=True)
