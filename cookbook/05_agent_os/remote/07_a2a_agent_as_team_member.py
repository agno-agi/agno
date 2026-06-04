"""
A2A Agent as Team Member
========================

Demonstrates using RemoteAgent with the A2A protocol to include agents
from any A2A-compatible framework as team members:
- Another Agno instance with A2A interface
- Google ADK agents
- LangGraph agents
- Any A2A-compatible agent

The A2A (Agent-to-Agent) protocol is an open standard for cross-framework
agent communication, enabling interoperability regardless of implementation.

Prerequisites:
1. Install A2A SDK:
   pip install a2a-sdk

2. Start the A2A server:
   python cookbook/05_agent_os/remote/agno_a2a_server.py  (port 7779)

3. Set OPENAI_API_KEY
"""

import asyncio

from agno.agent import Agent, RemoteAgent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Local Member
# ---------------------------------------------------------------------------

local_calculator = Agent(
    name="Calculator",
    role="You perform mathematical calculations and explain the steps.",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=["Show your work step by step.", "Be precise with numbers."],
)

# ---------------------------------------------------------------------------
# Create Remote A2A Members
# ---------------------------------------------------------------------------

# Connect to Agno agent exposed via A2A interface (agno_a2a_server.py)
# Uses A2A protocol with REST variant
remote_researcher = RemoteAgent(
    base_url="http://localhost:7779/a2a/agents/researcher-agent-2",
    agent_id="researcher-agent-2",
    protocol="a2a",
    a2a_protocol="rest",
)

# To connect to Google ADK agent (uses JSON-RPC variant):
# adk_agent = RemoteAgent(
#     base_url="http://localhost:7780",
#     agent_id="facts_agent",
#     protocol="a2a",
#     a2a_protocol="json-rpc",
# )

# ---------------------------------------------------------------------------
# Create Team with Local + A2A Members
# ---------------------------------------------------------------------------

research_team = Team(
    name="Cross-Framework Research Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[
        local_calculator,   # Local Agno agent
        remote_researcher,  # Remote A2A agent
    ],
    instructions=[
        "You lead a cross-framework team.",
        "Delegate math questions to the Calculator.",
        "Delegate research questions to the remote Researcher.",
        "Synthesize responses from all members.",
    ],
    markdown=True,
    show_members_responses=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------


async def main():
    print("=" * 60)
    print("A2A Agent as Team Member")
    print("=" * 60)
    print("\nThis demonstrates using RemoteAgent with A2A protocol")
    print("to include agents from other frameworks as team members.\n")
    print("Make sure agno_a2a_server.py is running on port 7779:")
    print("  python cookbook/05_agent_os/remote/agno_a2a_server.py\n")

    response = await research_team.arun(
        "Research the Pythagorean theorem and calculate 3^2 + 4^2",
        stream=False,
    )
    print(response.content)


if __name__ == "__main__":
    asyncio.run(main())
