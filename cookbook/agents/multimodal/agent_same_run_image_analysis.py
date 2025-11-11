from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.dalle import DalleTools

# Create an Agent with the DALL-E tool
agent = Agent(
    model=OpenAIChat(id="gpt-4.1"), tools=[DalleTools()], name="DALL-E Image Generator"
)

response = agent.run(
    "Generate an image of a dog and tell what color the dog is.",
    markdown=True,
    debug_mode=True,
)

if response.images:
    print("Agent Response", response.content)
    print(response.images[0].url)
