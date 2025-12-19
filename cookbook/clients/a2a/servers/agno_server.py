"""Agno AgentOS A2A Server for testing A2AClient.

This server uses Agno's AgentOS to create an A2A-compatible
agent that can be tested with A2AClient.

Prerequisites:
    export OPENAI_API_KEY=your_key

Usage:
    python cookbook/clients/a2a/servers/agno_server.py

The server will start at http://localhost:7777
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

chat_agent = Agent(
    name="basic-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    id="basic_agent",
    description="A helpful AI assistant that provides thoughtful answers.",
    instructions="You are a helpful AI assistant.",
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[chat_agent],
    a2a_interface=True,
)
app = agent_os.get_app()


if __name__ == "__main__":
    print("Server URL: http://localhost:7777")
    agent_os.serve(app="agno_server:app", reload=True, port=7777)
