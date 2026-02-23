from unittest.mock import AsyncMock, Mock

import pytest

from agno.agent import RunEvent
from agno.os.interfaces.slack.router import _process_event
from agno.os.interfaces.slack.state import StreamState
from agno.run.team import TeamRunEvent
from agno.run.workflow import WorkflowRunEvent


def _stream():
    s = AsyncMock()
    s.append = AsyncMock()
    return s


def _chunk(event, **kwargs):
    m = Mock(event=event)
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


def _tool_mock(tool_name="search", tool_call_id="call_1", tool_call_error=None):
    t = Mock()
    t.tool_name = tool_name
    t.tool_call_id = tool_call_id
    t.tool_call_error = tool_call_error
    return t


# ── Reasoning ──────────────────────────────────────────────────────


class TestReasoning:
    @pytest.mark.asyncio
    async def test_started_creates_card(self):
        state = StreamState()
        stream = _stream()
        await _process_event(RunEvent.reasoning_started.value, _chunk(RunEvent.reasoning_started.value), state, stream)
        assert "reasoning_0" in state.task_cards
        assert state.task_cards["reasoning_0"].status == "in_progress"
        stream.append.assert_called_once()

    @pytest.mark.asyncio
    async def test_completed_increments_round(self):
        state = StreamState()
        stream = _stream()
        state.track_task("reasoning_0", "Reasoning")
        await _process_event(
            RunEvent.reasoning_completed.value, _chunk(RunEvent.reasoning_completed.value), state, stream
        )
        assert state.task_cards["reasoning_0"].status == "complete"
        assert state.reasoning_round == 1

    @pytest.mark.asyncio
    async def test_multiple_rounds_unique_keys(self):
        state = StreamState()
        stream = _stream()
        await _process_event(RunEvent.reasoning_started.value, _chunk(RunEvent.reasoning_started.value), state, stream)
        await _process_event(
            RunEvent.reasoning_completed.value, _chunk(RunEvent.reasoning_completed.value), state, stream
        )
        await _process_event(RunEvent.reasoning_started.value, _chunk(RunEvent.reasoning_started.value), state, stream)
        assert "reasoning_0" in state.task_cards
        assert "reasoning_1" in state.task_cards


# ── Tool lifecycle ─────────────────────────────────────────────────


class TestToolLifecycle:
    @pytest.mark.asyncio
    async def test_started_creates_card(self):
        state = StreamState()
        stream = _stream()
        chunk = _chunk(RunEvent.tool_call_started.value, tool=_tool_mock(), agent_name=None)
        await _process_event(RunEvent.tool_call_started.value, chunk, state, stream)
        assert "call_1" in state.task_cards
        assert state.task_cards["call_1"].status == "in_progress"

    @pytest.mark.asyncio
    async def test_started_fallback_id(self):
        state = StreamState()
        stream = _stream()
        tool = _tool_mock(tool_call_id=None)
        chunk = _chunk(RunEvent.tool_call_started.value, tool=tool, agent_name=None)
        await _process_event(RunEvent.tool_call_started.value, chunk, state, stream)
        # Fallback is str(len(task_cards)) at call time = "0"
        assert "0" in state.task_cards

    @pytest.mark.asyncio
    async def test_completed_success(self):
        state = StreamState()
        stream = _stream()
        state.track_task("call_1", "search")
        chunk = _chunk(RunEvent.tool_call_completed.value, tool=_tool_mock(), agent_name=None)
        await _process_event(RunEvent.tool_call_completed.value, chunk, state, stream)
        assert state.task_cards["call_1"].status == "complete"

    @pytest.mark.asyncio
    async def test_completed_with_error(self):
        state = StreamState()
        stream = _stream()
        state.track_task("call_1", "search")
        tool = _tool_mock(tool_call_error="timeout")
        chunk = _chunk(RunEvent.tool_call_completed.value, tool=tool, agent_name=None)
        await _process_event(RunEvent.tool_call_completed.value, chunk, state, stream)
        assert state.task_cards["call_1"].status == "error"

    @pytest.mark.asyncio
    async def test_completed_creates_if_missing(self):
        state = StreamState()
        stream = _stream()
        chunk = _chunk(RunEvent.tool_call_completed.value, tool=_tool_mock(), agent_name=None)
        await _process_event(RunEvent.tool_call_completed.value, chunk, state, stream)
        assert "call_1" in state.task_cards
        assert state.task_cards["call_1"].status == "complete"

    @pytest.mark.asyncio
    async def test_tool_call_error_event(self):
        state = StreamState()
        stream = _stream()
        tool = _tool_mock(tool_call_id="call_err")
        chunk = _chunk(RunEvent.tool_call_error.value, tool=tool, agent_name=None, error="boom")
        await _process_event(RunEvent.tool_call_error.value, chunk, state, stream)
        assert "call_err" in state.task_cards
        assert state.task_cards["call_err"].status == "error"
        assert state.error_count == 1

    @pytest.mark.asyncio
    async def test_tool_error_creates_if_missing(self):
        state = StreamState()
        stream = _stream()
        tool = _tool_mock(tool_call_id="new_id")
        chunk = _chunk(RunEvent.tool_call_error.value, tool=tool, agent_name=None, error="fail")
        await _process_event(RunEvent.tool_call_error.value, chunk, state, stream)
        assert "new_id" in state.task_cards
        assert state.task_cards["new_id"].status == "error"

    @pytest.mark.asyncio
    async def test_tool_with_member_name(self):
        state = StreamState(entity_name="Main Agent")
        stream = _stream()
        chunk = _chunk(RunEvent.tool_call_started.value, tool=_tool_mock(), agent_name="Research Agent")
        await _process_event(RunEvent.tool_call_started.value, chunk, state, stream)
        # task_id prefixes with sanitized member name
        assert "research_agent_call_1" in state.task_cards


