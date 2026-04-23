"""
Standalone usage of Claude Agent SDK with Agno's .run() and .print_response() methods.

Requirements:
    pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/claude_basic.py
"""

from agno.agents.claude import ClaudeAgent

# ----- Wrap Claude Agent SDK for Agno -----
agent = ClaudeAgent(
    name="Claude Assistant",
    model="claude-sonnet-4-20250514",
    max_turns=3,
)

# Use .print_response() just like a native Agno agent
agent.print_response(
    "What is quantum computing? Explain in 2-3 sentences.", stream=True
)
