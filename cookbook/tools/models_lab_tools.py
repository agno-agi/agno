"""Run `pip install requests` to install dependencies."""

from agno.agent import Agent
from agno.tools.models_labs import ModelsLabTools

# Create an Agent with the ModelsLabs tool
agent = Agent(tools=[ModelsLabTools()], name="ModelsLabs Agent")

agent.print_response(
    "Generate a video of a beautiful sunset over the ocean", markdown=True
)