# ── Content ────────────────────────────────────────────────────────


class TestContent:
    @pytest.mark.asyncio
    async def test_run_content_buffers(self):
        state = StreamState()
        stream = _stream()
        chunk = _chunk(RunEvent.run_content.value, content="hello")
        await _process_event(RunEvent.run_content.value, chunk, state, stream)
        assert state.text_buffer == "hello"

    @pytest.mark.asyncio
    async def test_run_content_none_ignored(self):
        state = StreamState()
        stream = _stream()
        chunk = _chunk(RunEvent.run_content.value, content=None)
        await _process_event(RunEvent.run_content.value, chunk, state, stream)
        assert state.text_buffer == ""

    @pytest.mark.asyncio
    async def test_intermediate_content_suppressed_for_team(self):
        state = StreamState(entity_type="team")
        stream = _stream()
        chunk = _chunk(RunEvent.run_intermediate_content.value, content="partial")
        await _process_event(RunEvent.run_intermediate_content.value, chunk, state, stream)
        assert state.text_buffer == ""

    @pytest.mark.asyncio
    async def test_intermediate_content_buffers_for_agent(self):
        state = StreamState(entity_type="agent")
        stream = _stream()
        chunk = _chunk(RunEvent.run_intermediate_content.value, content="partial")
        await _process_event(RunEvent.run_intermediate_content.value, chunk, state, stream)
        assert state.text_buffer == "partial"


# ── Memory ─────────────────────────────────────────────────────────


class TestMemory:
    @pytest.mark.asyncio
    async def test_started_completed_lifecycle(self):
        state = StreamState()
        stream = _stream()
        await _process_event(
            RunEvent.memory_update_started.value, _chunk(RunEvent.memory_update_started.value), state, stream
        )
        assert "memory_update" in state.task_cards
        assert state.task_cards["memory_update"].status == "in_progress"

        await _process_event(
            RunEvent.memory_update_completed.value, _chunk(RunEvent.memory_update_completed.value), state, stream
        )
        assert state.task_cards["memory_update"].status == "complete"


# ── Terminal events ────────────────────────────────────────────────


class TestTerminalEvents:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("ev", [RunEvent.run_error.value, RunEvent.run_cancelled.value])
    async def test_run_terminal_returns_true(self, ev):
        state = StreamState()
        stream = _stream()
        chunk = _chunk(ev, content="something went wrong")
        result = await _process_event(ev, chunk, state, stream)
        assert result is True
        assert state.terminal_status == "error"
        assert "Error" in state.text_buffer

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ev", ["WorkflowError", "WorkflowCancelled"])
    async def test_workflow_terminal_returns_true(self, ev):
        state = StreamState()
        stream = _stream()
        chunk = _chunk(ev, error="wf failed", content=None)
        result = await _process_event(ev, chunk, state, stream)
        assert result is True
        assert state.terminal_status == "error"
        assert "Error" in state.text_buffer

    @pytest.mark.asyncio
    async def test_run_completed_noop(self):
        state = StreamState()
        stream = _stream()
        result = await _process_event(
            RunEvent.run_completed.value, _chunk(RunEvent.run_completed.value, content=None, tool=None), state, stream
        )
        assert result is False
        assert state.text_buffer == ""


