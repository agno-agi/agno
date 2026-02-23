from typing import Iterator

import pytest

from agno.agent import Agent
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.metrics import ModelMetrics, RunMetrics, SessionMetrics, ToolCallMetrics
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunOutput
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools


def add(a: int, b: int) -> str:
    """Add two numbers."""
    return str(a + b)


def multiply(a: int, b: int) -> str:
    """Multiply two numbers."""
    return str(a * b)


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


def test_team_metrics_details_structure():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(model=OpenAIChat(id="gpt-4o-mini"), members=[member])
    response = team.run("Say hello.")

    assert response.metrics is not None
    assert isinstance(response.metrics, RunMetrics)
    assert response.metrics.total_tokens > 0
    assert response.metrics.details is not None
    assert "model" in response.metrics.details

    model_metrics = response.metrics.details["model"]
    assert len(model_metrics) >= 1
    assert isinstance(model_metrics[0], ModelMetrics)


@pytest.mark.asyncio
async def test_team_metrics_details_structure_async():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(model=OpenAIChat(id="gpt-4o-mini"), members=[member])
    response = await team.arun("Say hello.")

    assert response.metrics is not None
    assert response.metrics.total_tokens > 0
    assert "model" in response.metrics.details
    assert isinstance(response.metrics.details["model"][0], ModelMetrics)


def test_team_metrics_details_sum_matches_total():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(model=OpenAIChat(id="gpt-4o-mini"), members=[member])
    response = team.run("What is 2+2?")

    detail_total = sum(entry.total_tokens for entries in response.metrics.details.values() for entry in entries)
    assert detail_total == response.metrics.total_tokens


def test_team_member_metrics():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Researcher")
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        store_member_responses=True,
        delegate_to_all_members=True,
    )
    response = team.run("Research the impact of AI on healthcare.")

    assert len(response.member_responses) > 0
    member_response = response.member_responses[0]
    assert member_response.metrics is not None
    assert member_response.metrics.total_tokens > 0


@pytest.mark.asyncio
async def test_team_member_metrics_async():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Researcher", role="Answer questions")
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        store_member_responses=True,
        delegate_to_all_members=True,
    )
    response = await team.arun("Ask Researcher to explain photosynthesis briefly.")

    assert len(response.member_responses) > 0
    member_response = response.member_responses[0]
    assert member_response.metrics is not None
    assert member_response.metrics.total_tokens > 0


def test_team_member_metrics_fields():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        store_member_responses=True,
        delegate_to_all_members=True,
    )
    response = team.run("Say hi.")

    if response.member_responses:
        member_response = response.member_responses[0]
        if member_response.metrics and member_response.metrics.details and "model" in member_response.metrics.details:
            model_metric = member_response.metrics.details["model"][0]
            assert isinstance(model_metric, ModelMetrics)
            assert model_metric.id is not None
            assert model_metric.provider is not None
            assert model_metric.total_tokens > 0


def test_team_eval_metrics_sync():
    eval_hook = AgentAsJudgeEval(
        name="Team Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be helpful",
        scoring_strategy="binary",
    )
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        post_hooks=[eval_hook],
    )
    response = team.run("What is the capital of France?")

    assert "model" in response.metrics.details
    assert "eval_model" in response.metrics.details
    assert sum(metric.total_tokens for metric in response.metrics.details["eval_model"]) > 0

    detail_total = sum(entry.total_tokens for entries in response.metrics.details.values() for entry in entries)
    assert detail_total == response.metrics.total_tokens


@pytest.mark.asyncio
async def test_team_eval_metrics_async():
    eval_hook = AgentAsJudgeEval(
        name="Async Team Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be accurate",
        scoring_strategy="binary",
    )
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        post_hooks=[eval_hook],
    )
    response = await team.arun("What is 5+3?")

    assert "eval_model" in response.metrics.details
    assert sum(metric.total_tokens for metric in response.metrics.details["eval_model"]) > 0

    detail_total = sum(entry.total_tokens for entries in response.metrics.details.values() for entry in entries)
    assert detail_total == response.metrics.total_tokens


