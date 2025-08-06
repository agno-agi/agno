from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    output_model=OpenAIChat(id="o3-mini"),
    tools=[DuckDuckGoTools()],
)

agent.print_response("Latest news from France?", stream=True)
