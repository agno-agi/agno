from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.shelly import ShellyTools

agent_db = SqliteDb(db_file="tmp/persistent_memory.db")
media_agent = Agent(
    name="Home Automation Agent",
    model=Gemini(id="gemini-2.0-flash"),
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
    tools=[ShellyTools(device_ip="192.168.1.224")],
    instructions="You are a home automation agent that can control the home automation devices. If the user asks you to control the devices, you should use the ShellyTools to control the devices.",
    debug_mode=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    agents=[media_agent],
    interfaces=[Whatsapp(agent=media_agent)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="basic:app", reload=True)
