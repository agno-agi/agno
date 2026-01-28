from agno.agent import Agent
from agno.models.moonshot import MoonShot
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=MoonShot(id="kimi-k2-thinking"),
    markdown=True,
    tools=[WebSearchTools()],
)

agent.print_response("What is happening in France?", stream=True)
