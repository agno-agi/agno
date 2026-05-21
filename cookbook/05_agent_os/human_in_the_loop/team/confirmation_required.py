"""AgentOS HITL: Confirmation Required

AgentOS equivalent of cookbook/03_teams/20_human_in_the_loop/confirmation_required.py

A team member's tool requires human confirmation before execution.
When the tool is called the run pauses and the API response contains the
requirement. The client confirms or rejects, then calls continue_run.

AgentOS handles streaming and async automatically, so this single server
covers the sync, async, streaming, and async-streaming variants.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/hitl/confirmation_required.py
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
    session_table="hitl_confirmation_sessions",
)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def get_the_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"It is currently 70 degrees and cloudy in {city}"


# ---------------------------------------------------------------------------
# Create members
# ---------------------------------------------------------------------------

weather_agent = Agent(
    name="WeatherAgent",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[get_the_weather],
    instructions=(
        "You MUST call the get_the_weather tool to answer any weather question. "
        "Do NOT answer from your own knowledge."
    ),
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create team
# ---------------------------------------------------------------------------

team = Team(
    id="hitl-confirmation-team",
    name="WeatherTeam",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[weather_agent],
    instructions="Delegate all weather questions to the WeatherAgent immediately.",
    db=db,
    telemetry=False,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="hitl-confirmation-required",
    description="AgentOS HITL: member tool requiring confirmation before execution",
    agents=[weather_agent],
    teams=[team],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="confirmation_required:app", port=7777, reload=True)
