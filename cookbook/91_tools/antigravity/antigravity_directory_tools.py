"""
Use a local Antigravity agent directory through AntigravityTools.

Pass `agent_directory=` to the toolkit constructor and it will:
  1. Parse `agent.yaml`, `AGENTS.md`, `workspace/`, and `skills/`.
  2. Register the agent definition via POST /v1beta/agents (idempotent).
  3. Route all subsequent `run_antigravity_task` calls at the named custom agent.

Lets a regular Agno agent (any model) delegate sub-tasks to a folder-defined
Antigravity agent without having to wire up `/agents` calls yourself.

Re-uses the example folder from
`cookbook/frameworks/antigravity/example_agent/`.

Requirements:
    export GEMINI_API_KEY=...
    uv pip install agno google-genai pyyaml

Usage:
    .venvs/demo/bin/python cookbook/91_tools/antigravity/antigravity_directory_tools.py
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.antigravity import AntigravityTools

AGENT_DIR = (
    Path(__file__).parent.parent.parent / "frameworks" / "antigravity" / "example_agent"
)

agent = Agent(
    name="Haiku Requester",
    model=Gemini(id="gemini-2.5-pro"),
    # Register the folder once at construction; subsequent run_antigravity_task
    # calls invoke the named agent (`agno-haiku-bot-from-dir`).
    tools=[AntigravityTools(agent_directory=str(AGENT_DIR))],
    markdown=True,
    instructions=[
        "When the user asks for a haiku, delegate to the Antigravity sandbox via run_antigravity_task.",
        "Pass the topic through as-is; the sandbox agent enforces house style.",
    ],
)

if __name__ == "__main__":
    agent.print_response("Write a haiku about autumn maples.")
