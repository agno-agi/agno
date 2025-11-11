from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.duckduckgo import DuckDuckGoTools

reasoning_agent = Agent(
    name="reasoning-agent",
    model=OpenAIChat(id="o4-mini"),
    instructions="You are a helpful AI assistant with reasoning capabilities.",
    add_datetime_to_context=True,
    add_history_to_context=True,
    add_location_to_context=True,
    timezone_identifier="Etc/UTC",
    markdown=True,
    tools=[DuckDuckGoTools()],
)

# Setup your AgentOS app
agent_os = AgentOS(
    agents=[reasoning_agent],
    a2a_interface=True,
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS with A2A interface.

    You can run the reasoning-agent via A2A protocol:
    POST http://localhost:7777/a2a/message/send
    (include "agentId": "reasoning-agent" in params.message)
    """
    agent_os.serve(app="reasoning_agent:app", reload=True, port=7777)
