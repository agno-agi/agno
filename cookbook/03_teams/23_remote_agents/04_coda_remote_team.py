"""
Coda Remote Team
================

This cookbook demonstrates using multiple RemoteAgents from a single
AgentOS server (Coda) as team members.

Coda is a code companion that lives in Slack. It has specialized agents:
- Explorer: Searches code, traces flows, reviews PRs
- Researcher: Researches topics using web search
- Coder: Writes and modifies code
- Planner: Creates implementation plans
- Triager: Triages issues and categorizes work

Requirements:
    - A running Coda instance (or any AgentOS server with multiple agents)
    - Update CODA_URL to point to your server

To run Coda locally:
    cd /path/to/coda
    python -m app.main
"""

import asyncio

from agno.agent.remote import RemoteAgent
from agno.models.openai import OpenAIResponses
from agno.team.team import Team

# Public Coda instance for testing (no auth required)
# For production, run your own Coda server with authentication enabled
CODA_URL = "https://coda-production-26ad.up.railway.app"


async def main():
    # Create RemoteAgents for each Coda agent
    explorer = RemoteAgent(
        base_url=CODA_URL,
        agent_id="explorer",
        timeout=120.0,
    )

    researcher = RemoteAgent(
        base_url=CODA_URL,
        agent_id="researcher",
        timeout=120.0,
    )

    coder = RemoteAgent(
        base_url=CODA_URL,
        agent_id="coder",
        timeout=120.0,
    )

    planner = RemoteAgent(
        base_url=CODA_URL,
        agent_id="planner",
        timeout=120.0,
    )

    triager = RemoteAgent(
        base_url=CODA_URL,
        agent_id="triager",
        timeout=120.0,
    )

    # Create a team with all remote agents
    team = Team(
        name="Coda Development Team",
        model=OpenAIResponses(id="gpt-4o-mini"),
        members=[explorer, researcher, coder, planner, triager],
        instructions="""\
You lead a remote development team powered by Coda. Each member runs on the Coda server:

- Explorer: Search code, trace execution flows, review PRs, analyze repos
- Researcher: Research topics, find documentation, search the web
- Coder: Write code, implement features, fix bugs
- Planner: Create implementation plans, break down tasks
- Triager: Triage issues, categorize work, prioritize tasks

Delegate tasks to the appropriate specialist. For complex tasks, use multiple agents.""",
        show_members_responses=True,
    )

    print("Testing Coda Remote Team...")
    print(f"Connected to: {CODA_URL}")
    print("=" * 60)

    await team.aprint_response(
        "Have Explorer find the main entry point of the agno repo, "
        "then have Planner outline what it would take to add a new feature.",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
