import pytest

from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team


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


@pytest.fixture
def analysis_agent(shared_model):
    """Create an analysis agent for testing."""
    return Agent(name="Analysis Agent", model=shared_model, role="Analyze data and provide insights")


@pytest.fixture
def route_team(web_agent, finance_agent, analysis_agent, shared_model):
    """Create a route team with storage and memory for testing."""
    return Team(
        name="Route Team",
        mode="route",
        model=shared_model,
        members=[web_agent, finance_agent, analysis_agent],
        enable_user_memories=True,
    )


def test_tools_available_to_agents(route_team, shared_model):
    route_team.run("What is the current stock price of AAPL?")

    # Since the finance model was called last, the model should only have the finance functions
    assert list(shared_model._functions.keys()) == [
        "get_current_stock_price",
    ]

    route_team.run("What is currently happening in the news?")

    # Since the web model was called last, the model should only have the web functions
    assert list(shared_model._functions.keys()) == [
        "duckduckgo_search",
        "duckduckgo_news",
    ]
