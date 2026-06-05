"""
Remote Agent with A2A Protocol
==============================

This cookbook demonstrates using a RemoteAgent with the A2A (Agent-to-Agent)
protocol, which enables cross-framework agent communication.

A2A is a standardized protocol that allows agents built with different
frameworks to communicate with each other.

Requirements:
    - A running A2A-compatible server
    - The server must expose the /.well-known/agent.json endpoint
"""

import asyncio

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.models.openai import OpenAIResponses
from agno.team.team import Team


async def main():
    # 1. Create a local agent
    analyst = Agent(
        name="Analyst",
        agent_id="analyst",
        model=OpenAIResponses(id="gpt-4o-mini"),
        instructions="You analyze and interpret data findings.",
    )

    # 2. Create a RemoteAgent using A2A protocol
    # A2A enables communication with agents built using any framework
    remote_data_agent = RemoteAgent(
        base_url="http://localhost:8080",  # A2A-compatible server
        agent_id="data-agent",
        protocol="a2a",  # Use A2A protocol instead of AgentOS
        a2a_protocol="rest",  # Options: "rest" or "json-rpc"
        timeout=120.0,
    )

    # 3. Create a team mixing local and A2A remote agents
    team = Team(
        name="Cross-Framework Team",
        model=OpenAIResponses(id="gpt-4o-mini"),
        members=[analyst, remote_data_agent],
        instructions="""\
You coordinate between local and remote agents.
- Analyst: Interprets findings locally
- Data Agent: Fetches and processes data (remote A2A agent)

Delegate data tasks to Data Agent, then have Analyst interpret.""",
        show_members_responses=True,
    )

    print("Testing A2A protocol with remote agent...")
    print("=" * 60)

    await team.aprint_response(
        "Ask the Data Agent to fetch the latest metrics, then have Analyst interpret them.",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
