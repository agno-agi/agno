from agno.agent import Agent
from agno.models.n1n import N1N

agent = Agent(model=N1N(id="gpt-4o"), markdown=True)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story.")
