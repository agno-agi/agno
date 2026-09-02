"""
OpenCode on AgentOS
===================
Serve an OpenCode coding agent through AgentOS -- the same runtime used for
native Agno agents.

The agent is available at the standard /agents/{agent_id}/runs endpoint,
supports streaming (SSE) and non-streaming responses, and appears in the
AgentOS UI alongside any native agents.

Requirements:
    npm install -g opencode-ai
    opencode serve --port 4096

Usage:
    .venvs/demo/bin/python cookbook/frameworks/opencode/opencode_agentos.py

Then call the API:
    # List agents
    curl http://localhost:7777/agents

    # Streaming
    curl -X POST http://localhost:7777/agents/opencode-dev/runs \
        -F "message=List the files in this project" \
        -F "stream=true" \
        --no-buffer

    # Non-streaming
    curl -X POST http://localhost:7777/agents/opencode-dev/runs \
        -F "message=List the files in this project" \
        -F "stream=false"
"""

from agno.agents.opencode import OpenCodeAgent
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create the OpenCode agent
# ---------------------------------------------------------------------------
opencode_agent = OpenCodeAgent(
    name="OpenCode Dev",
    description="An OpenCode coding agent served through AgentOS",
    base_url="http://127.0.0.1:4096",
)

# ---------------------------------------------------------------------------
# Setup AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    name="OpenCode Example",
    description="AgentOS serving an OpenCode coding agent",
    agents=[opencode_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="opencode_agentos:app", reload=True)
