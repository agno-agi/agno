"""
Serving an AgentOS with an Auto-Populated Registry
==================================================

This is the same idea as ``auto_populate_registry.py``, but served as an app so
you can see the discovered components over the API.

No registry is passed to AgentOS. After the app starts, the components used by
the team members are available at:

    GET /registry?resource_type=model
    GET /registry?resource_type=tool
    GET /registry?resource_type=db

A registry passed explicitly is still honoured: anything you declare is kept,
and the discovered components are merged in (deduplicated by id/name).
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team


# ---------------------------------------------------------------------------
# A simple custom tool
# ---------------------------------------------------------------------------
def get_weather(city: str) -> str:
    """Return the weather for a city."""
    return "sunny"


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/auto_registry_os.db", id="auto-registry-os-db")

researcher = Agent(
    id="researcher",
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[get_weather],
    db=db,
)

writer = Agent(
    id="writer",
    name="Writer",
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

content_team = Team(
    id="content-team",
    name="Content Team",
    members=[researcher, writer],
)

# ---------------------------------------------------------------------------
# Create AgentOS WITHOUT an explicit registry; components are discovered for you
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="auto-registry-os",
    teams=[content_team],
    db=db,
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS App
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="auto_populate_registry_os:app", reload=True)
