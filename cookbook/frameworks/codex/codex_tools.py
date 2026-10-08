"""
Codex with built-in tool calls, wrapped in Agno's CodexAgent.

Codex has built-in tools (shell commands, file edits, web search, MCP) that
are executed by the Codex runtime. You control what it may touch with the
sandbox setting:

    read-only        read files and run read-only commands (default)
    workspace-write  also edit files inside the working directory
    full-access      no filesystem restrictions

Shell commands, file changes and MCP calls show up as Agno tool call events,
so they render in print_response() and stream over AgentOS.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_tools.py
"""

from agno.agents.codex import CodexAgent

# ----- Agent with built-in tools -----
agent = CodexAgent(
    name="Codex Coder",
    model="gpt-5.6-luna",
    sandbox="read-only",
    cwd=".",
    reasoning_effort="low",
)

# Streaming with tool calls visible
agent.print_response(
    "List the Python files in the current directory and summarize what this project does",
    stream=True,
)
