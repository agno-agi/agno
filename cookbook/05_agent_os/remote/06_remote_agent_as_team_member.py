"""
Example demonstrating how to use RemoteAgent as a Team member.

This shows how to include agents from another AgentOS server as members
in a local Team, enabling cross-service agent orchestration.

Prerequisites:
1. Start the server:
   python cookbook/05_agent_os/remote/server.py

   The server will run on http://localhost:7778

2. Set your OPENAI_API_KEY environment variable
"""

import asyncio

from agno.agent import Agent, RemoteAgent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Local Member
# ---------------------------------------------------------------------------

local_summarizer = Agent(
    name="Summarizer",
    role="You synthesize information into clear, concise summaries.",
    model=OpenAIResponses(id="gpt-5-mini"),
)

# ---------------------------------------------------------------------------
# Create Remote Members
# ---------------------------------------------------------------------------

remote_assistant = RemoteAgent(
    base_url="http://localhost:7778",
    agent_id="assistant-agent",
)

remote_researcher = RemoteAgent(
    base_url="http://localhost:7778",
    agent_id="researcher-agent",
)

# ---------------------------------------------------------------------------
# Create Team with Local + Remote Members
# ---------------------------------------------------------------------------

hybrid_team = Team(
    name="Hybrid Research Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[
        local_summarizer,
        remote_assistant,
        remote_researcher,
    ],
    instructions=[
        "You lead a hybrid team with local and remote agents.",
        "Delegate math questions to the remote Assistant.",
        "Delegate research questions to the remote Researcher.",
        "Use the local Summarizer for final synthesis.",
    ],
    markdown=True,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(
        hybrid_team.aprint_response(
            "Calculate 15 * 23, then summarize what multiplication is.",
            stream=True,
        )
    )
