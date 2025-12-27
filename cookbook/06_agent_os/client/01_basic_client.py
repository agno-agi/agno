"""
Basic AgentOSClient Example

This example demonstrates how to use AgentOSClient to connect to
a remote AgentOS instance and perform basic operations.

Prerequisites:
1. Start an AgentOS server:
   python -c "
   from agno.agent import Agent
   from agno.models.openai import OpenAIChat
   from agno.os import AgentOS

   agent = Agent(
       name='Assistant',
       model=OpenAIChat(id='gpt-4o-mini'),
       instructions='You are a helpful assistant.',
   )
   agent_os = AgentOS(agents=[agent])
   agent_os.serve()
   "

2. Run this script: python 01_basic_client.py
"""

import asyncio

from agno.client import AgentOSClient


async def main():
    # Connect to AgentOS using async context manager
    client = AgentOSClient(base_url="http://localhost:7777")
    # Get AgentOS configuration
    config = await client.aget_config()
    print(f"Connected to: {config.name or config.os_id}")
    print(f"Available agents: {[a.id for a in (config.agents or [])]}")
    print(f"Available teams: {[t.id for t in (config.teams or [])]}")
    print(f"Available workflows: {[w.id for w in (config.workflows or [])]}")

    # Get details about a specific agent
    if config.agents:
        agent_id = config.agents[0].id
        agent = await client.aget_agent(agent_id)
        print("\nAgent Details:")
        print(f"  Name: {agent.name}")
        print(f"  Model: {agent.model}")
        print(f"  Tools: {len(agent.tools or [])}")


if __name__ == "__main__":
    asyncio.run(main())
