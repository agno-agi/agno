"""
Call an Agno A2A agent with A2AClient
==========================================

An Agno orchestrator agent uses `A2AClient` (which wraps the official
`a2a-sdk` client) to talk to another Agno agent over A2A 1.0. One toolkit
instance binds one remote agent, and its tool names carry the remote
agent's URL slug (`send_message_to_basic_agent`, `get_basic_agent_card`).

First, in another terminal, start one of the interface cookbook servers:

    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/basic.py
    # -> serves http://localhost:7777/a2a/agents/basic_agent

Then run this script:

    .venvs/demo/bin/python cookbook/91_tools/a2a/01_call_agno_a2a_agent.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.a2a import A2AClient

REMOTE_AGENT_URL = "http://localhost:7777/a2a/agents/basic_agent"

orchestrator = Agent(
    name="Orchestrator",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[A2AClient(url=REMOTE_AGENT_URL)],
    description="An orchestrator that delegates user questions to a remote Agno A2A agent.",
    instructions=[
        "Use `send_message_to_basic_agent(message=...)` to forward the user's question to the remote agent.",
        "If you want to know what the remote agent can do, call `get_basic_agent_card()` first (no args).",
        "Return the remote agent's response verbatim to the user.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    orchestrator.print_response(
        "Ask the remote agent to say hello in three different languages."
    )