# ── Workflow suppression ───────────────────────────────────────────


class TestWorkflowSuppression:
    _SUPPRESSED = [
        RunEvent.run_content.value,
        RunEvent.reasoning_started.value,
        RunEvent.tool_call_started.value,
        RunEvent.tool_call_completed.value,
        RunEvent.tool_call_error.value,
        RunEvent.memory_update_started.value,
        RunEvent.memory_update_completed.value,
        RunEvent.run_intermediate_content.value,
        RunEvent.run_completed.value,
        RunEvent.run_error.value,
        RunEvent.run_cancelled.value,
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ev", _SUPPRESSED)
    async def test_suppressed_in_workflow_mode(self, ev):
        state = StreamState(entity_type="workflow")
        stream = _stream()
        chunk = _chunk(ev, content="suppressed", tool=None)
        result = await _process_event(ev, chunk, state, stream)
        assert result is False
        assert state.text_buffer == ""
        stream.append.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ev", _SUPPRESSED)
    async def test_team_prefix_also_suppressed(self, ev):
        state = StreamState(entity_type="workflow")
        stream = _stream()
        team_ev = f"Team{ev}"
        chunk = _chunk(team_ev, content="suppressed", tool=None)
        result = await _process_event(team_ev, chunk, state, stream)
        assert result is False
        assert state.text_buffer == ""


# ── Workflow lifecycle ─────────────────────────────────────────────


class TestWorkflowLifecycle:
    @pytest.mark.asyncio
    async def test_workflow_started(self):
        state = StreamState(entity_name="News Reporter")
        stream = _stream()
        chunk = _chunk(WorkflowRunEvent.workflow_started.value, workflow_name="News Reporter", run_id="run1")
        await _process_event(WorkflowRunEvent.workflow_started.value, chunk, state, stream)
        assert "wf_run_run1" in state.task_cards
        assert state.task_cards["wf_run_run1"].status == "in_progress"

    @pytest.mark.asyncio
    async def test_workflow_completed_with_content(self):
        state = StreamState(entity_name="News Reporter")
        stream = _stream()
        chunk = _chunk(
            WorkflowRunEvent.workflow_completed.value,
            content="Final article",
            run_id="run1",
            workflow_name="News Reporter",
        )
        state.track_task("wf_run_run1", "Workflow: News Reporter")
        result = await _process_event(WorkflowRunEvent.workflow_completed.value, chunk, state, stream)
        assert result is False
        assert "Final article" in state.text_buffer
        assert state.task_cards["wf_run_run1"].status == "complete"

    @pytest.mark.asyncio
    async def test_workflow_completed_fallback_to_captured(self):
        state = StreamState()
        state.workflow_final_content = "captured output"
        stream = _stream()
        chunk = _chunk(WorkflowRunEvent.workflow_completed.value, content=None, run_id="run1", workflow_name="Test")
        await _process_event(WorkflowRunEvent.workflow_completed.value, chunk, state, stream)
        assert "captured output" in state.text_buffer

    @pytest.mark.asyncio
    async def test_step_output_captures_in_workflow(self):
        state = StreamState(entity_type="workflow")
        stream = _stream()
        chunk = _chunk(WorkflowRunEvent.step_output.value, content="step result")
        await _process_event(WorkflowRunEvent.step_output.value, chunk, state, stream)
        assert state.workflow_final_content == "step result"
        assert state.text_buffer == ""

    @pytest.mark.asyncio
    async def test_step_output_buffers_in_agent_mode(self):
        state = StreamState(entity_type="agent")
        stream = _stream()
        chunk = _chunk(WorkflowRunEvent.step_output.value, content="step text")
        await _process_event(WorkflowRunEvent.step_output.value, chunk, state, stream)
        assert state.text_buffer == "step text"
        assert state.workflow_final_content == ""


# ── Workflow structural events ─────────────────────────────────────


class TestStructuralEvents:
    @pytest.mark.asyncio
    async def test_step_start_complete(self):
        state = StreamState()
        stream = _stream()
        await _process_event(
            WorkflowRunEvent.step_started.value, Mock(step_name="research", step_id="s1"), state, stream
        )
        assert "wf_step_s1" in state.task_cards
        assert state.task_cards["wf_step_s1"].status == "in_progress"
        await _process_event(
            WorkflowRunEvent.step_completed.value, Mock(step_name="research", step_id="s1"), state, stream
        )
        assert state.task_cards["wf_step_s1"].status == "complete"

    @pytest.mark.asyncio
    async def test_step_error(self):
        state = StreamState()
        stream = _stream()
        state.track_task("wf_step_s1", "research")
        chunk = Mock(step_name="research", step_id="s1", error="step crashed")
        await _process_event(WorkflowRunEvent.step_error.value, chunk, state, stream)
        assert state.task_cards["wf_step_s1"].status == "error"

    @pytest.mark.asyncio
    async def test_loop_full_lifecycle(self):
        state = StreamState()
        stream = _stream()
        await _process_event(
            WorkflowRunEvent.loop_execution_started.value,
            Mock(step_name="retry_loop", step_id="l1", max_iterations=3),
            state,
            stream,
        )
        assert "wf_loop_l1" in state.task_cards

        await _process_event(
            WorkflowRunEvent.loop_iteration_started.value,
            Mock(step_name="retry_loop", step_id="l1", iteration=1, max_iterations=3),
            state,
            stream,
        )
        assert "wf_loop_l1_iter_1" in state.task_cards

        await _process_event(
            WorkflowRunEvent.loop_iteration_completed.value,
            Mock(step_name="retry_loop", step_id="l1", iteration=1),
            state,
            stream,
        )
        assert state.task_cards["wf_loop_l1_iter_1"].status == "complete"

        await _process_event(
            WorkflowRunEvent.loop_execution_completed.value,
            Mock(step_name="retry_loop", step_id="l1"),
            state,
            stream,
        )
        assert state.task_cards["wf_loop_l1"].status == "complete"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "started,completed,prefix",
        [
            (
                WorkflowRunEvent.parallel_execution_started,
                WorkflowRunEvent.parallel_execution_completed,
                "wf_parallel_",
            ),
            (WorkflowRunEvent.condition_execution_started, WorkflowRunEvent.condition_execution_completed, "wf_cond_"),
            (WorkflowRunEvent.router_execution_started, WorkflowRunEvent.router_execution_completed, "wf_router_"),
            (WorkflowRunEvent.steps_execution_started, WorkflowRunEvent.steps_execution_completed, "wf_steps_"),
        ],
    )
    async def test_structural_pairs(self, started, completed, prefix):
        state = StreamState()
        stream = _stream()
        sid = "x1"
        chunk_start = Mock(step_name="test", step_id=sid)
        await _process_event(started.value, chunk_start, state, stream)
        key = f"{prefix}{sid}"
        assert key in state.task_cards
        assert state.task_cards[key].status == "in_progress"

        chunk_end = Mock(step_name="test", step_id=sid)
        await _process_event(completed.value, chunk_end, state, stream)
        assert state.task_cards[key].status == "complete"

    @pytest.mark.asyncio
    async def test_workflow_agent_started_completed(self):
        state = StreamState()
        stream = _stream()
        await _process_event(
            WorkflowRunEvent.workflow_agent_started.value,
            Mock(agent_name="Researcher", step_id="a1"),
            state,
            stream,
        )
        assert "wf_agent_a1" in state.task_cards
        await _process_event(
            WorkflowRunEvent.workflow_agent_completed.value,
            Mock(agent_name="Researcher", step_id="a1"),
            state,
            stream,
        )
        assert state.task_cards["wf_agent_a1"].status == "complete"


# ── Normalization ──────────────────────────────────────────────────


class TestNormalization:
    @pytest.mark.asyncio
    async def test_team_events_normalized(self):
        state = StreamState()
        stream = _stream()
        chunk = _chunk(TeamRunEvent.run_content.value, content="team hello")
        await _process_event(TeamRunEvent.run_content.value, chunk, state, stream)
        assert state.text_buffer == "team hello"

    @pytest.mark.asyncio
    async def test_unknown_event_returns_false(self):
        state = StreamState()
        stream = _stream()
        result = await _process_event("CompletelyUnknownEvent", _chunk("CompletelyUnknownEvent"), state, stream)
        assert result is False
        assert state.text_buffer == ""
        stream.append.assert_not_called()
