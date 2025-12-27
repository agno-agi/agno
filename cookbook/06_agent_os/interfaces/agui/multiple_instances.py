from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools.duckduckgo import DuckDuckGoTools

db = SqliteDb(db_file="tmp/agentos.db")

chat_agent = Agent(
    name="Assistant",
    model=OpenAIChat(id="gpt-5-mini"),
    db=db,
    instructions="You are a helpful AI assistant.",
    add_datetime_to_context=True,
    markdown=True,
)

web_research_agent = Agent(
    name="Web Research Agent",
    model=OpenAIChat(id="gpt-5-mini"),
    db=db,
    tools=[DuckDuckGoTools()],
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


if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="multiple_instances:app", reload=True)
