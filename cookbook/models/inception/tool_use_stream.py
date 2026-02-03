from agno.agent import Agent
from agno.models.inception import Inception
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Inception(id="mercury"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
