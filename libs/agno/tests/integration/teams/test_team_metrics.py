from dataclasses import replace
from typing import Iterator

from agno.agent import Agent
from agno.agent.metrics import SessionMetrics
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools


def test_team_metrics_basic():
    """Test basic team metrics functionality."""

    stock_agent = Agent(
        name="Stock Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get stock information",
        tools=[YFinanceTools(stock_price=True)],
    )

    team = Team(
        name="Stock Research Team",
        mode="route",
        model=OpenAIChat("gpt-4o"),
        members=[stock_agent],
    )

    response = team.run("What is the current stock price of AAPL?")

    # Verify response metrics exist
    assert response.metrics is not None
    assert isinstance(response.metrics, dict)

    # Check basic metrics
    assert response.metrics["input_tokens"] is not None
    assert response.metrics["output_tokens"] is not None
    assert response.metrics["total_tokens"] is not None

    # Check member response metrics
    assert len(response.member_responses) == 1
    member_response = response.member_responses[0]
    assert member_response.metrics is not None
    assert isinstance(member_response.metrics, dict)
    assert member_response.metrics["input_tokens"] is not None
    assert member_response.metrics["output_tokens"] is not None
    assert member_response.metrics["total_tokens"] is not None

    # Check session metrics
    assert team.session_metrics is not None
    assert isinstance(team.session_metrics, SessionMetrics)
    assert team.session_metrics.input_tokens is not None
    assert team.session_metrics.output_tokens is not None
    assert team.session_metrics.total_tokens is not None

    # Check full team session metrics
    assert team.full_team_session_metrics is not None
    assert isinstance(team.full_team_session_metrics, SessionMetrics)
    assert team.full_team_session_metrics.input_tokens is not None
    assert team.full_team_session_metrics.output_tokens is not None
    assert team.full_team_session_metrics.total_tokens is not None


def test_team_metrics_streaming():
    """Test team metrics with streaming."""

    stock_agent = Agent(
        name="Stock Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get stock information",
        tools=[YFinanceTools(stock_price=True)],
    )

    team = Team(
        name="Stock Research Team",
        mode="route",
        model=OpenAIChat("gpt-4o"),
        members=[stock_agent],
    )

    # Run with streaming
    run_stream = team.run("What is the stock price of NVDA?", stream=True)
    assert isinstance(run_stream, Iterator)

    # Consume the stream
    responses = list(run_stream)
    assert len(responses) > 0

    # Verify metrics exist after stream completion
    assert team.run_response.metrics is not None
    assert isinstance(team.run_response.metrics, dict)

    # Basic metrics checks
    assert team.run_response.metrics["input_tokens"] is not None
    assert team.run_response.metrics["output_tokens"] is not None
    assert team.run_response.metrics["total_tokens"] is not None

    # Verify session metrics updated after streaming
    assert team.full_team_session_metrics is not None
    assert team.full_team_session_metrics.total_tokens > 0


def test_team_metrics_multiple_runs():
    """Test team metrics across multiple runs."""

    stock_agent = Agent(
        name="Stock Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get stock information",
        tools=[YFinanceTools(stock_price=True)],
    )

    team = Team(
        name="Stock Research Team",
        mode="route",
        model=OpenAIChat("gpt-4o"),
        members=[stock_agent],
    )

    # First run
    team.run("What is the current stock price of AAPL?")

    # Capture metrics after first run
    metrics_run1 = replace(team.session_metrics)
    assert metrics_run1.total_tokens > 0

    # Second run
    team.run("What is the current stock price of MSFT?")

    # Verify metrics have been updated after second run
    assert team.session_metrics.total_tokens > metrics_run1.total_tokens

    # Verify member metrics are tracked in full team metrics
    assert team.full_team_session_metrics.total_tokens >= team.session_metrics.total_tokens
