"""
Codex Agent on AgentOS
======================
An OpenAI Codex agent (via the Codex Python SDK), served through AgentOS.

The Codex SDK runs the Codex CLI locally as a subprocess. Tool execution
(shell, file edits, web search, MCP) is handled by Codex -- you configure
the sandbox level and the working directory.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/00_quickstart/codex_agent.py
"""

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

agent = CodexAgent(
    name="Codex Agent",
    model="gpt-5.6-luna",
    sandbox="workspace-write",
    cwd=".",
)

agent_os = AgentOS(
    agents=[agent],
    db=SqliteDb(db_file="tmp/agentos.db"),
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="codex_agent:app", reload=True)
