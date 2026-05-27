"""
Multi-Framework AgentOS — Agno + Claude Code
============================================
Serve a Claude Code agent (via the Claude Agent SDK) and an Agno agent
through a single AgentOS. They share one database, one API surface,
and one UI.

This is the example from the launch blog post:
    "AgentOS now supports Claude Code, LangGraph, and DSPy"

Requirements:
    pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/00_quickstart/multi_framework_agentos.py

Then call the API:
    # List agents
    curl http://localhost:7777/agents

    # Run the Agno agent
    curl -X POST http://localhost:7777/agents/agno-agent/runs \\
        -F "message=List the Python files in this directory" \\
        -F "stream=true" --no-buffer

    # Run the Claude Code agent
    curl -X POST http://localhost:7777/agents/claude-code-agent/runs \\
        -F "message=Read README.md and summarize it" \\
        -F "stream=true" --no-buffer
"""

from agno.agent import Agent
from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.tools.workspace import Workspace

# ---------------------------------------------------------------------------
# Claude Code agent (via the Claude Agent SDK)
# ---------------------------------------------------------------------------
claude_agent = ClaudeAgent(
    name="Claude Code Agent",
    model="claude-sonnet-4-6",
    allowed_tools=["Read", "Edit", "Bash"],
    permission_mode="acceptEdits",
    max_turns=10,
)

# ---------------------------------------------------------------------------
# Agno agent
# ---------------------------------------------------------------------------
agno_agent = Agent(
    name="Agno Agent",
    model="openai:gpt-5.4",
    tools=[
        Workspace(
            root=".",
            allowed=["read", "list", "search"],
            confirm=["write", "edit", "delete", "shell"],
        )
    ],
)

# ---------------------------------------------------------------------------
# Serve both through one AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    agents=[agno_agent, claude_agent],
    tracing=True,
    db=SqliteDb(db_file="tmp/agentos.db"),
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="multi_framework_agentos:app", reload=True)
