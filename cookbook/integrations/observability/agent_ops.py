"""
This example shows how to use agentops to log model calls.

Steps to get started with agentops:
1. Install agentops: pip install agentops
2. Obtain an API key from https://app.agentops.ai/
3. Export environment variables like AGENTOPS_API_KEY and OPENAI_API_KEY.
4. Run the script.

You can view the logs in the AgentOps dashboard: https://app.agentops.ai/
"""

import agentops
from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Initialize AgentOps
agentops.init()

# Create and run an agent
agent = Agent(model=OpenAIChat(id="gpt-4o"))
response = agent.run("Share a 2 sentence horror story")

# Print the response
print(response.content)
