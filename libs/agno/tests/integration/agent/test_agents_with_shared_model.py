import pytest

from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat


@pytest.fixture(scope="session")
def shared_model():
    return OpenAIChat(id="gpt-4o-mini")


@pytest.fixture
def web_agent(shared_model):
    """Create a web agent for testing."""
    from agno.tools.duckduckgo import DuckDuckGoTools

    return Agent(
        name="Web Agent",
        model=shared_model,
        role="Search the web for information",
        tools=[DuckDuckGoTools(cache_results=True)],
    )


@pytest.fixture
def finance_agent(shared_model):
    """Create a finance agent for testing."""
    from agno.tools.yfinance import YFinanceTools

    return Agent(
        name="Finance Agent",
        model=shared_model,
        role="Get financial data",
        tools=[YFinanceTools(stock_price=True)],
    )


def test_tools_available_to_agents(web_agent, finance_agent):
    finance_agent.run("What is the current stock price of AAPL?")

    assert list(finance_agent.model._functions.keys()) == [
        "get_current_stock_price",
    ]

    web_agent.run("What is currently happening in the news?")
    assert list(web_agent.model._functions.keys()) == [
        "duckduckgo_search",
        "duckduckgo_news",
    ]
