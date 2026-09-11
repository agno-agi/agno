"""
Microsoft 365 Copilot Interface for Agno

This interface enables Microsoft 365 Copilot and Copilot Studio to invoke
Agno agents, teams, and workflows as specialized sub-agents.

Usage:
    from agno.os import AgentOS
    from agno.os.interfaces.m365 import M365Copilot
    from agno.agent import Agent

    agent = Agent(name="Financial Analyst", instructions="...")
    os = AgentOS(
        agents=[agent],
        interfaces=[M365Copilot(agent=agent)]
    )
"""

from agno.os.interfaces.m365.m365 import M365Copilot

__all__ = ["M365Copilot"]
