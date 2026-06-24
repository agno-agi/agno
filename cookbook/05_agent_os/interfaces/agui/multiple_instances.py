"""
Multiple Instances
==================

Demonstrates multiple instances.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/agentos.db")

chat_agent = Agent(
    name="Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    instructions="You are a helpful AI assistant.",
    add_datetime_to_context=True,
    markdown=True,
)

web_research_agent = Agent(
    name="Web Research Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[WebSearchTools()],
    instructions="You are a helpful AI assistant that can search the web.",
    markdown=True,
)

# Setup your AgentOS app
agent_os = AgentOS(
    agents=[chat_agent, web_research_agent],
    interfaces=[
        AGUI(agent=chat_agent, prefix="/chat"),
        AGUI(agent=web_research_agent, prefix="/web-research"),
    ],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:9001/config

    """
    agent_os.serve(app="multiple_instances:app", reload=True, port=9001)
