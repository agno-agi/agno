"""
Compose AgentOS and A2A RemoteAgents in one Team
================================================

A local Team can coordinate remote members reached through different
protocols. Delegating to every member makes both network hops visible in one
run.

Prerequisites: start `servers/agentos_server.py` and `servers/a2a_server.py`; set OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/20_remote/04_remote_as_team_member.py
Try: inspect the two recorded member responses after the Team answer
"""

import asyncio

from agno.agent import RemoteAgent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Remote Members
# ---------------------------------------------------------------------------

agentos_member = RemoteAgent(
    base_url="http://127.0.0.1:7780",
    agent_id="researcher-agent",
)

a2a_member = RemoteAgent(
    base_url="http://127.0.0.1:7781/a2a/agents/a2a-assistant",
    agent_id="a2a-assistant",
    protocol="a2a",
    a2a_protocol="rest",
)

# ---------------------------------------------------------------------------
# Create Hybrid Team
# ---------------------------------------------------------------------------

hybrid_team = Team(
    id="hybrid-remote-team",
    name="Hybrid Remote Team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[agentos_member, a2a_member],
    instructions=[
        "Ask every remote member to answer the user's request.",
        "Synthesize their answers and identify which transport reached each member.",
    ],
    delegate_to_all_members=True,
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Hybrid Team
# ---------------------------------------------------------------------------


async def run_hybrid_team() -> None:
    """Run both remote members and verify their responses were retained."""
    response = await hybrid_team.arun(
        "Explain one benefit of composing remote Agents, then calculate 12 times 8.",
    )
    if len(response.member_responses) != 2:
        raise RuntimeError("Expected one response from each remote member")

    print(f"Team run: {response.run_id}")
    print(f"Remote member responses: {len(response.member_responses)}")
    print(response.content)


if __name__ == "__main__":
    asyncio.run(run_hybrid_team())
