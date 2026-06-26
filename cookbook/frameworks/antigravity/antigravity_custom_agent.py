"""
Antigravity with a custom (named) agent definition.

Demonstrates the Agents API flow: instead of running the base `antigravity` agent
with ad-hoc instructions, you register a named agent definition once and then
invoke it by name. Useful when:

  - You want stable, reusable agent identities to schedule / share / version.
  - Instructions + sources should live with the agent definition, not the call.

Registration is explicit: call `agent.ensure_custom_agent()` once before the
first run. It POSTs to /v1beta/agents and treats 409 / already-exists as success,
so re-running this script is idempotent.

Requirements:
    export GEMINI_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/antigravity/antigravity_custom_agent.py
"""

from agno.agents.antigravity import AntigravityAgent

agent = AntigravityAgent(
    name="Haiku Bot",
    custom_agent_name="agno-haiku-bot",
    custom_agent_instructions=(
        "You are a haiku-writing assistant. Always respond with exactly one haiku "
        "(three lines, 5-7-5 syllable structure) and nothing else."
    ),
    custom_agent_description="Demo custom Antigravity agent that only writes haikus.",
)

# Register the definition with the API. Idempotent — safe to re-run.
agent.ensure_custom_agent()

# Invoke the registered agent.
agent.print_response("Write a haiku about Python.", stream=True)
agent.print_response("Now one about the ocean.", stream=True)
