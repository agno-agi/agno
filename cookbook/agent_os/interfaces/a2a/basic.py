from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

chat_agent = Agent(
    name="basic-agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful AI assistant.",
    add_datetime_to_context=True,
    markdown=True,
)

# Setup your AgentOS app
agent_os = AgentOS(
    agents=[chat_agent],
    a2a_interface=True,
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS with A2A interface.

    You can run the basic-agent via A2A protocol:
    POST http://localhost:7777/a2a/message/send
    (include "agentId": "basic-agent" in params.message)

    """
    agent_os.serve(app="basic:app", reload=True, port=7777)
