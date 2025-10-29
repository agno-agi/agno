from typing import Iterator

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools


def test_team_metrics_basic(shared_db):
    """Test basic team metrics functionality."""

    stock_agent = Agent(
        name="Stock Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get stock information",
        tools=[YFinanceTools()],
    )

    team = Team(
        name="Stock Research Team",
        model=OpenAIChat("gpt-4o"),
        members=[stock_agent],
        db=shared_db,
        store_member_responses=True,
    )

    response = team.run("What is the current stock price of AAPL?")

    # Verify response metrics exist
    assert response.metrics is not None

    # Check basic metrics
    assert response.metrics.input_tokens is not None
    assert response.metrics.output_tokens is not None
    assert response.metrics.total_tokens is not None

    # Check member response metrics
    assert len(response.member_responses) == 1
    member_response = response.member_responses[0]
    assert member_response.metrics is not None
    assert member_response.metrics.input_tokens is not None
    assert member_response.metrics.output_tokens is not None
    assert member_response.metrics.total_tokens is not None

    # Check session metrics
    session_from_db = team.get_session(session_id=team.session_id)
    assert session_from_db is not None and session_from_db.session_data is not None
    assert session_from_db.session_data["session_metrics"]["input_tokens"] is not None
    assert session_from_db.session_data["session_metrics"]["output_tokens"] is not None
    assert session_from_db.session_data["session_metrics"]["total_tokens"] is not None


def test_team_metrics_streaming(shared_db):
    """Test team metrics with streaming."""

    stock_agent = Agent(
        name="Stock Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get stock information",
        tools=[YFinanceTools()],
    )

    team = Team(
        name="Stock Research Team",
        model=OpenAIChat("gpt-4o"),
        members=[stock_agent],
        db=shared_db,
        store_member_responses=True,
    )

    # Run with streaming
    run_stream = team.run("What is the stock price of NVDA?", stream=True)
    assert isinstance(run_stream, Iterator)

    # Consume the stream
    responses = list(run_stream)
    assert len(responses) > 0

    run_response = team.get_last_run_output()

    # Verify metrics exist after stream completion
    assert run_response is not None
    assert run_response.metrics is not None

    # Basic metrics checks
    assert run_response.metrics.input_tokens is not None
    assert run_response.metrics.output_tokens is not None
    assert run_response.metrics.total_tokens is not None


def test_team_metrics_multiple_runs(shared_db):
    """Test team metrics across multiple runs."""

    stock_agent = Agent(
        name="Stock Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get stock information",
        tools=[YFinanceTools()],
    )

    team = Team(
        name="Stock Research Team",
        model=OpenAIChat("gpt-4o"),
        members=[stock_agent],
        db=shared_db,
    )

    # First run
    response = team.run("What is the current stock price of AAPL?")

    # Capture metrics after first run
    assert response is not None
    assert response.metrics is not None
    assert response.metrics.total_tokens > 0

    # Second run
    team.run("What is the current stock price of MSFT?")

    # Verify metrics have been updated after second run
    session_from_db = team.get_session(session_id=team.session_id)
    assert session_from_db is not None and session_from_db.session_data is not None
    assert session_from_db.session_data["session_metrics"]["total_tokens"] > response.metrics.total_tokens


def test_team_metrics_with_history(shared_db):
    """Test session metrics are correctly aggregated when history is enabled"""

    agent = Agent()
    team = Team(
        members=[agent],
        add_history_to_context=True,
        db=shared_db,
    )

    team.run("Hi")
    run_response = team.get_last_run_output()
    assert run_response is not None
    assert run_response.metrics is not None
    assert run_response.metrics.input_tokens is not None

    session_from_db = team.get_session(session_id=team.session_id)

    # Check the session metrics (team.session_metrics) coincide with the sum of run metrics
    assert session_from_db is not None and session_from_db.session_data is not None
    assert run_response.metrics.input_tokens == session_from_db.session_data["session_metrics"]["input_tokens"]
    assert run_response.metrics.output_tokens == session_from_db.session_data["session_metrics"]["output_tokens"]
    assert run_response.metrics.total_tokens == session_from_db.session_data["session_metrics"]["total_tokens"]

    # Checking metrics aggregation works with multiple runs
    team.run("Hi")
    run_response = team.get_last_run_output()
    assert run_response is not None
    assert run_response.metrics is not None
    assert run_response.metrics.input_tokens is not None

    session_from_db = team.get_session(session_id=team.session_id)

    # run metrics are less than session metrics because we add the history to the context
    assert session_from_db is not None and session_from_db.session_data is not None
    assert run_response.metrics.input_tokens < session_from_db.session_data["session_metrics"]["input_tokens"]
    assert run_response.metrics.output_tokens < session_from_db.session_data["session_metrics"]["output_tokens"]
    assert run_response.metrics.total_tokens < session_from_db.session_data["session_metrics"]["total_tokens"]
