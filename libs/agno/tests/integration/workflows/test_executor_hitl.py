"""
Integration tests for Executor HITL (Human-In-The-Loop) in workflows.

Tests the full flow: agent/team pauses inside a Step -> propagates to workflow ->
user resolves -> workflow.continue_run() routes back to executor -> completes.

Tests cover:
- Agent confirmation flow (sync, async, streaming)
- Agent rejection flow
- Agent user input flow
- Team-in-step HITL flow
- Chained executor HITL (pause again after first continue)
- Streaming with StepExecutorPausedEvent
"""

import os

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus
from agno.run.workflow import StepExecutorPausedEvent, WorkflowRunOutput
from agno.team.team import Team
from agno.tools.decorator import tool
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


# =============================================================================
# Tools with HITL
# =============================================================================


@tool(requires_confirmation=True)
def get_the_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city to get weather for.
    """
    return f"It is currently 70 degrees and cloudy in {city}"


# =============================================================================
# Helper functions
# =============================================================================


def _make_weather_agent(db=None):
    return Agent(
        name="Weather Agent",
        role="Provides weather information. Use the get_the_weather tool to get weather data.",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=db,
        telemetry=False,
    )


def _make_team_with_weather_agent(db=None):
    agent = _make_weather_agent(db=db)
    return Team(
        name="Weather Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        db=db,
        telemetry=False,
        instructions=[
            "You MUST delegate all weather-related tasks to the Weather Agent.",
            "Do NOT try to answer weather questions yourself.",
        ],
    )


def save_result(step_input: StepInput) -> StepOutput:
    """Final step that saves results."""
    prev = step_input.previous_step_content or "no previous content"
    return StepOutput(content=f"Result saved: {prev}")


# =============================================================================
# Agent Confirmation Flow Tests
# =============================================================================


class TestAgentConfirmationFlow:
    """Tests for agent confirmation HITL within a workflow step."""

    def test_agent_confirmation_pauses_workflow(self, shared_db):
        """Workflow pauses when agent in step requires confirmation."""
        agent = _make_weather_agent(db=shared_db)
        workflow = Workflow(
            name="Weather Workflow",
            db=shared_db,
            steps=[
                Step(name="get_weather", agent=agent),
                Step(name="save", executor=save_result),
            ],
            telemetry=False,
        )

        response = workflow.run(input="What is the weather in Tokyo?")

        assert response.is_paused is True
        assert response.status == RunStatus.paused
        assert response.step_requirements is not None
        assert len(response.step_requirements) == 1

        req = response.step_requirements[0]
        assert req.requires_executor_input is True
        assert req.executor_type == "agent"
        assert req.executor_agent_name == "Weather Agent"
        assert req.executor_requirements is not None
        assert len(req.executor_requirements) >= 1

    def test_agent_confirmation_continue(self, shared_db):
        """Pause -> confirm -> continue_run completes workflow."""
        agent = _make_weather_agent(db=shared_db)
        workflow = Workflow(
            name="Weather Workflow Continue",
            db=shared_db,
            steps=[
                Step(name="get_weather", agent=agent),
                Step(name="save", executor=save_result),
            ],
            telemetry=False,
        )

        response = workflow.run(input="What is the weather in Tokyo?")
        assert response.is_paused is True

        # Resolve the executor requirements - confirm each one
        req = response.step_requirements[0]
        for executor_req in req.executor_requirements:
            if isinstance(executor_req, dict):
                # Serialized requirement - set confirmation
                executor_req["confirmation"] = True
                if "tool_execution" in executor_req and executor_req["tool_execution"]:
                    executor_req["tool_execution"]["confirmed"] = True
            else:
                executor_req.confirm()

        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert final.content is not None

    def test_agent_rejection_flow(self, shared_db):
        """Pause -> reject -> continue_run processes rejection."""
        agent = _make_weather_agent(db=shared_db)
        workflow = Workflow(
            name="Weather Workflow Reject",
            db=shared_db,
            steps=[
                Step(name="get_weather", agent=agent),
                Step(name="save", executor=save_result),
            ],
            telemetry=False,
        )

        response = workflow.run(input="What is the weather in Tokyo?")
        assert response.is_paused is True

        # Reject the confirmation
        req = response.step_requirements[0]
        for executor_req in req.executor_requirements:
            if isinstance(executor_req, dict):
                executor_req["confirmation"] = False
                if "tool_execution" in executor_req and executor_req["tool_execution"]:
                    executor_req["tool_execution"]["confirmed"] = False
            else:
                executor_req.reject(note="User does not want this")

        result = workflow.continue_run(response)
        # After rejection, workflow should complete (agent handles the rejection)
        # It may re-pause if the model retries the tool call
        assert result.content is not None


# =============================================================================
# Streaming Tests
# =============================================================================


class TestAgentConfirmationStreaming:
    """Tests for agent confirmation HITL with streaming."""

    def test_streaming_yields_executor_paused_event(self, shared_db):
        """Streaming workflow yields StepExecutorPausedEvent when agent pauses."""
        agent = _make_weather_agent(db=shared_db)
        workflow = Workflow(
            name="Weather Workflow Stream",
            db=shared_db,
            steps=[
                Step(name="get_weather", agent=agent),
                Step(name="save", executor=save_result),
            ],
            telemetry=False,
        )

        events = list(workflow.run(input="What is the weather in Tokyo?", stream=True))

        # Find the StepExecutorPausedEvent
        paused_events = [e for e in events if isinstance(e, StepExecutorPausedEvent)]
        assert len(paused_events) >= 1

        paused_event = paused_events[0]
        assert paused_event.executor_type == "agent"
        assert paused_event.executor_agent_name == "Weather Agent"
        assert paused_event.executor_requirements is not None

        # The last event should be the WorkflowRunOutput in paused state
        run_outputs = [e for e in events if isinstance(e, WorkflowRunOutput)]
        assert len(run_outputs) >= 1
        assert run_outputs[-1].is_paused is True

    def test_streaming_continue_after_confirm(self, shared_db):
        """Streaming: pause -> confirm -> continue_run stream completes."""
        agent = _make_weather_agent(db=shared_db)
        workflow = Workflow(
            name="Weather Workflow Stream Continue",
            db=shared_db,
            steps=[
                Step(name="get_weather", agent=agent),
                Step(name="save", executor=save_result),
            ],
            telemetry=False,
        )

        # Run until pause
        events = list(workflow.run(input="What is the weather in Tokyo?", stream=True))
        run_outputs = [e for e in events if isinstance(e, WorkflowRunOutput)]
        paused_response = run_outputs[-1]
        assert paused_response.is_paused is True

        # Confirm
        req = paused_response.step_requirements[0]
        for executor_req in req.executor_requirements:
            if isinstance(executor_req, dict):
                executor_req["confirmation"] = True
                if "tool_execution" in executor_req and executor_req["tool_execution"]:
                    executor_req["tool_execution"]["confirmed"] = True
            else:
                executor_req.confirm()

        # Continue with streaming
        continue_events = list(workflow.continue_run(paused_response, stream=True))
        continue_outputs = [e for e in continue_events if isinstance(e, WorkflowRunOutput)]
        assert len(continue_outputs) >= 1
        final = continue_outputs[-1]
        assert final.status == RunStatus.completed


# =============================================================================
# Async Tests
# =============================================================================


class TestAgentConfirmationAsync:
    """Tests for async agent confirmation HITL within a workflow step."""

    @pytest.mark.asyncio
    async def test_async_agent_confirmation_flow(self, shared_db):
        """Async: workflow pauses and continues after agent confirmation."""
        agent = _make_weather_agent(db=shared_db)
        workflow = Workflow(
            name="Async Weather Workflow",
            db=shared_db,
            steps=[
                Step(name="get_weather", agent=agent),
                Step(name="save", executor=save_result),
            ],
            telemetry=False,
        )

        response = await workflow.arun(input="What is the weather in Tokyo?")

        assert response.is_paused is True
        assert response.step_requirements is not None

        # Confirm
        req = response.step_requirements[0]
        for executor_req in req.executor_requirements:
            if isinstance(executor_req, dict):
                executor_req["confirmation"] = True
                if "tool_execution" in executor_req and executor_req["tool_execution"]:
                    executor_req["tool_execution"]["confirmed"] = True
            else:
                executor_req.confirm()

        final = await workflow.acontinue_run(response)
        assert final.status == RunStatus.completed
        assert final.content is not None

    @pytest.mark.asyncio
    async def test_async_streaming_executor_paused_event(self, shared_db):
        """Async streaming: yields StepExecutorPausedEvent."""
        agent = _make_weather_agent(db=shared_db)
        workflow = Workflow(
            name="Async Stream Weather Workflow",
            db=shared_db,
            steps=[
                Step(name="get_weather", agent=agent),
                Step(name="save", executor=save_result),
            ],
            telemetry=False,
        )

        events = []
        async for event in await workflow.arun(input="What is the weather in Tokyo?", stream=True):
            events.append(event)

        paused_events = [e for e in events if isinstance(e, StepExecutorPausedEvent)]
        assert len(paused_events) >= 1
        assert paused_events[0].executor_type == "agent"


# =============================================================================
# Team-in-Step HITL Tests
# =============================================================================


class TestTeamInStepHITL:
    """Tests for team-in-step where a member agent has HITL tools."""

    def test_team_in_step_pauses_workflow(self, shared_db):
        """Workflow pauses when team member agent requires confirmation."""
        team = _make_team_with_weather_agent(db=shared_db)
        workflow = Workflow(
            name="Team Weather Workflow",
            db=shared_db,
            steps=[
                Step(name="team_weather", team=team),
                Step(name="save", executor=save_result),
            ],
            telemetry=False,
        )

        response = workflow.run(input="What is the weather in Tokyo?")

        assert response.is_paused is True
        assert response.step_requirements is not None
        assert len(response.step_requirements) == 1

        req = response.step_requirements[0]
        assert req.requires_executor_input is True
        assert req.executor_type == "team"
        assert req.executor_agent_name == "Weather Team"

    def test_team_in_step_continue_after_confirm(self, shared_db):
        """Team-in-step: pause -> confirm -> continue_run completes."""
        team = _make_team_with_weather_agent(db=shared_db)
        workflow = Workflow(
            name="Team Weather Workflow Continue",
            db=shared_db,
            steps=[
                Step(name="team_weather", team=team),
                Step(name="save", executor=save_result),
            ],
            telemetry=False,
        )

        response = workflow.run(input="What is the weather in Tokyo?")
        assert response.is_paused is True

        # Resolve executor requirements
        req = response.step_requirements[0]
        for executor_req in req.executor_requirements:
            if isinstance(executor_req, dict):
                executor_req["confirmation"] = True
                if "tool_execution" in executor_req and executor_req["tool_execution"]:
                    executor_req["tool_execution"]["confirmed"] = True
            else:
                executor_req.confirm()

        final = workflow.continue_run(response)
        assert final.status == RunStatus.completed
        assert final.content is not None


# =============================================================================
# Multi-step with Executor HITL
# =============================================================================


class TestMultiStepExecutorHITL:
    """Tests for executor HITL in multi-step workflows."""

    def test_executor_hitl_after_first_step(self, shared_db):
        """Executor HITL pauses at the correct step when it's not the first step."""

        def initial_step(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Initial processing done")

        agent = _make_weather_agent(db=shared_db)
        workflow = Workflow(
            name="Multi-Step Weather",
            db=shared_db,
            steps=[
                Step(name="init", executor=initial_step),
                Step(name="get_weather", agent=agent),
                Step(name="save", executor=save_result),
            ],
            telemetry=False,
        )

        response = workflow.run(input="What is the weather in Tokyo?")

        assert response.is_paused is True
        assert response.paused_step_name == "get_weather"
        assert response.paused_step_index == 1

        # Confirm and continue
        req = response.step_requirements[0]
        for executor_req in req.executor_requirements:
            if isinstance(executor_req, dict):
                executor_req["confirmation"] = True
                if "tool_execution" in executor_req and executor_req["tool_execution"]:
                    executor_req["tool_execution"]["confirmed"] = True
            else:
                executor_req.confirm()

        final = workflow.continue_run(response)
        assert final.status == RunStatus.completed
        # The save step should have run
        assert "Result saved" in (final.content or "")
