import pytest
from typing import List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools


def test_router_team_basic():
    """Test basic functionality of a router team."""
    web_agent = Agent(
        name="Web Agent",
        model=OpenAIChat("gpt-4o"),
        role="Search the web for information",
        tools=[DuckDuckGoTools()]
    )
    
    finance_agent = Agent(
        name="Finance Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get financial data",
        tools=[YFinanceTools(stock_price=True)]
    )
    
    team = Team(
        name="Router Team",
        mode="router",
        model=OpenAIChat("gpt-4o"),
        members=[web_agent, finance_agent]
    )
    
    # This should route to the finance agent
    response = team.run("What is the current stock price of AAPL?")
    
    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert len(response.member_responses) == 1
    assert response.member_responses[0].agent_id == finance_agent.agent_id


def test_router_team_with_multiple_agents():
    """Test router team routing to multiple agents."""
    web_agent = Agent(
        name="Web Agent",
        model=OpenAIChat("gpt-4o"),
        role="Search the web for information",
        tools=[DuckDuckGoTools()]
    )
    
    finance_agent = Agent(
        name="Finance Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get financial data",
        tools=[YFinanceTools(stock_price=True)]
    )
    
    analysis_agent = Agent(
        name="Analysis Agent",
        model=OpenAIChat("gpt-4o"),
        role="Analyze data and provide insights"
    )
    
    team = Team(
        name="Multi-Router Team",
        mode="router",
        model=OpenAIChat("gpt-4o"),
        members=[web_agent, finance_agent, analysis_agent]
    )
    
    # This should route to both finance and web agents
    response = team.run("Compare the stock performance of AAPL with recent tech industry news")
    
    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    # Should have routed to at least 2 agents
    assert len(response.member_responses) >= 2


def test_router_team_with_expected_output():
    """Test router team with expected output specification."""
    qa_agent = Agent(
        name="QA Agent",
        model=OpenAIChat("gpt-4o"),
        role="Answer general knowledge questions"
    )
    
    math_agent = Agent(
        name="Math Agent",
        model=OpenAIChat("gpt-4o"),
        role="Solve mathematical problems"
    )
    
    team = Team(
        name="Specialized Router Team",
        mode="router",
        model=OpenAIChat("gpt-4o"),
        members=[qa_agent, math_agent]
    )
    
    # This should route to the math agent with specific expected output
    response = team.run("Calculate the area of a circle with radius 5 units")
    
    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert len(response.member_responses) == 1
    assert response.member_responses[0].agent_id == math_agent.agent_id
    # The response should contain the answer (approximately 78.5)
    assert "78.5" in response.content or "78.54" in response.content 