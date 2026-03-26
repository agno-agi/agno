"""
Run a Claude Agent SDK agent through AgentOS endpoints.

This shows how to register a Claude Agent SDK agent alongside native Agno agents
and serve them all through the same AgentOS runtime.

Requirements:
    pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude_agentos.py

Then call the API:
    # Streaming
    curl -X POST http://localhost:7777/agents/claude-assistant/runs \
        -F "message=What is quantum computing?" \
        -F "stream=true" \
        --no-buffer

    # Non-streaming
    curl -X POST http://localhost:7777/agents/claude-assistant/runs \
        -F "message=What is quantum computing?" \
        -F "stream=false"

    # List agents
    curl http://localhost:7777/agents
"""

from agno.frameworks.claude import ClaudeAgentSDK
from agno.os.app import AgentOS

# ----- Wrap Claude Agent SDK for AgentOS -----
claude_agent = ClaudeAgentSDK(
    agent_id="claude-assistant",
    agent_name="Claude Assistant",
    description="A Claude-powered assistant served through AgentOS",
    model="claude-sonnet-4-20250514",
    allowed_tools=["Read", "Bash"],
    permission_mode="acceptEdits",
    max_turns=10,
)

# ----- Serve through AgentOS -----
app = AgentOS(agents=[claude_agent])
app.serve(app.get_app())
