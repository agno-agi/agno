"""
Basic Agent Protocol Server
============================

Demonstrates exposing an Agno agent via the Agent Protocol interface.
Any Agent Protocol client (including deepagents) can connect to this server.

Run:
    python server.py

Endpoints available at:
    POST http://localhost:7778/ap/threads          - Create a thread
    POST http://localhost:7778/ap/threads/{id}/runs - Run agent on thread
    GET  http://localhost:7778/ap/threads/{id}      - Get thread state
    POST http://localhost:7778/ap/agents/search     - List agents
    GET  http://localhost:7778/ap/agents/{id}       - Get agent info
    POST http://localhost:7778/ap/runs/wait         - Stateless run (blocking)
    POST http://localhost:7778/ap/runs/stream       - Stateless run (streaming)
"""

from agno.agent.agent import Agent
from agno.models.anthropic import Claude
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

research_agent = Agent(
    name="research-agent",
    model=Claude(id="claude-sonnet-4-6"),
    id="research_agent",
    description="A research agent that investigates topics in depth and provides thorough, well-structured answers.",
    instructions=(
        "You are a research agent. When given a topic, provide a thorough, "
        "well-structured analysis with key findings, recent developments, "
        "and relevant context."
    ),
    add_datetime_to_context=True,
    markdown=True,
    debug_mode=True,
)

assistant_agent = Agent(
    name="assistant-agent",
    model=Claude(id="claude-sonnet-4-6"),
    id="assistant_agent",
    description="A helpful AI assistant that provides concise, accurate answers.",
    instructions="You are a helpful AI assistant. Provide clear, concise answers.",
    add_datetime_to_context=True,
    markdown=True,
    debug_mode=True,
)

# ---------------------------------------------------------------------------
# Setup AgentOS with Agent Protocol interface
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[research_agent, assistant_agent],
    agent_protocol_interface=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run the AgentOS with Agent Protocol interface.

    Test with curl:
        # List agents
        curl -s http://localhost:7778/ap/agents/search -X POST -H 'Content-Type: application/json' -d '{}'

        # Create a thread
        curl -s http://localhost:7778/ap/threads -X POST -H 'Content-Type: application/json' -d '{}'

        # Run agent (stateless)
        curl -s http://localhost:7778/ap/runs/wait -X POST -H 'Content-Type: application/json' \\
            -d '{"agent_id":"research_agent","input":{"messages":[{"role":"user","content":"What is quantum computing?"}]}}'
    """
    agent_os.serve(app="server:app", reload=True, port=7778)
