from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools

reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools()],
    instructions="Use tables to display data",
    use_json_mode=True,
    reasoning=True,
    markdown=True,
)
reasoning_agent.print_response(
    "Write a report comparing NVDA to TSLA", stream=True, show_full_reasoning=True
)
