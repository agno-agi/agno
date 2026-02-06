from agno.agent import Agent
from agno.models.moonshot import MoonShot

agent = Agent(model=MoonShot(id="kimi-k2-thinking"), markdown=True)

agent.print_response("Share a 2 sentence horror story.", stream=True)
