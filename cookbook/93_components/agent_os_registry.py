"""
AgentOS Registry App
====================

Demonstrates configuring AgentOS with a Registry and serving the app.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", id="postgres_db")


def sample_tool():
    return "Hello, world!"


# ---------------------------------------------------------------------------
# Create Registry
# ---------------------------------------------------------------------------
registry = Registry(
    name="Agno Registry",
    tools=[DuckDuckGoTools(), sample_tool, CalculatorTools()],
    models=[
        OpenAIChat(id="gpt-5-mini"),
        OpenAIChat(id="gpt-5"),
        Claude(id="claude-sonnet-4-5"),
    ],
    dbs=[db],
)

# ---------------------------------------------------------------------------
# Create AgentOS App
# ---------------------------------------------------------------------------
agent = Agent(
    id="registry-agent",
    model=Claude(id="claude-sonnet-4-5"),
    db=db,
)

agent_os = AgentOS(
    agents=[agent],
    id="registry-agent-os",
    registry=registry,
    db=db,
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS App
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="agent_os_registry:app", reload=True)
