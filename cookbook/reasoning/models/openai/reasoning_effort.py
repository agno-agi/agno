from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="o3-mini", reasoning_effort="high"),
    tools=[DuckDuckGoTools(enable_search=True)],
    instructions="Use tables to display data.",
    markdown=True,
)

agent.print_response("Write a report comparing NVDA to TSLA", stream=True)
