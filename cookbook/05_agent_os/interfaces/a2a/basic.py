"""
Basic
=====

Demonstrates basic.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS with the A2A 1.0 interface.

    Endpoints (A2A 1.0, JSON-RPC 2.0 envelope, flat Part with mediaType):
        POST http://localhost:7777/a2a/agents/{id}/v1/message:send
        POST http://localhost:7777/a2a/agents/{id}/v1/message:stream
        GET  http://localhost:7777/a2a/agents/{id}/.well-known/agent-card.json

    Test with the official a2a-sdk client (see README.md for a runnable snippet)
    or with the a2a-inspector at https://github.com/a2aproject/a2a-inspector.
    """
    agent_os.serve(app="basic:app", reload=True, port=7777)
