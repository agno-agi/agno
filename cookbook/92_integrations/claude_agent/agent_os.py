"""AgentOS example: Running Claude Agent SDK agents alongside native Agno agents.

This demonstrates how to register a ClaudeAgent with AgentOS so it can be
accessed via the standard REST API alongside regular Agno agents.

Features:
    - Database-backed session persistence for both agent types
    - Streaming and non-streaming execution
    - Session history via AgentOS APIs

Requirements:
    pip install claude-agent-sdk agno
    export ANTHROPIC_API_KEY=sk-...

Run:
    python cookbook/92_integrations/claude_agent/agent_os.py

Then use the API:
    # List all agents
    curl http://localhost:7777/agents

    # Run the Claude agent (streaming)
    curl -X POST http://localhost:7777/agents/code-assistant/runs \
      -F "message=List the files in this project" \
      -F "stream=true"

    # Run the Claude agent (non-streaming)
    curl -X POST http://localhost:7777/agents/code-assistant/runs \
      -F "message=What is this project about?" \
      -F "stream=false"
"""

from agno.agent import Agent
from agno.agent.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# --- Shared database for session persistence ---
db = SqliteDb(db_file="tmp/claude_agent_os.db")

# --- Claude Agent SDK agent ---
claude_agent = ClaudeAgent(
    agent_id="code-assistant",
    name="Code Assistant",
    description="A Claude-powered coding agent with file system access.",
    system_prompt="You are a helpful coding assistant. Help users understand and navigate codebases.",
    allowed_tools=["Read", "Glob", "Grep", "Bash"],
    max_turns=10,
    db=db,
)

# --- Native Agno agent ---
agno_agent = Agent(
    name="Greeting Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["You are a friendly assistant. Greet users warmly."],
    db=db,
)

# --- Register both with AgentOS ---
agent_os = AgentOS(
    agents=[claude_agent, agno_agent],
    db=db,
)

app = agent_os.get_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7777)
