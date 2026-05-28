"""
AgentOps Integration
====================

Demonstrates logging Agno model calls with AgentOps.
"""

import agentops
from agno.agent import Agent
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Initialize AgentOps
agentops.init()


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(model=OpenAIChat(id="gpt-4o"))


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = agent.run("Share a 2 sentence horror story")
    print(response.content)
