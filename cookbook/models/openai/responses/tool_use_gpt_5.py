from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5"),
    tools=[YFinanceTools(cache_results=True)],
    show_tool_calls=True,
    markdown=True,
    telemetry=False,
    monitoring=False,
)

agent.print_response("What is the current price of TSLA?", stream=True)
