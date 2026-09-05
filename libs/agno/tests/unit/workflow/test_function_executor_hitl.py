"""
Unit tests for Human-In-The-Loop (HITL) pause and resume with custom function executor Steps.

Regression test suite for Issue #9928:
HITL pause from a custom function-executor Step is dropped end-to-end.
"""

from __future__ import annotations

import json
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import ComponentRehydrationError
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput, RunRequirement, ToolExecution
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import StepExecutorPausedEvent
from agno.team.team import Team
from agno.tools.function import Function
from agno.workflow.step import (
    MissingHitlExecutorError,
    MissingHitlExecutorResponseError,
    Step,
)
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


class ScriptedModel(Model):
    """Offline deterministic model for testing without network or external API calls."""

    def __init__(self, responses: List[ModelResponse]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self.responses = list(responses)
        self.call_count = 0

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        resp = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return resp

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self.invoke()

    def parse_args(self, *args: Any, **kwargs: Any):
        return {}

    def get_instructions_for_model(self, *args: Any, **kwargs: Any):
        return None

    def get_system_message_for_model(self, *args: Any, **kwargs: Any):
        return None


def _create_mock_paused_team(run_id="run-team-1", team_id="team-1", team_name="SupportTeam"):
    """Helper to create a mock Team and a paused TeamRunOutput with an unresolved requirement."""
    req = RunRequirement(
        id="req-tool-1",
        tool_execution=ToolExecution(
            tool_call_id="call-1",
            tool_name="ask_user_confirmation",
            tool_args={"message": "Please confirm refund"},
            requires_user_input=True,
        ),
    )

    paused_output = TeamRunOutput(
        run_id=run_id,
        team_id=team_id,
        team_name=team_name,
        content="Pausing for user confirmation",
        status=RunStatus.paused,
        requirements=[req],
    )

    mock_team = MagicMock(spec=Team)
    mock_team.id = team_id
    mock_team.name = team_name
    mock_team.store_media = True
    mock_team.store_tool_messages = True
    mock_team.store_history_messages = True

    # Completed output on continue
    completed_output = TeamRunOutput(
        run_id=run_id,
        team_id=team_id,
        team_name=team_name,
        content="Action completed after user confirmation",
        status=RunStatus.completed,
        requirements=[],
    )
    mock_team.run = MagicMock(return_value=paused_output)
    mock_team.continue_run = MagicMock(return_value=completed_output)
    mock_team.acontinue_run = AsyncMock(return_value=completed_output)
    mock_team.deep_copy = MagicMock(return_value=mock_team)

    return mock_team, paused_output, completed_output, req


# =============================================================================
# 1. Normal custom function behavior preservation
# =============================================================================


@pytest.mark.asyncio
async def test_normal_custom_function_returns_string():
    """Verify that regular custom function steps returning strings work unchanged."""

    async def my_executor(step_input: StepInput) -> str:
        return f"Echo: {step_input.input}"

    wf = Workflow(id="normal-wf-1", steps=[Step(name="echo_step", executor=my_executor)])
    out = await wf.arun(input="hello")

    assert out.status == RunStatus.completed
    assert out.is_paused is False
    assert out.content == "Echo: hello"


@pytest.mark.asyncio
async def test_normal_custom_function_returns_step_output():
    """Verify that custom function steps returning StepOutput work unchanged."""

    async def my_executor(step_input: StepInput) -> StepOutput:
        return StepOutput(content="step output result")

    wf = Workflow(id="normal-wf-2", steps=[Step(name="step_output_step", executor=my_executor)])
    out = await wf.arun(input="hello")

    assert out.status == RunStatus.completed
    assert out.is_paused is False
    assert out.content == "step output result"


# =============================================================================
# 2. Issue #9928: Async non-streaming custom executor pause & storage
# =============================================================================


@pytest.mark.asyncio
async def test_custom_function_executor_pause_propagation_and_storage():
    """
    Test that when an inner team in a custom executor pauses on HITL:
    1. Workflow status becomes PAUSED
    2. Workflow is_paused is True
    3. Inner requirements propagate to workflow.step_requirements
    4. The paused TeamRunOutput is saved in workflow.step_executor_runs
    """
    mock_team, paused_team_output, _, _ = _create_mock_paused_team()

    async def run_team_executor(step_input: StepInput):
        return paused_team_output

    step = Step(
        name="RunTeamStep",
        executor=run_team_executor,
        hitl_executor=mock_team,
    )

    wf = Workflow(id="wf-hitl-custom", steps=[step])
    out = await wf.arun(input="process refund")

    assert out.status == RunStatus.paused, f"Expected PAUSED, got {out.status}"
    assert out.is_paused is True, "Expected out.is_paused to be True"
    assert out.step_requirements is not None, "Expected step_requirements to be populated"
    assert len(out.step_requirements) > 0, "Expected at least one step requirement"
    assert out.step_requirements[0].requires_executor_input is True

    # Verify step_executor_runs persistence
    assert out.step_executor_runs is not None, "Expected step_executor_runs to not be None"
    assert len(out.step_executor_runs) > 0, "Expected at least one run in step_executor_runs"
    assert out.step_executor_runs[0].run_id == paused_team_output.run_id


# =============================================================================
# 3. Issue #9928: Async streaming custom executor pause propagation
# =============================================================================


@pytest.mark.asyncio
async def test_custom_function_executor_streaming_pause_propagation():
    """
    Test that async streaming generator custom executor preserves pause end-to-end.
    """
    mock_team, paused_team_output, _, _ = _create_mock_paused_team()

    async def run_team_streaming_executor(step_input: StepInput):
        yield "Thinking..."
        yield paused_team_output

    step = Step(
        name="StreamingTeamStep",
        executor=run_team_streaming_executor,
        hitl_executor=mock_team,
    )

    wf = Workflow(id="wf-hitl-streaming", steps=[step])

    events = []
    async for chunk in wf.arun(input="stream task", stream=True):
        events.append(chunk)

    paused_events = [e for e in events if isinstance(e, StepExecutorPausedEvent)]
    assert len(paused_events) == 1, f"Expected 1 StepExecutorPausedEvent, got {events}"
    paused_event = paused_events[0]
    assert paused_event.step_name == "StreamingTeamStep"
    assert getattr(paused_event.executor_type, "value", paused_event.executor_type) == "team"
    assert paused_event.executor_requirements is not None
    assert len(paused_event.executor_requirements) > 0


# =============================================================================
# 4. Issue #9928: Resume routing to hitl_executor
# =============================================================================


@pytest.mark.asyncio
async def test_custom_function_executor_resume_routing():
    """
    Test that calling workflow.acontinue_run() routes back to hitl_executor.acontinue_run().
    """
    mock_team, paused_team_output, completed_output, _ = _create_mock_paused_team()

    async def run_team_executor(step_input: StepInput):
        return paused_team_output

    step = Step(
        name="RunTeamStep",
        executor=run_team_executor,
        hitl_executor=mock_team,
    )

    wf = Workflow(id="wf-hitl-resume", steps=[step], db=SqliteDb())
    paused_wf_out = await wf.arun(input="do action")

    assert paused_wf_out.is_paused is True, "Workflow must pause before it can be resumed"

    # Resolve requirements
    active_req = paused_wf_out.step_requirements[0]
    active_req.executor_requirements[0]["user_input"] = "Approved"

    # Resume the workflow
    resumed_out = await wf.acontinue_run(
        run_response=paused_wf_out,
        step_requirements=paused_wf_out.step_requirements,
    )

    # Verify that mock_team.acontinue_run was invoked
    mock_team.acontinue_run.assert_awaited_once()
    assert resumed_out.status == RunStatus.completed


# =============================================================================
# 5. Sync Non-Streaming and Streaming Tests
# =============================================================================


def test_custom_function_executor_sync_pause_and_resume():
    """Test sync custom function pause propagation and continue_run routing."""
    mock_team, paused_team_output, _, _ = _create_mock_paused_team()

    def run_team_sync_executor(step_input: StepInput):
        return paused_team_output

    step = Step(
        name="SyncRunTeamStep",
        executor=run_team_sync_executor,
        hitl_executor=mock_team,
    )
    wf = Workflow(id="wf-hitl-sync", steps=[step], db=SqliteDb())
    paused_wf_out = wf.run(input="sync action")

    assert paused_wf_out.status == RunStatus.paused
    assert paused_wf_out.is_paused is True
    assert len(paused_wf_out.step_requirements) > 0
    assert paused_wf_out.step_executor_runs is not None
    assert len(paused_wf_out.step_executor_runs) > 0

    # Resolve requirement and continue
    active_req = paused_wf_out.step_requirements[0]
    active_req.executor_requirements[0]["user_input"] = "Approved"

    resumed_out = wf.continue_run(
        run_response=paused_wf_out,
        step_requirements=paused_wf_out.step_requirements,
    )
    mock_team.continue_run.assert_called_once()
    assert resumed_out.status == RunStatus.completed


def test_custom_function_executor_sync_streaming_pause():
    """Test sync streaming generator custom executor preserves pause."""
    mock_team, paused_team_output, _, _ = _create_mock_paused_team()

    def run_team_sync_stream_executor(step_input: StepInput):
        yield "Thinking sync..."
        yield paused_team_output

    step = Step(
        name="SyncStreamingStep",
        executor=run_team_sync_stream_executor,
        hitl_executor=mock_team,
    )
    wf = Workflow(id="wf-hitl-sync-stream", steps=[step])
    events = list(wf.run(input="stream sync task", stream=True))

    paused_events = [e for e in events if isinstance(e, StepExecutorPausedEvent)]
    assert len(paused_events) == 1
    assert paused_events[0].step_name == "SyncStreamingStep"
    assert getattr(paused_events[0].executor_type, "value", paused_events[0].executor_type) == "team"
    assert len(paused_events[0].executor_requirements) > 0


# =============================================================================
# 6. Step Validation and Serialization Tests
# =============================================================================


def test_step_hitl_executor_validation():
    """Test that hitl_executor is rejected if executor is not provided."""
    mock_team, _, _, _ = _create_mock_paused_team()
    with pytest.raises(ValueError, match="hitl_executor is only valid with a function executor"):
        Step(name="InvalidStep", team=mock_team, hitl_executor=mock_team)


def test_step_hitl_executor_invalid_type_raises():
    """Test that non-Agent and non-Team hitl_executor is rejected with TypeError."""

    def dummy_executor(step_input: StepInput):
        return "ok"

    with pytest.raises(TypeError, match="hitl_executor must be an instance of Agent or Team"):
        Step(name="InvalidTypeStep", executor=dummy_executor, hitl_executor=object())  # type: ignore[arg-type]


def test_custom_executor_paused_without_hitl_executor_raises():
    """Test that returning a paused result without configuring hitl_executor raises ValueError."""
    _, paused_team_output, _, _ = _create_mock_paused_team()

    def unconfigured_sync_executor(step_input: StepInput):
        return paused_team_output

    wf = Workflow(
        id="wf-no-hitl-sync",
        steps=[Step(name="MissingHitlStepSync", executor=unconfigured_sync_executor)],
    )
    with pytest.raises(ValueError, match="no 'hitl_executor' was configured"):
        wf.run(input="test")


@pytest.mark.asyncio
async def test_custom_executor_paused_without_hitl_executor_raises_async():
    """Test that async custom executor returning paused result without hitl_executor raises ValueError."""
    _, paused_team_output, _, _ = _create_mock_paused_team()

    async def unconfigured_async_executor(step_input: StepInput):
        return paused_team_output

    wf = Workflow(
        id="wf-no-hitl-async",
        steps=[Step(name="MissingHitlStepAsync", executor=unconfigured_async_executor)],
    )
    with pytest.raises(ValueError, match="no 'hitl_executor' was configured"):
        await wf.arun(input="test")


def test_custom_executor_type_and_id_mismatch_raises():
    """Test type and ID mismatch between configured hitl_executor and returned response."""
    mock_team, paused_team_output, _, _ = _create_mock_paused_team(team_id="team-expected")

    mock_agent = MagicMock(spec=Agent)
    mock_agent.id = "agent-expected"

    # 1. Configured Agent, but returned TeamRunOutput -> TypeError
    def return_team_output(step_input: StepInput):
        return paused_team_output

    step_agent_mismatch = Step(
        name="TypeMismatchStep1",
        executor=return_team_output,
        hitl_executor=mock_agent,
    )
    wf_type_mismatch = Workflow(id="wf-mismatch-1", steps=[step_agent_mismatch])
    with pytest.raises(TypeError, match="configured hitl_executor of type Agent, but returned TeamRunOutput"):
        wf_type_mismatch.run(input="test")

    # 2. Configured Team, but returned RunOutput -> TypeError
    paused_agent_output = RunOutput(
        run_id="run-agent-1",
        agent_id="agent-expected",
        content="Agent paused",
        status=RunStatus.paused,
    )

    def return_agent_output(step_input: StepInput):
        return paused_agent_output

    step_team_mismatch = Step(
        name="TypeMismatchStep2",
        executor=return_agent_output,
        hitl_executor=mock_team,
    )
    wf_team_mismatch = Workflow(id="wf-mismatch-2", steps=[step_team_mismatch])
    with pytest.raises(TypeError, match="configured hitl_executor of type Team, but returned RunOutput"):
        wf_team_mismatch.run(input="test")

    # 3. Configured Team with team-expected, but response has team_id="team-different" -> ValueError
    paused_team_wrong_id = TeamRunOutput(
        run_id="run-team-diff",
        team_id="team-different",
        content="Team paused",
        status=RunStatus.paused,
    )

    def return_wrong_team_id(step_input: StepInput):
        return paused_team_wrong_id

    step_id_mismatch = Step(
        name="IdMismatchStep",
        executor=return_wrong_team_id,
        hitl_executor=mock_team,
    )
    wf_id_mismatch = Workflow(id="wf-mismatch-3", steps=[step_id_mismatch])
    with pytest.raises(ValueError, match="does not match returned response team_id"):
        wf_id_mismatch.run(input="test")


def test_step_to_dict_and_get_links_with_hitl_executor():
    """Test serialization of hitl_executor into dict and links."""
    mock_team, _, _, _ = _create_mock_paused_team(team_id="team-special-1")

    def dummy_executor(step_input: StepInput):
        return "ok"

    step = Step(name="SerializedStep", executor=dummy_executor, hitl_executor=mock_team)
    data = step.to_dict()
    assert data.get("hitl_team_id") == "team-special-1"

    links = step.get_links()
    assert any(
        link.get("child_component_id") == "team-special-1" and link.get("link_kind") == "step_team" for link in links
    )


def test_workflow_deep_copy_preserves_hitl_executor():
    """Test that workflow deep_copy preserves hitl_executor and unresolved IDs."""
    mock_team, _, _, _ = _create_mock_paused_team(team_id="team-copy-1")

    def dummy_executor(step_input: StepInput):
        return "ok"

    step = Step(name="StepWithHitl", executor=dummy_executor, hitl_executor=mock_team)
    step._unresolved_hitl_team_id = "team-unresolved-99"
    wf = Workflow(id="wf-copy-test", steps=[step])

    copied_wf = wf.deep_copy()
    copied_step = copied_wf.steps[0]

    assert copied_step.hitl_executor is not None
    assert copied_step.hitl_executor.id == "team-copy-1"
    assert copied_step._unresolved_hitl_team_id == "team-unresolved-99"


def test_workflow_save_and_rehydrate_with_hitl_executor(tmp_path):
    """Test cascading save of hitl_executor, strict load, failure on missing, and lenient roundtrip."""
    db_file = str(tmp_path / "wf_save_test.db")
    db = SqliteDb(db_file=db_file)

    model = ScriptedModel([ModelResponse(role="assistant", content="dummy")])
    agent = Agent(id="agent-save-1", name="AgentSave1", model=model, db=db)
    team = Team(id="team-save-1", name="TeamSave1", members=[agent], model=model, db=db)

    def custom_team_exec(step_input: StepInput):
        return team.run(step_input.input)

    step = Step(name="StepSave", executor=custom_team_exec, hitl_executor=team)
    wf = Workflow(id="wf-save-1", name="WorkflowSave1", steps=[step], db=db)

    # 1. Cascading save
    wf_version = wf.save(db=db)
    assert wf_version is not None

    links = db.get_links(component_id="wf-save-1", version=1)
    team_links = [link for link in links if link.get("link_kind") == "step_team"]
    assert len(team_links) > 0
    assert team_links[0]["child_version"] is not None

    # 2. Strict rehydration loads successfully
    from agno.registry import Registry
    from agno.workflow.workflow import get_workflow_by_id

    registry = Registry()
    registry.add_model(model)
    registry.add_function(custom_team_exec)

    reloaded_wf = get_workflow_by_id(
        db=db,
        id="wf-save-1",
        registry=registry,
        strict=True,
    )
    assert reloaded_wf is not None
    reloaded_step = reloaded_wf.steps[0]
    assert reloaded_step.hitl_executor is not None
    assert reloaded_step.hitl_executor.id == "team-save-1"

    # 3. Strict rehydration failure when child component is missing
    bad_step_dict = {
        "type": "Step",
        "name": "MissingChildStep",
        "executor_ref": "custom_team_exec",
        "hitl_team_id": "non-existent-team-id",
    }
    with pytest.raises(ComponentRehydrationError, match="references hitl team 'non-existent-team-id'"):
        Step.from_dict(bad_step_dict, db=db, registry=registry, strict=True)

    # 4. Lenient rehydration preserves unresolved ID on roundtrip to_dict()
    lenient_step = Step.from_dict(bad_step_dict, db=db, registry=registry, strict=False)
    assert lenient_step.hitl_executor is None
    assert lenient_step._unresolved_hitl_team_id == "non-existent-team-id"
    roundtrip_data = lenient_step.to_dict()
    assert roundtrip_data.get("hitl_team_id") == "non-existent-team-id"


def test_workflow_rehydrates_pinned_hitl_agent_version(tmp_path):
    """A function step reloads its pinned HITL Agent version, not the latest Agent config."""
    from agno.registry import Registry
    from agno.workflow.workflow import get_workflow_by_id

    db = SqliteDb(db_file=str(tmp_path / "wf_agent_pin.db"))
    model = ScriptedModel([ModelResponse(role="assistant", content="dummy")])
    agent = Agent(
        id="hitl-agent-pin",
        name="Pinned HITL Agent",
        description="version one",
        model=model,
        db=db,
    )

    def custom_agent_exec(step_input: StepInput):
        return agent.run(step_input.input)

    workflow = Workflow(
        id="wf-agent-pin",
        name="Pinned HITL Agent Workflow",
        steps=[Step(name="AgentStep", executor=custom_agent_exec, hitl_executor=agent)],
        db=db,
    )
    assert workflow.save() == 1

    links = db.get_links(component_id="wf-agent-pin", version=1)
    agent_links = [link for link in links if link.get("link_kind") == "step_agent"]
    assert len(agent_links) == 1
    assert agent_links[0]["child_version"] == 1

    agent.description = "version two"
    assert agent.save(db=db) == 2

    registry = Registry()
    registry.add_model(model)
    registry.add_function(custom_agent_exec)
    reloaded = get_workflow_by_id(db=db, id="wf-agent-pin", registry=registry, strict=True)

    assert reloaded is not None
    reloaded_agent = reloaded.steps[0].hitl_executor
    assert isinstance(reloaded_agent, Agent)
    assert reloaded_agent.id == "hitl-agent-pin"
    assert reloaded_agent.description == "version one"

    bad_step_dict = {
        "type": "Step",
        "name": "MissingAgentStep",
        "executor_ref": "custom_agent_exec",
        "hitl_agent_id": "missing-hitl-agent",
    }
    with pytest.raises(ComponentRehydrationError, match="references hitl agent 'missing-hitl-agent'"):
        Step.from_dict(bad_step_dict, db=db, registry=registry, strict=True)

    lenient_step = Step.from_dict(bad_step_dict, db=db, registry=registry, strict=False)
    assert lenient_step.hitl_executor is None
    assert lenient_step._unresolved_hitl_agent_id == "missing-hitl-agent"
    assert lenient_step.to_dict().get("hitl_agent_id") == "missing-hitl-agent"


# =============================================================================
# 7. Real Offline E2E Agent and Team Tests (ScriptedModel)
# =============================================================================


def test_real_offline_agent_hitl_workflow_e2e(tmp_path):
    """Real offline Agent with ScriptedModel: tool execution on resumption."""
    executed_args = []

    def select_destination(message: str = "", choice: str = ""):
        executed_args.append({"message": message, "choice": choice})
        return f"Selected destination: {choice}"

    ask_func = Function(
        name="select_destination",
        description="Ask the user to pick an option.",
        entrypoint=select_destination,
        requires_user_input=True,
        user_input_fields=["choice"],
    )

    model = ScriptedModel(
        [
            ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "select_destination", "arguments": json.dumps({"message": "Where to?"})},
                    }
                ],
            ),
            ModelResponse(role="assistant", content="Successfully booked Tokyo!"),
        ]
    )

    db_file = str(tmp_path / "test_offline_agent.db")
    db = SqliteDb(db_file=db_file)
    agent = Agent(id="agent_tokyo", name="travel_agent", model=model, tools=[ask_func], db=db)

    def run_agent_executor(step_input: StepInput):
        return agent.run(step_input.input)

    step = Step(
        name="TravelStep",
        executor=run_agent_executor,
        hitl_executor=agent,
    )

    wf = Workflow(id="wf-agent-tokyo", steps=[step], db=db)
    wf_out = wf.run("Book trip to Tokyo")

    assert wf_out.status == RunStatus.paused
    assert wf_out.is_paused is True
    assert wf_out.step_requirements is not None
    assert len(wf_out.step_requirements) > 0

    # Resolve requirement with choice="Tokyo"
    step_req = wf_out.step_requirements[0]
    inner_req_dict = step_req.executor_requirements[0]
    inner_req = RunRequirement.from_dict(inner_req_dict)
    inner_req.provide_user_input({"choice": "Tokyo"})
    step_req.executor_requirements[0] = inner_req.to_dict()

    resumed_out = wf.continue_run(run_response=wf_out, step_requirements=wf_out.step_requirements)
    assert resumed_out.status == RunStatus.completed
    assert resumed_out.is_paused is False
    assert resumed_out.content == "Successfully booked Tokyo!"
    assert len(executed_args) == 1
    assert executed_args[0] == {"message": "Where to?", "choice": "Tokyo"}


