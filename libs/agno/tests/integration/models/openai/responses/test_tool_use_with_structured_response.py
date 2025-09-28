import enum
from typing import Dict, List

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools


class StockAnalysis(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    current_price: float = Field(..., description="Current stock price")
    recommendation: str = Field(..., description="Buy/Sell/Hold recommendation")
    risk_level: str = Field(..., description="High/Medium/Low risk assessment")
    target_price: float = Field(..., description="12-month target price")


class MovieScript(BaseModel):
    setting: str = Field(..., description="Provide a nice setting for a blockbuster movie.")
    ending: str = Field(..., description="Ending of the movie. If not available, provide a happy ending.")
    genre: str = Field(
        ..., description="Genre of the movie. If not available, select action, thriller or romantic comedy."
    )
    name: str = Field(..., description="Give a name to this movie")
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(..., description="3 sentence storyline for the movie. Make it exciting!")
    rating: Dict[str, int] = Field(
        ..., description="Your own rating of the movie. 1-10. Return a dictionary with the keys 'story' and 'acting'."
    )


class Priority(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskAnalysis(BaseModel):
    task_name: str = Field(..., description="Name of the task")
    priority: Priority
    estimated_hours: int = Field(..., description="Estimated hours to complete")
    dependencies: List[str] = Field(..., description="List of dependencies")


def test_tool_use_with_structured_output_tool_use():
    """Test tool use combined with structured output for stock analysis."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        output_schema=StockAnalysis,
        telemetry=False,
    )

    response = agent.run("Analyze AAPL stock and provide a recommendation")

    # Verify structured output
    assert response.content is not None
    assert isinstance(response.content, StockAnalysis)
    assert response.content.symbol == "AAPL"
    assert response.content.current_price > 0
    assert response.content.recommendation in ["Buy", "Sell", "Hold"]
    assert response.content.risk_level in ["High", "Medium", "Low"]
    assert response.content.target_price > 0

    # Verify tool usage occurred
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)


@pytest.mark.asyncio
async def test_async_tool_use_with_structured_output():
    """Test tool use combined with structured output for movie script generation."""

    async def get_movie_inspiration(genre: str) -> str:
        """Get inspiration for a movie script based on genre."""
        inspirations = {
            "action": "High-octane chase scenes through bustling cities",
            "thriller": "Psychological mind games and unexpected plot twists",
            "romantic comedy": "Meet-cute scenarios in charming locations",
        }
        return inspirations.get(genre.lower(), "Creative storytelling with compelling characters")

    async def get_character_suggestions(genre: str, setting: str) -> str:
        """Get character suggestions based on genre and setting."""
        return f"For a {genre} movie set in {setting}, consider: protagonist with mysterious past, antagonist with hidden motives, supporting character with local knowledge"

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[get_movie_inspiration, get_character_suggestions],
        output_schema=MovieScript,
        telemetry=False,
    )

    response = await agent.arun("Create a thriller movie script set in Tokyo")

    # Verify structured output
    assert response.content is not None
    assert isinstance(response.content, MovieScript)
    assert response.content.setting is not None
    assert response.content.genre is not None
    assert response.content.name is not None
    assert isinstance(response.content.characters, list)
    assert len(response.content.characters) > 0
    assert response.content.storyline is not None
    assert isinstance(response.content.rating, dict)
    assert "story" in response.content.rating
    assert "acting" in response.content.rating

    # Verify tool usage occurred
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)


def test_tool_use_with_structured_output_enum_fields():
    """Test tool use with structured output containing enum fields."""

    def analyze_project_requirements(project_type: str) -> str:
        """Analyze project requirements and complexity."""
        return f"Project type {project_type} requires: frontend development, API integration, database design, testing"

    def estimate_task_complexity(task_description: str) -> str:
        """Estimate the complexity of a given task."""
        return f"Task '{task_description}' is medium complexity, requires 8-12 hours, depends on database schema"

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[analyze_project_requirements, estimate_task_complexity],
        output_schema=TaskAnalysis,
        telemetry=False,
    )

    response = agent.run("Analyze the task of building a user authentication system for a web application")

    # Verify structured output with enum
    assert response.content is not None
    assert isinstance(response.content, TaskAnalysis)
    assert response.content.task_name is not None
    assert isinstance(response.content.priority, Priority)
    assert response.content.estimated_hours > 0
    assert isinstance(response.content.dependencies, list)

    # Verify tool usage occurred
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)


def test_multiple_tool_calls_with_structured_output():
    """Test multiple tool calls combined with structured output."""

    def get_stock_price(symbol: str) -> str:
        """Get current stock price."""
        prices = {"AAPL": "150.25", "GOOGL": "2500.75", "MSFT": "300.50"}
        return f"Current price of {symbol}: ${prices.get(symbol, '100.00')}"

    def get_market_sentiment(symbol: str) -> str:
        """Get market sentiment for a stock."""
        sentiments = {"AAPL": "Bullish", "GOOGL": "Neutral", "MSFT": "Bullish"}
        return f"Market sentiment for {symbol}: {sentiments.get(symbol, 'Neutral')}"

    def get_analyst_rating(symbol: str) -> str:
        """Get analyst rating for a stock."""
        ratings = {"AAPL": "Buy", "GOOGL": "Hold", "MSFT": "Strong Buy"}
        return f"Analyst rating for {symbol}: {ratings.get(symbol, 'Hold')}"

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[get_stock_price, get_market_sentiment, get_analyst_rating],
        output_schema=StockAnalysis,
        telemetry=False,
    )

    response = agent.run("Provide a comprehensive analysis of AAPL stock")

    # Verify structured output
    assert response.content is not None
    assert isinstance(response.content, StockAnalysis)
    assert response.content.symbol == "AAPL"
    assert response.content.current_price > 0
    assert response.content.recommendation in ["Buy", "Sell", "Hold", "Strong Buy"]
    assert response.content.risk_level in ["High", "Medium", "Low"]

    # Verify multiple tool calls occurred
    assert response.messages is not None
    tool_call_messages = [msg for msg in response.messages if msg.tool_calls is not None]
    assert len(tool_call_messages) > 0
    total_tool_calls = sum(len(msg.tool_calls) for msg in tool_call_messages)
    assert total_tool_calls >= 2  # Should have made multiple tool calls


def test_tool_use_with_structured_output_stream():
    """Test streaming tool use combined with structured output."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        output_schema=StockAnalysis,
        telemetry=False,
    )

    response_stream = agent.run(
        "Analyze TSLA stock and provide a recommendation", stream=True, stream_intermediate_steps=True
    )

    responses = []
    tool_call_seen = False
    final_content = None

    for event in response_stream:
        responses.append(event)

        # Check for tool call events
        if event.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(event, "tool") and event.tool:  # type: ignore
            if event.tool.tool_name:  # type: ignore
                tool_call_seen = True

        # Capture final structured content
        if hasattr(event, "content") and event.content is not None and isinstance(event.content, StockAnalysis):
            final_content = event.content

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"

    # Verify final structured output
    assert final_content is not None
    assert isinstance(final_content, StockAnalysis)
    assert final_content.symbol == "TSLA"
    assert final_content.current_price > 0
    assert final_content.recommendation in ["Buy", "Sell", "Hold"]
    assert final_content.risk_level in ["High", "Medium", "Low"]


@pytest.mark.asyncio
async def test_async_tool_use_with_structured_output_stream():
    """Test async streaming tool use combined with structured output."""

    async def get_market_data(symbol: str) -> str:
        """Get market data for a stock symbol."""
        return f"Market data for {symbol}: Price $180.50, Volume 1.2M, P/E ratio 28.5"

    async def get_news_sentiment(symbol: str) -> str:
        """Get news sentiment for a stock."""
        return f"News sentiment for {symbol}: Positive outlook, strong earnings expected"

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[get_market_data, get_news_sentiment],
        output_schema=StockAnalysis,
        telemetry=False,
    )

    responses = []
    tool_call_seen = False
    final_content = None

    async for event in agent.arun(
        "Analyze NVDA stock using market data and news sentiment", stream=True, stream_intermediate_steps=True
    ):
        responses.append(event)

        # Check for tool call events
        if event.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(event, "tool") and event.tool:  # type: ignore
            if event.tool.tool_name:  # type: ignore
                tool_call_seen = True

        # Capture final structured content
        if hasattr(event, "content") and event.content is not None and isinstance(event.content, StockAnalysis):
            final_content = event.content

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in async stream"

    # Verify final structured output
    assert final_content is not None
    assert isinstance(final_content, StockAnalysis)
    assert final_content.symbol == "NVDA"
    assert final_content.current_price > 0
    assert final_content.recommendation in ["Buy", "Sell", "Hold"]
    assert final_content.risk_level in ["High", "Medium", "Low"]
