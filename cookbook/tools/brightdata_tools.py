from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.brightdata import BrightDataTools

agent = Agent(
    tools=[BrightDataTools(search_engine=True, web_data_feed=True)],
    show_tool_calls=True,
    model=OpenAIChat(id="gpt-4o-mini"),
    debug_mode=True,
)
agent.print_response(
    "Search Amazon data feed for the following product : https://www.amazon.com/dp/B0D2Q9397Y?th=1&psc=1",
    markdown=True,
    show_full_reasoning=True,
)
