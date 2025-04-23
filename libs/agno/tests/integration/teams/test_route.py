from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools


def test_route_team_basic():
    """Test basic functionality of a route team."""
    web_agent = Agent(
        name="Web Agent",
        model=OpenAIChat("gpt-4o"),
        role="Search the web for information",
        tools=[DuckDuckGoTools(cache_results=True)],
    )

    finance_agent = Agent(
        name="Finance Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get financial data",
        tools=[YFinanceTools(stock_price=True)],
    )

    team = Team(name="Router Team", mode="route", model=OpenAIChat("gpt-4o"), members=[web_agent, finance_agent])

    # This should route to the finance agent
    response = team.run("What is the current stock price of AAPL?")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert len(response.member_responses) == 1
    assert response.member_responses[0].agent_id == finance_agent.agent_id
    assert team.session_id is not None
    assert team.session_id == finance_agent.team_session_id


def test_route_team_structured_output():
    """Test basic functionality of a route team."""

    class StockInfo(BaseModel):
        symbol: str
        price: str

    web_agent = Agent(
        name="Web Agent",
        model=OpenAIChat("gpt-4o"),
        role="Search the web for information",
        tools=[DuckDuckGoTools(cache_results=True)],
    )

    finance_agent = Agent(
        name="Finance Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get financial data",
        response_model=StockInfo,
        tools=[YFinanceTools(stock_price=True)],
    )

    team = Team(name="Router Team", mode="route", model=OpenAIChat("gpt-4o"), members=[web_agent, finance_agent])

    # This should route to the finance agent
    response = team.run("What is the current stock price of AAPL?")

    assert response.content is not None
    assert isinstance(response.content, StockInfo)
    assert response.content.symbol is not None
    assert response.content.price is not None
    member_responses = response.member_responses
    assert len(member_responses) == 1
    assert response.member_responses[0].agent_id == finance_agent.agent_id


def test_route_team_with_multiple_agents():
    """Test route team routing to multiple agents."""
    web_agent = Agent(
        name="Web Agent",
        model=OpenAIChat("gpt-4o"),
        role="Search the web for information",
        tools=[DuckDuckGoTools(cache_results=True)],
    )

    finance_agent = Agent(
        name="Finance Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get financial data",
        tools=[YFinanceTools(stock_price=True)],
    )

    analysis_agent = Agent(name="Analysis Agent", model=OpenAIChat("gpt-4o"), role="Analyze data and provide insights")

    team = Team(
        name="Multi-Router Team",
        mode="route",
        model=OpenAIChat("gpt-4o"),
        members=[web_agent, finance_agent, analysis_agent],
    )

    # This should route to both finance and web agents
    response = team.run("Compare the stock performance of AAPL with recent tech industry news")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    # Should have routed to at least 2 agents
    assert len(response.member_responses) >= 2


def test_route_team_with_expected_output():
    """Test route team with expected output specification."""
    qa_agent = Agent(name="QA Agent", model=OpenAIChat("gpt-4o"), role="Answer general knowledge questions")

    math_agent = Agent(name="Math Agent", model=OpenAIChat("gpt-4o"), role="Solve mathematical problems")

    team = Team(
        name="Specialized Router Team", mode="route", model=OpenAIChat("gpt-4o"), members=[qa_agent, math_agent]
    )

    # This should route to the math agent with specific expected output
    response = team.run("Calculate the area of a circle with radius 5 units")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert len(response.member_responses) == 1
    assert response.member_responses[0].agent_id == math_agent.agent_id
