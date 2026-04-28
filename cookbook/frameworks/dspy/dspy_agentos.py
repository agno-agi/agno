"""
DSPy on AgentOS
===============
Serve a DSPy program through AgentOS -- the same runtime used for native Agno agents.

The agent is available at the standard /agents/{agent_id}/runs endpoint,
supports streaming (SSE) and non-streaming responses, and appears in
the AgentOS UI alongside any native agents.

Requirements:
    pip install dspy

Usage:
    .venvs/demo/bin/python cookbook/frameworks/dspy/dspy_agentos.py

Then call the API:
    # List agents
    curl http://localhost:7777/agents

    # Streaming
    curl -X POST http://localhost:7777/agents/dspy-assistant/runs \\
        -F "message=What is quantum computing?" \\
        -F "stream=true" \\
        --no-buffer

    # Non-streaming
    curl -X POST http://localhost:7777/agents/dspy-assistant/runs \\
        -F "message=What is quantum computing?" \\
        -F "stream=false"
"""

import dspy
from agno.agents.dspy import DSPyAgent
from agno.os.app import AgentOS

# ---------------------------------------------------------------------------
# Configure DSPy LM (must be set on the main thread)
# ---------------------------------------------------------------------------
dspy.configure(lm=dspy.LM("openai/gpt-5.4"))

# ---------------------------------------------------------------------------
# Create the DSPy agent
# ---------------------------------------------------------------------------
dspy_agent = DSPyAgent(
    name="DSPy Assistant",
    description="A DSPy-powered assistant served through AgentOS",
    program=dspy.ChainOfThought("question -> answer"),
)

# ---------------------------------------------------------------------------
# Setup AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    name="DSPy Agent Example",
    description="AgentOS serving a DSPy agent",
    agents=[dspy_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="dspy_agentos:app", reload=True)
