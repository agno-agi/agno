from dataclasses import replace
from typing import Iterator

from agno.agent import Agent
from agno.agent.metrics import SessionMetrics
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.team.team import Team
from agno.tools.hackernews import HackerNewsTools
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


def test_member_metrics_aggregation():
    """Test the metrics of all members' are aggregated correctly."""

    memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")
    memory = Memory(db=memory_db)

    stock_agent = Agent(
        session_id="session-1",
        name="Stock Agent",
        model=OpenAIChat("gpt-4o"),
        memory=memory,
        role="Get stock information",
        tools=[YFinanceTools(stock_price=True)],
    )

    company_info_agent = Agent(
        session_id="session-1",
        name="Company Info Agent",
        model=OpenAIChat("gpt-4o"),
        memory=memory,
        role="Get company information from HackerNews",
        tools=[HackerNewsTools()],
    )

    team = Team(
        session_id="session-1",
        name="Company Research Team",
        mode="collaborate",
        model=OpenAIChat("gpt-4o"),
        members=[stock_agent, company_info_agent],
    )

    # Running the team twice to make sure the metrics are aggregated correctly for multiple runs
    team.run(
        "I need information on NVIDIA. Let me know if there are any active Hackernews thread about it, and what is its current stock price."
    )
    team.run(
        "I need information on TSLA. Let me know if there are any active Hackernews thread about it, and what is its current stock price."
    )

    # Aggregating metrics for all team members' runs
    members_metrics = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for member in team.members:
        assert isinstance(member.memory, Memory)
        if member.memory.runs is not None:
            for runs in member.memory.runs.values():
                for run in runs:
                    if run is not None and run.messages is not None:
                        for m in run.messages:
                            if m.role == "assistant" and m.metrics is not None:
                                members_metrics["input_tokens"] += m.metrics.input_tokens
                                members_metrics["output_tokens"] += m.metrics.output_tokens
                                members_metrics["total_tokens"] += m.metrics.total_tokens

    # Asserting team.full_team_session_metrics coincides with our aggregated metrics
    assert team.full_team_session_metrics is not None
    assert team.session_metrics is not None
    assert (
        team.full_team_session_metrics.input_tokens
        == members_metrics["input_tokens"] + team.session_metrics.input_tokens
    )
    assert (
        team.full_team_session_metrics.output_tokens
        == members_metrics["output_tokens"] + team.session_metrics.output_tokens
    )
    assert (
        team.full_team_session_metrics.total_tokens
        == members_metrics["total_tokens"] + team.session_metrics.total_tokens
    )


def test_team_metrics_with_history():
    """Test session metrics are correctly aggregated when history is enabled"""

    agent = Agent()
    team = Team(
        members=[agent],
        enable_team_history=True,
        storage=SqliteStorage(table_name="team_metrics_tests", db_file="tmp/team-metrics-tests.db"),
    )

    team.run("Hi")
    assert team.session_metrics is not None
    assert team.run_response.metrics is not None
    assert team.run_response.metrics["input_tokens"] is not None
    # Check the session metrics (team.session_metrics) coincide with the sum of run metrics
    assert sum(team.run_response.metrics["input_tokens"]) == team.session_metrics.input_tokens
    assert sum(team.run_response.metrics["output_tokens"]) == team.session_metrics.output_tokens
    assert sum(team.run_response.metrics["total_tokens"]) == team.session_metrics.total_tokens

    # Checking metrics aggregation works with multiple runs
    team.run("Hi")
    assert team.session_metrics is not None
    assert team.run_response.metrics is not None
    assert team.run_response.metrics["input_tokens"] is not None
    # Check the session metrics (team.session_metrics) coincide with the sum of run metrics
    assert sum(team.run_response.metrics["input_tokens"]) == team.session_metrics.input_tokens
    assert sum(team.run_response.metrics["output_tokens"]) == team.session_metrics.output_tokens
    assert sum(team.run_response.metrics["total_tokens"]) == team.session_metrics.total_tokens
