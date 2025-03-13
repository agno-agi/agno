from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=OpenAIResponses(id="o3-mini", reasoning_effort="high"),
    tools=[YFinanceTools(enable_all=True)],
    show_tool_calls=True,
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Write a report on the NVDA, is it a good buy?", stream=True)
