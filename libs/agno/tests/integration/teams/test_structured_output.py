from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools


def test_route_team_multiple_response_models():
    """Test route team with different response models for each agent."""

    class StockAnalysis(BaseModel):
        symbol: str
        company_name: str
        analysis: str

    class CompanyAnalysis(BaseModel):
        company_name: str
        analysis: str

    stock_searcher = Agent(
        name="Stock Searcher",
        model=OpenAIChat("gpt-4o"),
        response_model=StockAnalysis,
        role="Searches for information on stocks and provides price analysis.",
        tools=[
            YFinanceTools(
                stock_price=True,
                analyst_recommendations=True,
            )
        ],
    )

    company_info_agent = Agent(
        name="Company Info Searcher",
        model=OpenAIChat("gpt-4o"),
        role="Searches for general information about companies and recent news.",
        response_model=CompanyAnalysis,
        tools=[
            YFinanceTools(
                stock_price=False,
                company_info=True,
                company_news=True,
            )
        ],
    )

    team = Team(
        name="Stock Research Team",
        mode="route",
        model=OpenAIChat("gpt-4o"),
        members=[stock_searcher, company_info_agent],
        markdown=True,
    )

    # This should route to the stock_searcher
    response = team.run("What is the current stock price of NVDA?")

    assert response.content is not None
    assert isinstance(response.content, StockAnalysis)
    assert response.content.symbol is not None
    assert response.content.company_name is not None
    assert response.content.analysis is not None
    assert len(response.member_responses) == 1
    assert response.member_responses[0].agent_id == stock_searcher.agent_id

    # This should route to the company_info_agent
    response = team.run("What is in the news about NVDA?")

    assert response.content is not None
    assert isinstance(response.content, CompanyAnalysis)
    assert response.content.company_name is not None
    assert response.content.analysis is not None
    assert len(response.member_responses) == 1
    assert response.member_responses[0].agent_id == company_info_agent.agent_id


def test_route_team_mixed_structured_output():
    """Test route team with mixed structured and unstructured outputs."""

    class StockInfo(BaseModel):
        symbol: str
        price: float

    stock_agent = Agent(
        name="Stock Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get stock information",
        response_model=StockInfo,
        tools=[YFinanceTools(stock_price=True)],
    )

    news_agent = Agent(
        name="News Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get company news",
        tools=[YFinanceTools(company_news=True)],
    )

    team = Team(
        name="Financial Research Team",
        mode="route",
        model=OpenAIChat("gpt-4o"),
        members=[stock_agent, news_agent],
    )

    # This should route to the stock_agent and return structured output
    response = team.run("Get the current price of AAPL?")

    assert response.content is not None
    assert isinstance(response.content, StockInfo)
    assert response.content.symbol == "AAPL"
    assert len(response.member_responses) == 1
    assert response.member_responses[0].agent_id == stock_agent.agent_id

    # This should route to the news_agent and return unstructured output
    response = team.run("Tell me the latest news about AAPL")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert len(response.member_responses) == 1
    assert response.member_responses[0].agent_id == news_agent.agent_id