def test_real_offline_team_hitl_workflow_tokyo_scenario(tmp_path):
    """Real offline Team with ScriptedModel: Tokyo scenario from Issue #9928."""
    executed_args = []

    def select_destination(message: str = "", choice: str = ""):
        executed_args.append({"message": message, "choice": choice})
        return f"Selected destination: {choice}"

    ask_func = Function(
        name="select_destination",
        description="Ask the user to pick an option.",
        entrypoint=select_destination,
        requires_user_input=True,
        user_input_fields=["choice"],
    )

    model_member = ScriptedModel(
        [
            ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "select_destination", "arguments": json.dumps({"message": "Where to?"})},
                    }
                ],
            ),
            ModelResponse(role="assistant", content="Successfully booked Tokyo in member agent!"),
        ]
    )

    model_team = ScriptedModel(
        [
            ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call_team_1",
                        "type": "function",
                        "function": {
                            "name": "delegate_task_to_member",
                            "arguments": json.dumps({"member_id": "m1", "task": "Book Tokyo trip"}),
                        },
                    }
                ],
            ),
            ModelResponse(role="assistant", content="Team coordinating travel to Tokyo."),
        ]
    )

    db_file = str(tmp_path / "test_offline_team.db")
    db = SqliteDb(db_file=db_file)
    member = Agent(id="m1", name="M1", model=model_member, tools=[ask_func], db=db)
    team = Team(id="t1", name="T1", members=[member], model=model_team, db=db)

    def run_team_executor(step_input: StepInput):
        return team.run(step_input.input)

    step = Step(
        name="TeamTravelStep",
        executor=run_team_executor,
        hitl_executor=team,
    )

    wf = Workflow(id="wf-team-tokyo", steps=[step], db=db)
    wf_out = wf.run("Book trip to Tokyo via team")

    assert wf_out.status == RunStatus.paused
    assert wf_out.is_paused is True
    assert wf_out.step_requirements is not None
    assert len(wf_out.step_requirements) > 0

    # Resolve requirement with Tokyo
    step_req = wf_out.step_requirements[0]
    inner_req_dict = step_req.executor_requirements[0]
    inner_req = RunRequirement.from_dict(inner_req_dict)
    inner_req.provide_user_input({"choice": "Tokyo"})
    step_req.executor_requirements[0] = inner_req.to_dict()

    resumed_out = wf.continue_run(run_response=wf_out, step_requirements=wf_out.step_requirements)
    assert resumed_out.status == RunStatus.completed
    assert resumed_out.is_paused is False
    assert len(executed_args) == 1
    assert executed_args[0] == {"message": "Where to?", "choice": "Tokyo"}


