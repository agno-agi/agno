from agno.agent import Agent
from agno.models.zai import ZAI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=ZAI(id="glm-4.6"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
agent.print_response("What's happening in AI today?", stream=True)
