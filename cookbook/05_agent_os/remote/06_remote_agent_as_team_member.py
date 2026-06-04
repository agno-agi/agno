"""
Remote Agent as Team Member
===========================

Demonstrates using RemoteAgent to include external agents as members
in a local Team. This enables cross-framework agent collaboration where
your Team can delegate to agents running on:
- Another Agno AgentOS instance
- Google ADK (via A2A protocol)
- LangGraph (via A2A protocol)
- Any A2A-compatible agent server

This is the Agno equivalent of Google ADK's RemoteA2aAgent pattern:
    prime_agent = RemoteA2aAgent(
        name="prime_agent",
        agent_card="http://localhost:8001/a2a/.../.well-known/agent.json"
    )
    root_agent = Agent(sub_agents=[roll_agent, prime_agent])

Prerequisites:
1. Start the server:
   python cookbook/05_agent_os/remote/server.py  (port 7778)

2. Set OPENAI_API_KEY
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

# Connect to agents running on server.py (port 7778)
# Uses AgentOS protocol (Agno's native REST API)
remote_assistant = RemoteAgent(
    base_url="http://localhost:7778",
    agent_id="assistant-agent",
    protocol="agentos",
)

remote_researcher = RemoteAgent(
    base_url="http://localhost:7778",
    agent_id="researcher-agent",
    protocol="agentos",
)

# ---------------------------------------------------------------------------
# Create Team with Local + Remote Members
# ---------------------------------------------------------------------------

hybrid_team = Team(
    name="Hybrid Research Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[
        local_summarizer,   # Local agent
        remote_assistant,   # Remote agent (server.py)
        remote_researcher,  # Remote agent (server.py)
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
# Run Examples
# ---------------------------------------------------------------------------


async def basic_example():
    """Team delegates to remote agents."""
    print("Hybrid Team - Basic Delegation:")
    print("-" * 50)

    response = await hybrid_team.arun(
        "Calculate 15 * 23, then summarize what multiplication is.",
        stream=False,
    )
    print(response.content)


async def streaming_example():
    """Stream responses when team delegates to remote members."""
    print("\nHybrid Team - Streaming:")
    print("-" * 50)

    async for chunk in hybrid_team.arun(
        "Calculate 7 * 8 and then summarize the result in one sentence.",
        stream=True,
    ):
        if hasattr(chunk, "content") and chunk.content:
            print(chunk.content, end="", flush=True)
    print()


async def main():
    print("=" * 60)
    print("Remote Agent as Team Member")
    print("=" * 60)
    print("\nThis demonstrates using RemoteAgent to include agents")
    print("from another AgentOS server as team members.\n")
    print("Make sure server.py is running on port 7778:")
    print("  python cookbook/05_agent_os/remote/server.py\n")

    await basic_example()
    await streaming_example()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())