def test_step_positional_args_backward_compatibility():
    """Verify legacy positional arguments Step('name', None, None, executor, None, 'step-id') work."""

    def dummy_executor(step_input: StepInput):
        return "ok"

    # Old code passing positional parameters up to step_id
    step = Step("legacy_step", None, None, dummy_executor, None, "legacy-step-id-123")
    assert step.name == "legacy_step"
    assert step.agent is None
    assert step.team is None
    assert step.executor is dummy_executor
    assert step.workflow is None
    assert step.step_id == "legacy-step-id-123"
    assert step.hitl_executor is None


def test_manual_step_output_paused_without_hitl_executor_raises():
    """Verify returning StepOutput(is_paused=True) without hitl_executor raises MissingHitlExecutorError."""

    def manual_pause_executor(step_input: StepInput):
        return StepOutput(content="manual pause", is_paused=True)

    step = Step(name="ManualPauseNoHitl", executor=manual_pause_executor)
    wf = Workflow(steps=[step])

    with pytest.raises(MissingHitlExecutorError):
        wf.run("test")


def test_manual_step_output_paused_with_hitl_executor_but_no_response_raises():
    """Verify returning StepOutput(is_paused=True) without a recoverable RunOutput/TeamRunOutput raises MissingHitlExecutorResponseError."""
    mock_team, _, _, _ = _create_mock_paused_team()

    def manual_pause_no_response_executor(step_input: StepInput):
        return StepOutput(content="manual pause", is_paused=True)

    step = Step(
        name="ManualPauseNoResponse",
        executor=manual_pause_no_response_executor,
        hitl_executor=mock_team,
    )
    wf = Workflow(steps=[step])

    # Sync path: must raise MissingHitlExecutorResponseError (never silently complete)
    with pytest.raises(MissingHitlExecutorResponseError) as excinfo:
        wf.run("test")
    assert "did not provide a recoverable RunOutput or TeamRunOutput" in str(excinfo.value)

    # Async path: must also raise MissingHitlExecutorResponseError
    async def async_test():
        with pytest.raises(MissingHitlExecutorResponseError) as aexcinfo:
            await wf.arun("test")
        assert "did not provide a recoverable RunOutput or TeamRunOutput" in str(aexcinfo.value)

    import asyncio

    asyncio.run(async_test())


