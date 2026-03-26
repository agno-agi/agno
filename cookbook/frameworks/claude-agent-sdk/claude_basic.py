"""
Standalone usage of Claude Agent SDK with Agno's .run() and .print_response() methods.

Requirements:
    pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude_basic.py
"""

from agno.frameworks.claude import ClaudeAgentSDK

# ----- Wrap Claude Agent SDK for Agno -----
agent = ClaudeAgentSDK(
    agent_id="claude-assistant",
    agent_name="Claude Assistant",
    model="claude-sonnet-4-20250514",
    max_turns=3,
)

# Use .print_response() just like a native Agno agent
agent.print_response(
    "What is quantum computing? Explain in 2-3 sentences.", stream=True
)
