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

def test_tools_available_to_agents(route_team, web_agent, finance_agent):
   
    # Team interaction with user 1 - Session 1
    route_team.run("What is the current stock price of AAPL?")
    
    assert route_team.model._functions == [
        "forward_task_to_member",
    ]
    
    assert web_agent.model._functions == [
        "search_web",
    ]
    
    assert finance_agent.model._functions == [
        "get_stock_price",
    ]