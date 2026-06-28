"""
Remote Agent as Team Member
===========================

This cookbook demonstrates using a RemoteAgent as a team member.
A RemoteAgent connects to an agent running on a remote AgentOS server,
enabling distributed agent architectures.

Requirements:
    - A running AgentOS server (e.g., `python -m agno.os --agents my_agent.py`)
    - The remote agent must be registered on the server

Key Points:
    - RemoteAgent only supports async methods (arun, aprint_response)
    - Teams with RemoteAgent members MUST use async team methods
    - Supports both AgentOS protocol and A2A (Agent-to-Agent) protocol
"""

import asyncio

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.models.openai import OpenAIResponses
from agno.team.team import Team


async def main():
    # 1. Create a local agent
    summarizer = Agent(
        name="Summarizer",
        model=OpenAIResponses(id="gpt-4o-mini"),
        instructions="You summarize information concisely in 2-3 sentences.",
    )

    # 2. Create a RemoteAgent pointing to a remote AgentOS server
    # Replace with your actual remote server URL and agent ID
    remote_explorer = RemoteAgent(
        base_url="http://localhost:7777",  # Your AgentOS server URL
        agent_id="explorer",  # ID of the agent on the remote server
        timeout=60.0,  # Request timeout in seconds
    )

    # 3. Create a team with both local and remote agents
    team = Team(
        name="Hybrid Research Team",
        model=OpenAIResponses(id="gpt-4o-mini"),
        members=[summarizer, remote_explorer],
        instructions="""\
You are a research team leader. You have access to:
- Summarizer: Summarizes information concisely
- Explorer: Explores codebases and finds information (runs remotely)

Delegate code exploration tasks to Explorer, then have Summarizer condense the findings.""",
        show_members_responses=True,
    )

    # 4. Use the team with async methods (required for RemoteAgent)
    print("Testing hybrid team with remote agent...")
    print("=" * 60)

    await team.aprint_response(
        "Use Explorer to find out what the main programming language is in the repo, "
        "then have Summarizer give me a one-line summary.",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
