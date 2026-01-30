from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp

agent_db = SqliteDb(db_file="tmp/persistent_memory.db")
image_agent = Agent(
    id="image_generation_model",
    db=agent_db,
    model=Gemini(
        id="models/gemini-2.5-flash-image",
        response_modalities=["Text", "Image"],
    ),
    debug_mode=True,
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
    agent_os.serve(app="image_generation_model:app", reload=True)
