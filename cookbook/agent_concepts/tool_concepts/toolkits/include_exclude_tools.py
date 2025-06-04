import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        CalculatorTools(
            enable_all=True,
            exclude_tools=["exponentiate", "factorial", "is_prime", "square_root"],
        ),
        DuckDuckGoTools(include_tools=["duckduckgo_search"]),
    ],
    show_tool_calls=True,
)

asyncio.run(
    agent.aprint_response(
        "Search the web for a difficult sum that can be done with normal arithmetic and solve it.",
        markdown=True,
    )
)
