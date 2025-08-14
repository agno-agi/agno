from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp.whatsapp import Whatsapp

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="AgentOS setup with a Whatsapp interface",
    agents=[basic_agent],
    interfaces=[Whatsapp(agent=basic_agent)],
)

app = agent_os.get_app()


if __name__ == "__main__":
    """Run our AgentOS.

    You can see the configuration and available interfaces on:
    http://localhost:7777/config

    """
    agent_os.serve(app="basic:app", reload=True)
