from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

chat_agent = Agent(
    name="basic-agent",
    model=OpenAIChat(id="gpt-4o"),
    id="basic_agent",
    description="A helpful and responsive AI assistant that provides thoughtful answers and assistance with a wide range of topics",
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

    You can run the Agent via A2A protocol:
    POST http://localhost:7777/agents/{id}/v1/message:send
    For streaming responses:
    POST http://localhost:7777/agents/{id}/v1/message:stream
    Retrieve the agent card at:
    GET  http://localhost:7777/agents/{id}/.well-known/agent-card.json

    """
    agent_os.serve(app="basic:app", reload=True, port=7777)
