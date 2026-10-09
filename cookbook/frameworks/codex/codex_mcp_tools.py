"""
Codex with MCP tools, wrapped in Agno's CodexAgent.

Codex connects to MCP servers through its config. Pass `config` overrides to
CodexAgent and they apply to every thread the agent starts, the same way an
`mcp_servers` table in ~/.codex/config.toml would.

MCP tool calls are surfaced as Agno tool call events named
`mcp__<server>__<tool>`.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_mcp_tools.py
"""

from agno.agents.codex import CodexAgent

# ----- Agent with an MCP server -----
agent = CodexAgent(
    name="Codex Docs Agent",
    model="gpt-5.6-luna",
    sandbox="read-only",
    config={
        "mcp_servers": {
            "agno_docs": {"url": "https://docs.agno.com/mcp"},
        }
    },
)

agent.print_response(
    "Use the agno_docs MCP server to find out what AgentOS is. Answer in two sentences.",
    stream=True,
)