def test_team_eval_metrics_streaming():
    eval_hook = AgentAsJudgeEval(
        name="Stream Team Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be concise",
        scoring_strategy="binary",
    )
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        post_hooks=[eval_hook],
    )

    final = None
    for event in team.run("Say hi.", stream=True, yield_run_output=True):
        if isinstance(event, TeamRunOutput):
            final = event

    assert final is not None
    assert "eval_model" in final.metrics.details

    detail_total = sum(entry.total_tokens for entries in final.metrics.details.values() for entry in entries)
    assert detail_total == final.metrics.total_tokens


def test_team_eval_metrics_numeric_scoring():
    eval_hook = AgentAsJudgeEval(
        name="Numeric Team Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Rate the response quality",
        scoring_strategy="numeric",
        threshold=5,
    )
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        post_hooks=[eval_hook],
    )
    response = team.run("Explain gravity.")

    assert "eval_model" in response.metrics.details
    assert sum(metric.total_tokens for metric in response.metrics.details["eval_model"]) > 0


def test_team_tool_call_metrics_sync():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Calculator", tools=[add])
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        store_member_responses=True,
    )
    response = team.run("Use the Calculator to add 15 and 27.")

    if response.member_responses and response.member_responses[0].tools:
        tool = response.member_responses[0].tools[0]
        assert isinstance(tool.metrics, ToolCallMetrics)
        assert tool.metrics.duration > 0


@pytest.mark.asyncio
async def test_team_tool_call_metrics_async():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Calculator", tools=[add])
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        store_member_responses=True,
    )
    response = await team.arun("Use the Calculator to add 10 and 20.")

    if response.member_responses and response.member_responses[0].tools:
        tool = response.member_responses[0].tools[0]
        assert isinstance(tool.metrics, ToolCallMetrics)
        assert tool.metrics.duration > 0


def test_team_tool_call_metrics_multiple_tools():
    member = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        name="Calculator",
        tools=[add, multiply],
    )
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        store_member_responses=True,
    )
    response = team.run("Add 2 and 3, then multiply 4 and 5. Use the Calculator.")

    if response.member_responses and response.member_responses[0].tools:
        for tool in response.member_responses[0].tools:
            assert isinstance(tool.metrics, ToolCallMetrics)
            assert tool.metrics.duration > 0


def test_team_provider_metrics_openai():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(model=OpenAIChat(id="gpt-4o-mini"), members=[member])
    response = team.run("Hello")

    model_metric = response.metrics.details["model"][0]
    assert model_metric.provider == "OpenAI"
    assert model_metric.id == "gpt-4o-mini"
    assert model_metric.input_tokens > 0
    assert model_metric.total_tokens > 0


def test_team_provider_metrics_gemini():
    from agno.models.google import Gemini

    member = Agent(model=Gemini(id="gemini-2.5-flash"), name="Helper")
    team = Team(model=Gemini(id="gemini-2.5-flash"), members=[member])
    response = team.run("Hello")

    model_metric = response.metrics.details["model"][0]
    assert model_metric.provider == "Google"
    assert model_metric.id == "gemini-2.5-flash"
    assert model_metric.input_tokens > 0
    assert model_metric.total_tokens > 0


def test_team_session_metrics_type(shared_db):
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(model=OpenAIChat(id="gpt-4o-mini"), members=[member], db=shared_db)
    team.run("First task.")
    team.run("Second task.")

    session_metrics = team.get_session_metrics()
    assert isinstance(session_metrics, SessionMetrics)
    assert session_metrics.total_tokens > 0
    assert isinstance(session_metrics.details, dict)
    assert len(session_metrics.details) > 0
    for model_type, metrics_list in session_metrics.details.items():
        assert isinstance(metrics_list, list)
        for metric in metrics_list:
            assert isinstance(metric, ModelMetrics)


