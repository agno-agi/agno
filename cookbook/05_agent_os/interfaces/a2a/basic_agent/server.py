"""
Basic A2A Server
================

The minimal way to expose an Agno agent over the A2A 1.0 protocol:
`AgentOS(a2a_interface=True)`. No protocol code required — AgentOS mounts
the A2A routes, builds the v1 AgentCard and speaks the official wire format.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

basic_agent = Agent(
    id="basic-agent",
    name="Basic Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    description="A helpful AI assistant exposed over the A2A protocol.",
    instructions="You are a helpful AI assistant. Keep answers concise.",
    markdown=True,
)

agent_os = AgentOS(
    agents=[basic_agent],
    a2a_interface=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run the A2A server.

    Endpoints (A2A 1.0, JSON-RPC 2.0 envelope, flat Part with mediaType):
        GET  http://localhost:9999/a2a/agents/basic-agent/.well-known/agent-card.json
        POST http://localhost:9999/a2a/agents/basic-agent/v1                 (JSON-RPC: SendMessage / SendStreamingMessage / GetTask / CancelTask — what the a2a-sdk Client targets)
        POST http://localhost:9999/a2a/agents/basic-agent/v1/message:send    (legacy URL-style, kept for back-compat)
        POST http://localhost:9999/a2a/agents/basic-agent/v1/message:stream  (legacy URL-style, kept for back-compat)

    Talk to it with `client.py` in this folder, any a2a-sdk client, or the
    a2a-inspector.
    """
    agent_os.serve(app="server:app", port=9999, reload=True)
