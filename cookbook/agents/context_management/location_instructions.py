from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    add_location_to_context=True,
    tools=[DuckDuckGoTools(cache_results=True)],
)
agent.print_response("What city am I in?")
agent.print_response("What is current news about my city?")
