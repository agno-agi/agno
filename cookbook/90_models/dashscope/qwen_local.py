"""Qwen Local Deployment - Universal Example"""

from agno.agent import Agent
from agno.models.dashscope import DashScope
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

MODEL_ID = "qwen2.5-3b-instruct"
BASE_URL = "http://localhost:1234/v1"


def main():
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        tools=[DuckDuckGoTools(), YFinanceTools()],
        markdown=True,
    )

    agent.print_response("Explain quantum computing in simple terms")
    agent.print_response("What is Apple's current stock price?")
    agent.print_response("Search for AI news and get Tesla stock price")


if __name__ == "__main__":
    main()
