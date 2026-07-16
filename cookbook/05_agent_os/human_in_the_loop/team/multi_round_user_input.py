"""AgentOS HITL: Multi-Round User Input

AgentOS equivalent of cookbook/03_teams/20_human_in_the_loop/multi_round_user_input.py

Demonstrates a member agent that pauses multiple times for user input during
a single team execution. This is the scenario from issue #8925.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/human_in_the_loop/team/multi_round_user_input.py

Then use the AgentOS UI at http://localhost:7777 to:
1. Start a team run with "Help me find a restaurant"
2. Provide your name when prompted (Round 1)
3. Provide cuisine and budget when prompted (Round 2)
4. See the final recommendation
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
    db_file="tmp/agent_os_multi_hitl.db",
    session_table="multi_hitl_sessions",
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
    instructions=[
        "You help users find restaurant recommendations.",
        "You MUST collect information in this order:",
        "1. First, call collect_name to get the user's name",
        "2. Then, call collect_preferences to get their cuisine and budget preferences",
        "3. Finally, provide a personalized recommendation using both pieces of info",
    ],
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create team
# ---------------------------------------------------------------------------

team = Team(
    id="multi-round-hitl-team",
    name="RestaurantTeam",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[survey_agent],
    instructions=[
        "You are a coordinator. You NEVER answer directly.",
        "ALWAYS delegate to SurveyAgent for any restaurant or dining request.",
        "Do not provide your own suggestions - only delegate.",
    ],
    db=db,
    telemetry=False,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="multi-round-hitl",
    description="AgentOS HITL: Multi-round user input (issue #8925 scenario)",
    agents=[survey_agent],
    teams=[team],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="multi_round_user_input:app", port=7777, reload=True)
