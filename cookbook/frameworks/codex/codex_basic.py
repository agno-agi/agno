"""
Standalone usage of the Codex SDK with Agno's .run() and .print_response() methods.

Codex (OpenAI's coding agent) runs locally through the Codex CLI that ships
with the openai-codex Python package. Authenticate once with the Codex CLI
(`codex login`) or set CODEX_API_KEY / OPENAI_API_KEY.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_basic.py
"""

from agno.agents.codex import CodexAgent

# ----- Wrap Codex for Agno -----
agent = CodexAgent(
    name="Codex Assistant",
    model="gpt-5.6-luna",
    sandbox="read-only",
)

# Use .print_response() just like a native Agno agent
agent.print_response(
    "What is quantum computing? Explain in 2-3 sentences.", stream=True
)
