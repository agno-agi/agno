from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic.claude import Claude
from agno.os.app import AgentOS
from agno.os.interfaces.telegram import Telegram
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools

agent_db = SqliteDb(db_file="tmp/persistent_memory.db")

reasoning_agent = Agent(
    name="Reasoning Research Agent",
    model=Claude(id="claude-3-7-sonnet-latest"),
    db=agent_db,
    tools=[
        ReasoningTools(add_instructions=True),
        DuckDuckGoTools(),
    ],
    instructions="Use tables to display data. When you use thinking tools, keep the thinking brief.",
    add_datetime_to_context=True,
    markdown=True,
)


# Setup our AgentOS app
agent_os = AgentOS(
    agents=[reasoning_agent],
    interfaces=[Telegram(agent=reasoning_agent)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="reasoning_agent:app", reload=True)
