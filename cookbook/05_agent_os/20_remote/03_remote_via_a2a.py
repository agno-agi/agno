"""
Call Agno and Google ADK Agents through A2A
===========================================

The Agno peer uses entity-scoped REST routes while Google ADK uses JSON-RPC at
the server root. RemoteAgent maps both protocol responses into Agno RunOutput.

Prerequisites: start `servers/a2a_server.py` and `servers/adk_server.py`; set OPENAI_API_KEY and GOOGLE_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/20_remote/03_remote_via_a2a.py
Try: compare the Agno Agent card fields with the Google ADK response
"""

import asyncio

from agno.agent import RemoteAgent

# ---------------------------------------------------------------------------
# Create A2A Remote Agents
# ---------------------------------------------------------------------------

agno_a2a_agent = RemoteAgent(
    base_url="http://127.0.0.1:7781/a2a/agents/a2a-assistant",
    agent_id="a2a-assistant",
    protocol="a2a",
    a2a_protocol="rest",
)

adk_a2a_agent = RemoteAgent(
    base_url="http://127.0.0.1:8001",
    agent_id="facts_agent",
    protocol="a2a",
    a2a_protocol="json-rpc",
)

# ---------------------------------------------------------------------------
# Run A2A Remote Agents
# ---------------------------------------------------------------------------


async def run_a2a_agents() -> None:
    """Inspect the REST peer, then call both A2A transports."""
    config = await agno_a2a_agent.get_agent_config()
    print(f"Agno A2A Agent: {config.id} ({config.name})")
    print(config.description)

    agno_response = await agno_a2a_agent.arun(
        "Use the calculator to add 19 and 23.",
        session_id="agno-a2a-session",
    )
    print(f"\nAgno REST run: {agno_response.run_id}")
    print(agno_response.content)

    adk_response = await adk_a2a_agent.arun(
        "Share one durable fact about Saturn.",
        session_id="adk-a2a-session",
    )
    print(f"\nGoogle ADK JSON-RPC run: {adk_response.run_id}")
    print(adk_response.content)


if __name__ == "__main__":
    asyncio.run(run_a2a_agents())
