from agno.agent import Agent
from agno.tools.dalle import DalleTools

# Create an Agent with the DALL-E tool
agent = Agent(tools=[DalleTools()], name="DALL-E Image Generator")

agent.print_response(
    "Generate an image of a dog and tell what color the dog is.",
    markdown=True,
    debug_mode=True,
)

