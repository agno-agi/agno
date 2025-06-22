from unittest.mock import patch

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
    with patch.object(finance_agent.model, "invoke", wraps=finance_agent.model.invoke) as mock_invoke:
        finance_agent.run("What is the current stock price of AAPL?")

        # Get the tools passed to invoke
        tools = mock_invoke.call_args[1].get("tools", [])
        tool_names = [tool["function"]["name"] for tool in tools]
        assert tool_names == ["get_current_stock_price"]

    with patch.object(web_agent.model, "invoke", wraps=web_agent.model.invoke) as mock_invoke:
        web_agent.run("What is currently happening in the news?")

        # Get the tools passed to invoke
        tools = mock_invoke.call_args[1].get("tools", [])
        tool_names = [tool["function"]["name"] for tool in tools]
        assert tool_names == ["duckduckgo_search", "duckduckgo_news"]
