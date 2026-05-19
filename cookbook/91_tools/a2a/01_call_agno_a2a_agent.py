"""
Call an Agno A2A agent with A2AClientTools
==========================================

An Agno orchestrator agent uses `A2AClientTools` (which wraps the official
`a2a-sdk` client) to talk to another Agno agent over A2A 1.0. Proves the
toolkit works end-to-end against an Agno-hosted A2A server — same way any
external A2A 1.0 client would.

First, in another terminal, start one of the interface cookbook servers:

    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/basic.py
    # -> serves http://localhost:7777/a2a/agents/basic_agent

Then run this script:

    .venvs/demo/bin/python cookbook/91_tools/a2a/01_call_agno_a2a_agent.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.a2a import A2AClientTools

REMOTE_AGENT_URL = "http://localhost:7777/a2a/agents/basic_agent"

orchestrator = Agent(
    name="Orchestrator",
    model=OpenAIChat(id="gpt-4o"),
    tools=[A2AClientTools(default_agent_url=REMOTE_AGENT_URL)],
    description="An orchestrator that delegates user questions to a remote Agno A2A agent.",
    instructions=[
        "Use `send_message(message=...)` to forward the user's question to the remote agent.",
        "The toolkit is pre-configured with the remote URL — do NOT pass an `agent_url` argument.",
        "If you want to know what the remote agent can do, call `get_agent_card()` first (no args).",
        "Return the remote agent's response verbatim to the user.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    orchestrator.print_response(
        "Ask the remote agent to say hello in three different languages."
    )
