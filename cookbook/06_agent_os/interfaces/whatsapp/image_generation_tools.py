from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.openai import OpenAITools

agent_db = SqliteDb(db_file="tmp/persistent_memory.db")
image_agent = Agent(
    id="image_generation_tools",
    db=agent_db,
    model=OpenAIChat(id="gpt-4o"),
    tools=[OpenAITools(image_model="gpt-image-1")],
    markdown=True,
    debug_mode=True,
    add_history_to_context=True,
)


# Setup our AgentOS app
agent_os = AgentOS(
    agents=[image_agent],
    interfaces=[Whatsapp(agent=image_agent)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="image_generation_tools:app", reload=True)