def test_workflow_deep_copy_no_team_db_in_memory_resume(tmp_path):
    """Verify that an in-memory Team (no DB attached) survives Workflow.deep_copy() and resumes cleanly.

    When Workflow.deep_copy() is called, custom function step closures retain the original Team
    reference. Preserving hitl_executor by reference ensures the copied workflow's continue_run
    targets the original instance holding the in-memory session rather than an empty copy,
    preventing 'ValueError: Could not find session with id ...' / RunNotFoundError.
    """
    executed_args: List[dict] = []

    def select_destination(message: str = "", choice: str = ""):
        executed_args.append({"message": message, "choice": choice})
        return f"Selected destination: {choice}"

    ask_func = Function(
        name="select_destination",
        description="Ask the user to pick an option.",
        entrypoint=select_destination,
        requires_user_input=True,
        user_input_fields=["choice"],
    )

    model_member = ScriptedModel(
        [
            ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "select_destination", "arguments": json.dumps({"message": "Where to?"})},
                    }
                ],
            ),
            ModelResponse(role="assistant", content="Successfully booked Tokyo in member agent!"),
        ]
    )

    model_team = ScriptedModel(
        [
            ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call_team_1",
                        "type": "function",
                        "function": {
                            "name": "delegate_task_to_member",
                            "arguments": json.dumps({"member_id": "m_mem", "task": "Book Tokyo trip"}),
                        },
                    }
                ],
            ),
            ModelResponse(role="assistant", content="Team coordinating travel to Tokyo."),
        ]
    )

    # Note: Team and Agent have NO database attached; session is purely in-memory.
    member = Agent(id="m_mem", name="MMem", model=model_member, tools=[ask_func])
    team = Team(id="t_mem", name="TMem", members=[member], model=model_team)

    def run_team_executor(step_input: StepInput):
        return team.run(step_input.input)

    step = Step(
        name="TeamMemStep",
        executor=run_team_executor,
        hitl_executor=team,
    )

    db = SqliteDb(db_file=str(tmp_path / "wf_mem.db"))
    wf = Workflow(id="wf-mem-tokyo", steps=[step], db=db)
    wf_out = wf.run("Book trip to Tokyo")

    assert wf_out.status == RunStatus.paused
    assert wf_out.is_paused is True
    assert wf_out.step_requirements is not None
    assert len(wf_out.step_requirements) > 0

    # Deep copy the workflow
    wf_copy = wf.deep_copy()
    assert wf_copy.steps[0].hitl_executor is team

    # Resolve requirement with Tokyo
    step_req = wf_out.step_requirements[0]
    inner_req_dict = step_req.executor_requirements[0]
    inner_req = RunRequirement.from_dict(inner_req_dict)
    inner_req.provide_user_input({"choice": "Tokyo"})
    step_req.executor_requirements[0] = inner_req.to_dict()

    # Resumed on copied workflow succeeds because hitl_executor points to the in-memory team
    resumed_out = wf_copy.continue_run(run_response=wf_out, step_requirements=wf_out.step_requirements)
    assert resumed_out.status == RunStatus.completed
    assert resumed_out.is_paused is False
    assert len(executed_args) == 1
    assert executed_args[0] == {"message": "Where to?", "choice": "Tokyo"}


