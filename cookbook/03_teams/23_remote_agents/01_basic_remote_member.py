"""
Remote Agent as Team Member
===========================

This cookbook demonstrates using a RemoteAgent as a team member.
A RemoteAgent connects to an agent running on a remote AgentOS server,
enabling distributed agent architectures.

Requirements:
    - A running AgentOS server that mounts the RemoteAccess interface and passes the
      agent to it. Start the backing server from the remote cookbook:
        python cookbook/05_agent_os/remote/server.py

Key Points:
    - RemoteAgent only supports async methods (arun, aprint_response)
    - Teams with RemoteAgent members MUST use async team methods
    - Only agents opted into the RemoteAccess interface are remotely callable
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
        model=OpenAIResponses(id="gpt-5.5"),
        instructions="You summarize information concisely in 2-3 sentences.",
    )

    # 2. Create a RemoteAgent pointing to a remote AgentOS server
    # The remote server must expose this agent through its Remote interface
    remote_researcher = RemoteAgent(
        base_url="http://localhost:7778",  # Your AgentOS server URL
        agent_id="researcher-agent",  # ID of the agent on the remote server
        timeout=60.0,  # Request timeout in seconds
    )

    # 3. Create a team with both local and remote agents
    team = Team(
        name="Hybrid Research Team",
        model=OpenAIResponses(id="gpt-5.5"),
        members=[summarizer, remote_researcher],
        instructions="""\
You are a research team leader. You have access to:
- Summarizer: Summarizes information concisely
- Researcher: Researches topics on the web (runs remotely)

Delegate research tasks to Researcher, then have Summarizer condense the findings.""",
        show_members_responses=True,
    )

    # 4. Use the team with async methods (required for RemoteAgent)
    print("Testing hybrid team with remote agent...")
    print("=" * 60)

    await team.aprint_response(
        "Use Researcher to find out what Agno is, then have Summarizer give me a one-line summary.",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
