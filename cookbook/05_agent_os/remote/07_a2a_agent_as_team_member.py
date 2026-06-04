"""
Example demonstrating how to use a remote A2A agent as a Team member.

This shows how to include agents from an A2A-compatible server as members
in a local Team, enabling cross-framework agent orchestration.

Prerequisites:
1. Install A2A SDK:
   pip install a2a-sdk

2. Start the A2A server:
   python cookbook/05_agent_os/remote/agno_a2a_server.py

   The server will run on http://localhost:7779

3. Set your OPENAI_API_KEY environment variable
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
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # RemoteAgent only supports async (arun), so use aprint_response
    asyncio.run(
        research_team.aprint_response(
            "Research the Pythagorean theorem and calculate 3^2 + 4^2",
            stream=True,
        )
    )