def test_sync_generator_run_output_hitl(tmp_path):
    """Verify a sync custom generator yielding a paused TeamRunOutput pauses and resumes."""
    mock_team, paused_team_out, _, _ = _create_mock_paused_team()

    def sync_gen_executor(step_input: StepInput):
        yield "Step progress message..."
        yield paused_team_out

    step = Step(
        name="SyncGenPauseStep",
        executor=sync_gen_executor,
        hitl_executor=mock_team,
    )
    db = SqliteDb(db_file=str(tmp_path / "sync_gen_pause.db"))
    wf = Workflow(steps=[step], db=db)
    wf_out = wf.run("test sync generator pause")

    assert wf_out.status == RunStatus.paused
    assert wf_out.is_paused is True
    assert wf_out.step_executor_runs is not None
    assert len(wf_out.step_executor_runs) == 1
    assert wf_out.step_executor_runs[0].team_id == "team-1"
    assert len(wf_out.step_requirements) == 1

    resumed = wf.continue_run(run_response=wf_out, step_requirements=wf_out.step_requirements)
    assert resumed.status == RunStatus.completed
    assert resumed.is_paused is False
    assert mock_team.continue_run.called


@pytest.mark.asyncio
async def test_async_generator_streaming_workflow_run_output_hitl(tmp_path):
    """Verify a streaming async custom generator yielding a paused TeamRunOutput pauses and resumes."""
    mock_team, paused_team_out, _, _ = _create_mock_paused_team()

    async def async_gen_executor(step_input: StepInput):
        yield "Starting async task..."
        yield paused_team_out

    step = Step(
        name="AsyncGenPauseStep",
        executor=async_gen_executor,
        hitl_executor=mock_team,
    )
    db = SqliteDb(db_file=str(tmp_path / "async_gen_pause.db"))
    wf = Workflow(steps=[step], db=db)

    events = []
    async for event in wf.arun("test async generator stream", stream=True):
        events.append(event)

    paused_events = [e for e in events if isinstance(e, StepExecutorPausedEvent)]
    assert len(paused_events) == 1
    paused_event = paused_events[0]
    assert paused_event.step_name == "AsyncGenPauseStep"
    assert paused_event.executor_requirements is not None
    assert len(paused_event.executor_requirements) == 1

    # Load session and verify paused status
    session = db.get_session(session_id=paused_event.session_id, session_type="workflow")
    assert session is not None
    latest_run = session.runs[-1]
    assert latest_run.status == RunStatus.paused
    assert latest_run.is_paused is True
    assert len(latest_run.step_executor_runs) == 1

    # Resume via acontinue_run
    resumed = await wf.acontinue_run(run_response=latest_run, step_requirements=latest_run.step_requirements)
    assert resumed.status == RunStatus.completed
    assert resumed.is_paused is False
    assert mock_team.acontinue_run.called


