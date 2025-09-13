from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools


def test_output_schemas_on_members():
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
        output_schema=StockAnalysis,
        role="Searches for information on stocks and provides price analysis.",
        tools=[YFinanceTools(include_tools=["get_current_stock_price", "get_analyst_recommendations"])],
    )

    company_info_agent = Agent(
        name="Company Info Searcher",
        model=OpenAIChat("gpt-4o"),
        role="Searches for general information about companies and recent news.",
        output_schema=CompanyAnalysis,
        tools=[
            YFinanceTools(
                include_tools=[
                    "get_company_info",
                    "get_company_news",
                ]
            )
        ],
    )

    team = Team(
        name="Stock Research Team",
        model=OpenAIChat("gpt-4o"),
        members=[stock_searcher, company_info_agent],
        respond_directly=True,
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
    assert response.member_responses[0].agent_id == stock_searcher.id  # type: ignore

    # This should route to the company_info_agent
    response = team.run("What is in the news about NVDA?")

    assert response.content is not None
    assert isinstance(response.content, CompanyAnalysis)
    assert response.content.company_name is not None
    assert response.content.analysis is not None
    assert len(response.member_responses) == 1
    assert response.member_responses[0].agent_id == company_info_agent.id  # type: ignore


def test_mixed_structured_output():
    """Test route team with mixed structured and unstructured outputs."""

    class StockInfo(BaseModel):
        symbol: str
        price: float

    stock_agent = Agent(
        name="Stock Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get stock information",
        output_schema=StockInfo,
        tools=[YFinanceTools()],
    )

    news_agent = Agent(
        name="News Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get company news",
        tools=[YFinanceTools()],
    )

    team = Team(
        name="Financial Research Team",
        model=OpenAIChat("gpt-4o"),
        members=[stock_agent, news_agent],
        respond_directly=True,
    )

    # This should route to the stock_agent and return  structured output
    response = team.run("Get the current price of AAPL?")

    assert response.content is not None
    assert isinstance(response.content, StockInfo)
    assert response.content.symbol == "AAPL"
    assert response.member_responses[0].agent_id == stock_agent.id  # type: ignore

    # This should route to the news_agent and return unstructured output
    response = team.run("Tell me the latest news about AAPL")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert response.member_responses[0].agent_id == news_agent.id  # type: ignore


def test_delegate_to_all_members_with_structured_output():
    """Test collaborate team with structured output."""
    from pydantic import BaseModel

    class DebateResult(BaseModel):
        topic: str
        perspective_one: str
        perspective_two: str
        conclusion: str

    agent1 = Agent(name="Perspective One", model=OpenAIChat("gpt-4o"), role="First perspective provider")

    agent2 = Agent(name="Perspective Two", model=OpenAIChat("gpt-4o"), role="Second perspective provider")

    team = Team(
        name="Debate Team",
        delegate_task_to_all_members=True,
        model=OpenAIChat("gpt-4o"),
        members=[agent1, agent2],
        instructions=[
            "Have both agents provide their perspectives on the topic.",
            "Synthesize their views into a balanced conclusion.",
            "Only ask the members once for their perspectives.",
        ],
        output_schema=DebateResult,
    )

    response = team.run("Is artificial general intelligence possible in the next decade?")

    assert response.content is not None
    assert isinstance(response.content, DebateResult)
    assert response.content.topic is not None
    assert response.content.perspective_one is not None
    assert response.content.perspective_two is not None
    assert response.content.conclusion is not None
