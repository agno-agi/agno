"""
Codex on AgentOS
================
Serve a Codex agent through AgentOS -- the same runtime used for native
Agno agents.

The agent is available at the standard /agents/{agent_id}/runs endpoint,
supports streaming (SSE) and non-streaming responses, and appears in
the AgentOS UI alongside any native agents.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_agentos.py

Then call the API:
    # List agents
    curl http://localhost:7777/agents

    # Streaming
    curl -X POST http://localhost:7777/agents/codex-assistant/runs \
        -F "message=What is quantum computing?" \
        -F "stream=true" \
        --no-buffer

    # Non-streaming
    curl -X POST http://localhost:7777/agents/codex-assistant/runs \
        -F "message=What is quantum computing?" \
        -F "stream=false"
"""

from agno.agents.codex import CodexAgent
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create the Codex agent
# ---------------------------------------------------------------------------
codex_agent = CodexAgent(
    name="Codex Assistant",
    description="A Codex-powered coding assistant served through AgentOS",
    model="gpt-5.6-luna",
    sandbox="read-only",
    cwd=".",
)

# ---------------------------------------------------------------------------
# Setup AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    name="Codex Example",
    description="AgentOS serving a Codex agent",
    agents=[codex_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="codex_agentos:app", reload=True)
