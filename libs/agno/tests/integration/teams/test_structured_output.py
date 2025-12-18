import pytest
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
        tools=[YFinanceTools(include_tools=["get_current_stock_price"])],
    )

    news_agent = Agent(
        name="News Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get company news",
        tools=[YFinanceTools(include_tools=["get_company_news"])],
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
        delegate_to_all_members=True,
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


def test_team_with_json_schema():
    """Test team with JSON schema as output_schema."""

    analysis_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "StockAnalysis",
            "schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Stock ticker symbol"},
                    "company_name": {"type": "string", "description": "Company name"},
                    "analysis": {"type": "string", "description": "Brief analysis"},
                },
                "required": ["symbol", "company_name", "analysis"],
                "additionalProperties": False,
            },
        },
    }

    stock_agent = Agent(
        name="Stock Analyst",
        model=OpenAIChat("gpt-4o-mini"),
        role="Provides stock analysis",
    )

    team = Team(
        name="Analysis Team",
        model=OpenAIChat("gpt-4o-mini"),
        members=[stock_agent],
        output_schema=analysis_schema,
        markdown=False,
    )

    response = team.run("Analyze NVDA stock briefly")

    # Verify response structure
    assert response.content is not None
    assert isinstance(response.content, dict)
    assert response.content_type == "dict"

    # Verify all required fields are present
    assert "symbol" in response.content
    assert "company_name" in response.content
    assert "analysis" in response.content

    # Verify field types are correct
    assert isinstance(response.content["symbol"], str)
    assert isinstance(response.content["company_name"], str)
    assert isinstance(response.content["analysis"], str)

    # Verify fields have actual content
    assert len(response.content["symbol"]) > 0
    assert len(response.content["company_name"]) > 0
    assert len(response.content["analysis"]) > 0


@pytest.mark.asyncio
async def test_team_arun_with_json_schema():
    """Test team with JSON schema using async run."""

    analysis_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "StockAnalysis",
            "schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Stock ticker symbol"},
                    "company_name": {"type": "string", "description": "Company name"},
                    "analysis": {"type": "string", "description": "Brief analysis"},
                },
                "required": ["symbol", "company_name", "analysis"],
                "additionalProperties": False,
            },
        },
    }

    stock_agent = Agent(
        name="Stock Analyst",
        model=OpenAIChat("gpt-4o-mini"),
        role="Provides stock analysis",
    )

    team = Team(
        name="Analysis Team",
        model=OpenAIChat("gpt-4o-mini"),
        members=[stock_agent],
        output_schema=analysis_schema,
        markdown=False,
    )

    response = await team.arun("Analyze AAPL stock briefly")

    # Verify response structure
    assert response.content is not None
    assert isinstance(response.content, dict)
    assert response.content_type == "dict"

    # Verify all required fields are present
    assert "symbol" in response.content
    assert "company_name" in response.content
    assert "analysis" in response.content

    # Verify field types are correct
    assert isinstance(response.content["symbol"], str)
    assert isinstance(response.content["company_name"], str)
    assert isinstance(response.content["analysis"], str)

    # Verify fields have actual content
    assert len(response.content["symbol"]) > 0
    assert len(response.content["company_name"]) > 0
    assert len(response.content["analysis"]) > 0


def test_team_delegate_to_all_with_json_schema():
    """Test collaborate team with JSON schema."""

    debate_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "DebateResult",
            "schema": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The debate topic"},
                    "conclusion": {"type": "string", "description": "Final conclusion"},
                },
                "required": ["topic", "conclusion"],
                "additionalProperties": False,
            },
        },
    }

    agent1 = Agent(name="Pro", model=OpenAIChat("gpt-4o-mini"), role="Argues in favor")
    agent2 = Agent(name="Con", model=OpenAIChat("gpt-4o-mini"), role="Argues against")

    team = Team(
        name="Debate Team",
        delegate_to_all_members=True,
        model=OpenAIChat("gpt-4o-mini"),
        members=[agent1, agent2],
        instructions=["Get perspectives from both agents and summarize."],
        output_schema=debate_schema,
    )

    response = team.run("Should AI be regulated?")

    # Verify response structure
    assert response.content is not None
    assert isinstance(response.content, dict)
    assert response.content_type == "dict"

    # Verify all required fields are present
    assert "topic" in response.content
    assert "conclusion" in response.content

    # Verify field types are correct
    assert isinstance(response.content["topic"], str)
    assert isinstance(response.content["conclusion"], str)

    # Verify fields have actual content
    assert len(response.content["topic"]) > 0
    assert len(response.content["conclusion"]) > 0

    # Verify member responses were collected (delegate_to_all_members=True)
    assert len(response.member_responses) >= 1


@pytest.mark.asyncio
async def test_team_arun_delegate_to_all_with_json_schema():
    """Test collaborate team with JSON schema using async run."""

    debate_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "DebateResult",
            "schema": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The debate topic"},
                    "conclusion": {"type": "string", "description": "Final conclusion"},
                },
                "required": ["topic", "conclusion"],
                "additionalProperties": False,
            },
        },
    }

    agent1 = Agent(name="Pro", model=OpenAIChat("gpt-4o-mini"), role="Argues in favor")
    agent2 = Agent(name="Con", model=OpenAIChat("gpt-4o-mini"), role="Argues against")

    team = Team(
        name="Debate Team",
        delegate_to_all_members=True,
        model=OpenAIChat("gpt-4o-mini"),
        members=[agent1, agent2],
        instructions=["Get perspectives from both agents and summarize."],
        output_schema=debate_schema,
    )

    response = await team.arun("Should autonomous vehicles be allowed?")

    # Verify response structure
    assert response.content is not None
    assert isinstance(response.content, dict)
    assert response.content_type == "dict"

    # Verify all required fields are present
    assert "topic" in response.content
    assert "conclusion" in response.content

    # Verify field types are correct
    assert isinstance(response.content["topic"], str)
    assert isinstance(response.content["conclusion"], str)

    # Verify fields have actual content
    assert len(response.content["topic"]) > 0
    assert len(response.content["conclusion"]) > 0

    # Verify member responses were collected (delegate_to_all_members=True)
    assert len(response.member_responses) >= 1
