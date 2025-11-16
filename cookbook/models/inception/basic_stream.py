from agno.agent import Agent
from agno.models.inception import Inception

agent = Agent(
    model=Inception(id="mercury"),
    markdown=True,
)

# Print the response in the terminal
agent.print_response("What is a diffusion model?", stream=True)
