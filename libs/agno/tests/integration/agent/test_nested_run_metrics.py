"""Tests for nested-run metrics propagation: agent/team/workflow runs started
inside custom tools must roll up into the parent run's metrics."""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.team import Team


def _own_usage(run_output: RunOutput) -> int:
    return sum(
        m.metrics.total_tokens for m in (run_output.messages or []) if m.role == "assistant" and m.metrics is not None
    )


def _make_ask_specialist(nested_run_tokens):
    def ask_specialist(question: str) -> str:
        """Ask the specialist agent a question.

        Args:
            question: The question for the specialist.
        """
        specialist = Agent(model=OpenAIChat(id="gpt-4o-mini"), instructions="Answer in 3 words.")
        result = specialist.run(question)
        nested_run_tokens.append(result.metrics.total_tokens)
        return str(result.content)

    return ask_specialist


def _make_aask_specialist(nested_run_tokens):
    async def aask_specialist(question: str) -> str:
        """Ask the specialist agent a question.

        Args:
            question: The question for the specialist.
        """
        specialist = Agent(model=OpenAIChat(id="gpt-4o-mini"), instructions="Answer in 3 words.")
        result = await specialist.arun(question)
        nested_run_tokens.append(result.metrics.total_tokens)
        return str(result.content)

    return aask_specialist


def _assert_propagated(run_output: RunOutput, nested_run_tokens):
    nested = sum(nested_run_tokens)
    assert nested > 0, "nested run did not execute"
    assert run_output.metrics.total_tokens == _own_usage(run_output) + nested


def test_nested_agent_in_tool():
    nested_run_tokens = []
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[_make_ask_specialist(nested_run_tokens)],
        instructions="Use the ask_specialist tool to answer. Then reply in 3 words.",
    )
    response = agent.run("What is the capital of France? Use your tool.")
    _assert_propagated(response, nested_run_tokens)


def test_nested_agent_in_tool_stream():
    nested_run_tokens = []
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[_make_ask_specialist(nested_run_tokens)],
        instructions="Use the ask_specialist tool to answer. Then reply in 3 words.",
    )
    response = None
    for event in agent.run("What is the capital of Japan? Use your tool.", stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            response = event
    _assert_propagated(response, nested_run_tokens)


@pytest.mark.asyncio
async def test_nested_agent_in_tool_async():
    nested_run_tokens = []
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[_make_aask_specialist(nested_run_tokens)],
        instructions="Use the aask_specialist tool to answer. Then reply in 3 words.",
    )
    response = await agent.arun("What is the capital of Italy? Use your tool.")
    _assert_propagated(response, nested_run_tokens)


@pytest.mark.asyncio
async def test_nested_agent_in_tool_async_stream():
    nested_run_tokens = []
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[_make_aask_specialist(nested_run_tokens)],
        instructions="Use the aask_specialist tool to answer. Then reply in 3 words.",
    )
    response = None
    async for event in agent.arun("What is the capital of Spain? Use your tool.", stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            response = event
    _assert_propagated(response, nested_run_tokens)


def test_nested_team_in_tool():
    """A team run inside a tool reports leader + member metrics to the parent."""
    nested_run_tokens = []

    def consult_team(question: str) -> str:
        """Consult the research team.

        Args:
            question: The question for the team.
        """
        member = Agent(name="M1", model=OpenAIChat(id="gpt-4o-mini"), instructions="Answer in 3 words.")
        nested_team = Team(
            name="NestedTeam",
            model=OpenAIChat(id="gpt-4o-mini"),
            members=[member],
            instructions="You MUST always delegate the task to member M1. Never answer directly.",
        )
        result = nested_team.run(question)
        leader_tokens = result.metrics.total_tokens if result.metrics else 0
        member_tokens = sum(r.metrics.total_tokens for r in (result.member_responses or []) if r.metrics)
        nested_run_tokens.append(leader_tokens + member_tokens)
        return str(result.content)

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[consult_team],
        instructions="Use the consult_team tool, then reply in 3 words.",
    )
    response = agent.run("What color is the sky? Use your tool.")
    _assert_propagated(response, nested_run_tokens)


@pytest.mark.asyncio
async def test_background_run_includes_nested_metrics(shared_db):
    """A detached background run collects nested-run metrics into its own run."""
    import asyncio

    from agno.run.base import RunStatus

    nested_run_tokens = []
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[_make_ask_specialist(nested_run_tokens)],
        instructions="Use the ask_specialist tool to answer. Then reply in 3 words.",
        db=shared_db,
    )
    handle = await agent.arun("What is the capital of Brazil? Use your tool.", background=True)

    response = None
    for _ in range(60):
        await asyncio.sleep(2)
        polled = await agent.aget_run_output(run_id=handle.run_id, session_id=handle.session_id)
        if polled is not None and polled.status in (RunStatus.completed, RunStatus.error):
            response = polled
            break

    assert response is not None and response.status == RunStatus.completed
    _assert_propagated(response, nested_run_tokens)


def test_nested_run_metrics_in_session_metrics(shared_db):
    """Session metrics include the nested run's tokens exactly once."""
    nested_run_tokens = []
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[_make_ask_specialist(nested_run_tokens)],
        instructions="Use the ask_specialist tool to answer. Then reply in 3 words.",
        db=shared_db,
    )
    response = agent.run("What is the capital of Kenya? Use your tool.")
    _assert_propagated(response, nested_run_tokens)

    session = agent.get_session(session_id=response.session_id)
    session_metrics = session.session_data.get("session_metrics", {})
    assert session_metrics.get("total_tokens") == response.metrics.total_tokens
