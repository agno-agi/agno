"""
Auto-Populating the Registry from Agents, Teams, and Workflows
==============================================================

AgentOS automatically discovers the components (models, tools, databases, and
vector databases) used anywhere inside its agents, teams, and workflows and adds
them to the registry. You do not need to declare these components a second time
when constructing the Registry.

This example builds a team and a workflow, hands them to AgentOS WITHOUT passing
an explicit registry, and then inspects the auto-populated registry. No model
calls are made, so this runs offline without any API key.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.workflow import Step, Workflow


# ---------------------------------------------------------------------------
# A simple custom tool
# ---------------------------------------------------------------------------
def get_weather(city: str) -> str:
    """Return the weather for a city."""
    return "sunny"


# ---------------------------------------------------------------------------
# Setup: a shared database and a team of two agents with distinct models
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/auto_registry.db", id="auto-registry-db")

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

# The team has no model of its own; its components come entirely from its members
content_team = Team(
    id="content-team",
    name="Content Team",
    members=[researcher, writer],
)

# ---------------------------------------------------------------------------
# A workflow whose step reuses an agent
# ---------------------------------------------------------------------------
summarizer = Agent(
    id="summarizer",
    name="Summarizer",
    model=OpenAIResponses(id="gpt-5.4"),
)

content_workflow = Workflow(
    id="content-workflow",
    name="Content Workflow",
    steps=[Step(name="Summarize", agent=summarizer)],
)

# ---------------------------------------------------------------------------
# Create AgentOS WITHOUT an explicit registry
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="auto-registry-os",
    teams=[content_team],
    workflows=[content_workflow],
)

# ---------------------------------------------------------------------------
# Run: inspect the auto-populated registry
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    registry = agent_os.registry

    print("Models discovered:")
    for model in registry.models:
        print(f"  - {model.provider}:{model.id}")

    print("\nTools discovered:")
    for tool in registry.tools:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
        print(f"  - {name}")

    print("\nDatabases discovered:")
    for database in registry.dbs:
        print(f"  - {database.id}")

    # Every component above was discovered from the team members and the
    # workflow step. None of them were passed to a Registry explicitly. The same
    # components are served by GET /registry. Shared instances (such as a model
    # reused across agents) are collected only once.
