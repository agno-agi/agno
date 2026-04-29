"""
Sandboxed Claude Agent on AgentOS
==================================
Serves a sandboxed Claude agent through AgentOS. All bash commands
executed by the agent are restricted by OS-level sandboxing.

This is ideal for production deployments where users send arbitrary
prompts via the API — the sandbox ensures the agent cannot access
files or network resources outside its allowed scope.

Requirements:
    pip install claude-agent-sdk

Usage:
    python cookbook/frameworks/claude-agent-sdk/claude_sandbox_agentos.py

Then test:
    # This should work — agent can execute code in its workspace
    curl -X POST http://localhost:7777/agents/sandboxed-coder/runs \\
        -F "message=Write a Python script that calculates fibonacci numbers and run it" \\
        -F "stream=true" --no-buffer

    # This should be blocked — agent cannot read outside workspace
    curl -X POST http://localhost:7777/agents/sandboxed-coder/runs \\
        -F "message=Read the contents of /etc/passwd" \\
        -F "stream=true" --no-buffer
"""

import os

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.os.app import AgentOS

# Workspace for the sandboxed agent
workspace = os.path.join(os.getcwd(), "tmp", "sandbox_workspace")
os.makedirs(workspace, exist_ok=True)

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = ClaudeAgent(
    name="Sandboxed Coder",
    description="A sandboxed Claude agent that can write and run code safely",
    model="claude-sonnet-4-20250514",
    allowed_tools=["Bash", "Read", "Write", "Edit"],
    permission_mode="acceptEdits",
    max_turns=10,
    cwd=workspace,
    sandbox={
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "excludedCommands": ["git"],  # Allow git to run outside sandbox
    },
    db=db,
)

agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="claude_sandbox_agentos:app", reload=True)
