"""
Claude Agent SDK with built-in tool calls, wrapped in Agno's ClaudeAgent.

The Claude Agent SDK has built-in tools (Read, Edit, Bash, Glob, Grep, WebSearch, etc.)
that are executed internally by the SDK. You just specify which tools to allow.

Requirements:
    pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/claude_tools.py
"""

from agno.agents.claude import ClaudeAgent

# ----- Agent with built-in tools -----
agent = ClaudeAgent(
    name="Claude Coder",
    model="claude-sonnet-4-20250514",
    allowed_tools=["Read", "Bash", "Glob"],
    permission_mode="acceptEdits",
    max_turns=5,
)

# Streaming with tool calls visible
agent.print_response(
    "List the Python files in the current directory and summarize what this project does",
    stream=True,
)
