"""Tests for nested-run metrics propagation in teams: a workflow streamed from
inside a team's custom tool must roll up into the team's run and session
metrics."""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.tools import tool
from agno.workflow import Step, Workflow


@pytest.mark.asyncio
async def test_workflow_in_team_tool_stream(shared_db):
    inner_workflow = Workflow(
        name="doc-workflow",
        steps=[
            Step(
                name="summarize",
                agent=Agent(name="Summarizer", model=OpenAIChat(id="gpt-4o-mini"), instructions="Answer in 3 words."),
            ),
        ],
    )

    async def process_documents(task: str):
        """Process documents through the internal workflow.

        Args:
            task: What to process.
        """
        async for event in inner_workflow.arun(input=task, stream=True, stream_events=True):
            yield event

    team = Team(
        name="DocTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[Agent(name="Helper", model=OpenAIChat(id="gpt-4o-mini"), instructions="Answer in 3 words.")],
        tools=[process_documents],
        instructions="Call process_documents with the user's request. Then reply in 5 words.",
        db=shared_db,
    )

    response = await team.arun("Summarize: the sky is blue.")

    leader_own = sum(
        m.metrics.total_tokens for m in (response.messages or []) if m.role == "assistant" and m.metrics is not None
    )
    member_total = sum(r.metrics.total_tokens for r in (response.member_responses or []) if r.metrics)
    workflow_total = response.metrics.total_tokens - leader_own

    # The nested workflow's tokens must be part of the team run metrics
    assert workflow_total > 0

    # Session metrics count the run (including nested workflow) and members exactly once
    session = team.get_session(session_id=response.session_id)
    session_metrics = session.session_data.get("session_metrics", {})
    assert session_metrics.get("total_tokens") == response.metrics.total_tokens + member_total


def test_nested_run_in_continued_team_stream_by_run_id(shared_db):
    """A nested agent run by a tool during a streamed HITL continuation (by
    run_id) must roll up into the continued run's metrics."""
    nested_run_tokens = []

    @tool(requires_confirmation=True)
    def get_order_status(order_id: str) -> str:
        """Get the status of an order.

        Args:
            order_id: The order id.
        """
        return "Order is shipped."

    def ask_specialist(question: str) -> str:
        """Ask the specialist a question. Call this after get_order_status.

        Args:
            question: The question.
        """
        specialist = Agent(model=OpenAIChat(id="gpt-4o-mini"), instructions="Answer in 3 words.")
        result = specialist.run(question)
        nested_run_tokens.append(result.metrics.total_tokens)
        return str(result.content)

    team = Team(
        name="OrderTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        tools=[get_order_status, ask_specialist],
        instructions=(
            "Use get_order_status first. After it returns, you MUST ask the specialist "
            "for the delivery outlook using the ask_specialist tool. Then answer in one sentence."
        ),
        db=shared_db,
    )

    run_output = team.run("What is the status of order 42 and its delivery outlook?")
    assert run_output.is_paused
    for req in run_output.requirements or []:
        if req.tool_execution is not None:
            req.tool_execution.confirmed = True

    response = None
    for event in team.continue_run(
        run_id=run_output.run_id,
        requirements=run_output.requirements,
        session_id=run_output.session_id,
        stream=True,
        yield_run_output=True,
    ):
        if isinstance(event, TeamRunOutput):
            response = event

    nested = sum(nested_run_tokens)
    own = sum(
        m.metrics.total_tokens for m in (response.messages or []) if m.role == "assistant" and m.metrics is not None
    )
    assert nested > 0, "nested run did not execute"
    assert response.metrics.total_tokens == own + nested
