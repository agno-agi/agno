from agno.agent import Agent
from agno.tools.dalle import DalleTools

# Create an Agent with the DALL-E tool
agent = Agent(tools=[DalleTools()], name="DALL-E Image Generator")

response = agent.run(
    "Generate an image of a dog and tell what color the dog is.",
    markdown=True,
    debug_mode=True,
)

if response.images:
    print("Agent Response", response.content)
    print(response.images[0].url)
