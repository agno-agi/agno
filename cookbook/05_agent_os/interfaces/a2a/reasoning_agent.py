"""
Reasoning Agent
===============

Demonstrates reasoning agent.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

reasoning_agent = Agent(
    name="reasoning-agent",
    id="reasoning_agent",
    model=OpenAIChat(id="o4-mini"),
    description="An advanced AI assistant with deep reasoning and analytical capabilities, enhanced with real-time web search to deliver thorough, well-thought-out responses with contextual awareness",
    instructions="You are a helpful AI assistant with reasoning capabilities.",
    add_datetime_to_context=True,
    add_history_to_context=True,
    add_location_to_context=True,
    timezone_identifier="Etc/UTC",
    markdown=True,
    tools=[WebSearchTools()],
)

# Setup your AgentOS app
agent_os = AgentOS(
    agents=[reasoning_agent],
    a2a_interface=True,
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS with the A2A 1.0 interface.

    Endpoints (A2A 1.0, JSON-RPC 2.0 envelope, flat Part with mediaType):
        GET  http://localhost:7777/a2a/agents/{id}/.well-known/agent-card.json
        POST http://localhost:7777/a2a/agents/{id}/v1                 (JSON-RPC: SendMessage / SendStreamingMessage — what the a2a-sdk Client targets)
        POST http://localhost:7777/a2a/agents/{id}/v1/message:send    (legacy URL-style, kept for back-compat)
        POST http://localhost:7777/a2a/agents/{id}/v1/message:stream  (legacy URL-style, kept for back-compat)

    Reasoning steps surface over streaming as TaskStatusUpdateEvents with
    metadata `agno_content_category=reasoning` plus `agno_event_type` in
    {reasoning_started, reasoning_step, reasoning_completed}. The reasoning
    text is in `metadata.reasoning_content`.

    Test with the official a2a-sdk client (see README.md for a runnable snippet)
    or with the a2a-inspector at https://github.com/a2aproject/a2a-inspector.
    """
    agent_os.serve(app="reasoning_agent:app", reload=True, port=7777)