@pytest.mark.asyncio
async def test_real_offline_team_async_streaming_e2e(tmp_path):
    """Test full async streaming pipeline end-to-end with real offline Team:
    1. Custom async executor uses the exact streaming call shape from Issue #9928.
    2. Model calls select_destination tool with requires_user_input=True.
    3. Workflow pauses, emitting StepExecutorPausedEvent.
    4. User provides 'Tokyo' via acontinue_run.
    5. Tool executes once with provided input, and workflow completes successfully.
    """
    executed_args: List[dict] = []

    def select_destination(message: str = "", choice: str = ""):
        executed_args.append({"message": message, "choice": choice})
        return f"Selected destination: {choice}"

    ask_func = Function(
        name="select_destination",
        description="Ask the user to pick an option.",
        entrypoint=select_destination,
        requires_user_input=True,
        user_input_fields=["choice"],
    )

    model_member = ScriptedModel(
        [
            ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call_member_stream",
                        "type": "function",
                        "function": {"name": "select_destination", "arguments": json.dumps({"message": "Where to?"})},
                    }
                ],
            ),
            ModelResponse(role="assistant", content="Successfully booked Tokyo in member agent!"),
        ]
    )

    model_team = ScriptedModel(
        [
            ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call_team_stream",
                        "type": "function",
                        "function": {
                            "name": "delegate_task_to_member",
                            "arguments": json.dumps({"member_id": "m_stream", "task": "Book Tokyo trip"}),
                        },
                    }
                ],
            ),
            ModelResponse(role="assistant", content="Team coordinating travel to Tokyo."),
        ]
    )

    db_file = str(tmp_path / "test_async_streaming_team.db")
    db = SqliteDb(db_file=db_file)
    member = Agent(id="m_stream", name="MStream", model=model_member, tools=[ask_func], db=db)
    team = Team(id="t_stream", name="TStream", members=[member], model=model_team, db=db)

    async def run_team_async_streaming_executor(step_input: StepInput):
        final_output = None
        async for chunk in team.arun(
            step_input.input,
            stream=True,
            stream_events=True,
            yield_run_output=True,
        ):
            final_output = chunk

        assert isinstance(final_output, TeamRunOutput)
        return final_output

    step = Step(
        name="TeamTravelStreamStep",
        executor=run_team_async_streaming_executor,
        hitl_executor=team,
    )

    wf = Workflow(id="wf-team-async-stream-tokyo", steps=[step], db=db)

    # Execute workflow with streaming
    events = []
    async for event in wf.arun("Book trip to Tokyo via async streaming team", stream=True):
        events.append(event)

    paused_events = [e for e in events if isinstance(e, StepExecutorPausedEvent)]
    assert len(paused_events) == 1
    paused_event = paused_events[0]
    assert paused_event.step_name == "TeamTravelStreamStep"

    # Get paused session
    session = db.get_session(session_id=paused_event.session_id, session_type="workflow")
    assert session is not None
    latest_run = session.runs[-1]
    assert latest_run.status == RunStatus.paused
    assert latest_run.is_paused is True
    assert len(latest_run.step_requirements) > 0

    # Resolve requirement with Tokyo
    step_req = latest_run.step_requirements[0]
    inner_req_dict = step_req.executor_requirements[0]
    inner_req = RunRequirement.from_dict(inner_req_dict)
    inner_req.provide_user_input({"choice": "Tokyo"})
    step_req.executor_requirements[0] = inner_req.to_dict()

    resumed_out = await wf.acontinue_run(run_response=latest_run, step_requirements=latest_run.step_requirements)
    assert resumed_out.status == RunStatus.completed
    assert resumed_out.is_paused is False
    assert len(executed_args) == 1
    assert executed_args[0] == {"message": "Where to?", "choice": "Tokyo"}