@pytest.mark.asyncio
async def test_team_session_metrics_async(shared_db):
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(model=OpenAIChat(id="gpt-4o-mini"), members=[member], db=shared_db)
    await team.arun("First async task.")
    await team.arun("Second async task.")

    session_metrics = team.get_session_metrics()
    assert isinstance(session_metrics, SessionMetrics)
    assert session_metrics.total_tokens > 0


def test_team_session_metrics_with_eval(shared_db):
    eval_hook = AgentAsJudgeEval(
        name="Session Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be helpful",
        scoring_strategy="binary",
    )
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        post_hooks=[eval_hook],
        db=shared_db,
    )
    response1 = team.run("What is 2+2?")
    response2 = team.run("What is 3+3?")

    assert "eval_model" in response1.metrics.details
    assert "eval_model" in response2.metrics.details

    session_metrics = team.get_session_metrics()
    assert session_metrics.total_tokens > 0


def test_team_session_metrics_run_independence(shared_db):
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(model=OpenAIChat(id="gpt-4o-mini"), members=[member], db=shared_db)

    response1 = team.run("Say hello.")
    response2 = team.run("Say goodbye.")

    assert response1.metrics.total_tokens > 0
    assert response2.metrics.total_tokens > 0

    session_metrics = team.get_session_metrics()
    assert session_metrics.total_tokens >= response1.metrics.total_tokens + response2.metrics.total_tokens


def test_team_streaming_metrics():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(model=OpenAIChat(id="gpt-4o-mini"), members=[member])

    final = None
    for event in team.run("Tell me a joke.", stream=True, yield_run_output=True):
        if isinstance(event, TeamRunOutput):
            final = event

    assert final is not None
    assert final.metrics.total_tokens > 0
    assert final.metrics.details is not None


def test_team_streaming_metrics_with_tools():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Calculator", tools=[add])
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        store_member_responses=True,
    )

    final = None
    for event in team.run("Add 3 and 7 using Calculator.", stream=True, yield_run_output=True):
        if isinstance(event, TeamRunOutput):
            final = event

    assert final is not None
    assert final.metrics.total_tokens > 0


def test_team_eval_plus_tools():
    eval_hook = AgentAsJudgeEval(
        name="Tool Team Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should include the computed result",
        scoring_strategy="binary",
    )
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Calculator", tools=[add])
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        post_hooks=[eval_hook],
        store_member_responses=True,
    )
    response = team.run("Add 7 and 8 using Calculator.")

    assert "model" in response.metrics.details
    assert "eval_model" in response.metrics.details

    detail_total = sum(entry.total_tokens for entries in response.metrics.details.values() for entry in entries)
    assert detail_total == response.metrics.total_tokens


def test_team_eval_duration_tracked():
    eval_hook = AgentAsJudgeEval(
        name="Duration Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be factually correct",
        scoring_strategy="binary",
    )
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        post_hooks=[eval_hook],
    )
    response = team.run("What is the capital of France?")

    assert response.metrics.additional_metrics is not None
    assert "eval_duration" in response.metrics.additional_metrics
    assert response.metrics.additional_metrics["eval_duration"] > 0


def test_team_no_eval_key_without_eval():
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(model=OpenAIChat(id="gpt-4o-mini"), members=[member])
    response = team.run("Hello")

    assert "model" in response.metrics.details
    assert "eval_model" not in response.metrics.details


def test_team_detail_keys_reset_between_runs():
    eval_hook = AgentAsJudgeEval(
        name="Reset Test",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be correct",
        scoring_strategy="binary",
    )
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"), name="Helper")
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        post_hooks=[eval_hook],
    )

    team.run("What is 1+1?")
    response2 = team.run("What is 2+2?")

    assert "eval_model" in response2.metrics.details
    assert sum(metric.total_tokens for metric in response2.metrics.details["eval_model"]) > 0
