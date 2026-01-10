"""
This cookbook demonstrates how to use a registry in an AgentOS app.
"""

from agno.agent.agent import Agent, get_agent_by_id  # noqa: F401
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.duckduckgo import DuckDuckGoTools

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


def sample_tool():
    return "Hello, world!"


registry = Registry(
    name="Agno Registry",
    description="Registry for Agno",
    tools=[DuckDuckGoTools(), sample_tool],
    models=[OpenAIChat(id="gpt-5-mini")],
    dbs=[db],
)

agent = Agent(
    id="registry-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
)

agent_os = AgentOS(
    agents=[agent],
    id="registry-agent-os",
    registry=registry,
    db=db,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agent_os_registry:app", reload=True)
