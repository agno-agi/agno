"""
Manage Antigravity custom agents via the Agents API toolkit.

`AntigravityTools` exposes the full CRUD surface of `/v1beta/agents` as tools
that an Agno agent can call:

  - create_custom_antigravity_agent: POST /agents
  - get_custom_antigravity_agent:    GET  /agents/{name}
  - list_antigravity_agents:         GET  /agents
  - list_antigravity_agent_versions: GET  /agents/{name}/versions
  - update_custom_antigravity_agent: PATCH /agents/{name}
  - delete_antigravity_agent:        DELETE /agents/{name}
  - run_custom_antigravity_agent:    POST /interactions with `agent=<name>`

Plus `run_antigravity_task` for one-off invocations of the base antigravity agent.

This cookbook shows a Gemini-driven Agno agent driving the full lifecycle:
create a haiku-bot definition, invoke it, then clean up.

Requirements:
    export GEMINI_API_KEY=...
    uv pip install agno google-genai

Usage:
    .venvs/demo/bin/python cookbook/91_tools/antigravity/antigravity_agents_crud_tools.py
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.antigravity import AntigravityTools

agent = Agent(
    name="Antigravity Admin",
    model=Gemini(id="gemini-2.5-pro"),
    tools=[AntigravityTools()],
    markdown=True,
    instructions=[
        "You manage custom Antigravity agents via the Agents API tools.",
        "When asked to create an agent, use create_custom_antigravity_agent with the requested name and instructions.",
        "When asked to invoke a named agent, use run_custom_antigravity_agent.",
        "When asked to clean up, use delete_antigravity_agent.",
        "Surface the agent ids / responses to the user clearly.",
    ],
)

if __name__ == "__main__":
    agent.print_response(
        "Create a custom Antigravity agent called 'demo-haiku-bot' whose only job is to "
        "write a single haiku in response to any prompt. Then invoke it with the prompt "
        "'autumn leaves'. Finally, delete the agent."
    )
