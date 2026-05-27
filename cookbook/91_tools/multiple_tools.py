"""Run `uv pip install openai ddgs yfinance` to install dependencies."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[WebSearchTools(), YFinanceTools()],
    instructions=["Use tables to display data"],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Write a thorough report on NVDA, get all financial information and latest news",
        stream=True,
    )
