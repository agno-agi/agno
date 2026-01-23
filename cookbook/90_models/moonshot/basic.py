from agno.agent import Agent
from agno.models.n1n import N1N

agent = Agent(model=N1N(id="kimi-k2-thinking"), markdown=True)

agent.print_response("Share a 2 sentence horror story.")
