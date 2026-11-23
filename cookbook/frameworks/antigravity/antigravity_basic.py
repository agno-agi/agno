"""
Standalone usage of Google's Gemini Agents API (Antigravity) via Agno's
.run() and .print_response() methods.

Requirements:
    export GEMINI_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/antigravity/antigravity_basic.py
"""

from agno.agents.antigravity import AntigravityAgent

agent = AntigravityAgent(name="Antigravity")

agent.print_response(
    "What is 2 + 2? Explain your reasoning briefly.",
    stream=True,
)
