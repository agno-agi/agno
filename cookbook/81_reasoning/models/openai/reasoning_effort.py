from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=OpenAIChat(id="o3-mini", reasoning_effort="high"),
    tools=[WebSearchTools(enable_news=False)],
    instructions="Use tables to display data.",
    markdown=True,
)

agent.print_response("Write a report comparing NVDA to TSLA", stream=True)
