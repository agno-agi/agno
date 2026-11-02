"""Unit tests for the session metrics of a continued run: each run is in them once, whatever the retries."""

from typing import Any, AsyncIterator, Iterator, List, Union
from unittest.mock import patch

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunCompletedEvent, RunPausedEvent
from agno.run.base import RunStatus
from agno.tools import tool


class ScriptedModel(Model):
    """Minimal offline model: answers each call with the next of the given responses, or raises it."""

    def __init__(self, responses: List[Union[ModelResponse, Exception]]):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._responses = responses

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def _next(self) -> ModelResponse:
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


@tool(requires_confirmation=True)
def delete_file(path: str) -> str:
    """Delete a file."""
    return f"Deleted {path}"


def count_files() -> str:
    """Count the files."""
    return "3 files"


USAGE = MessageMetrics(input_tokens=6, output_tokens=4, total_tokens=10)


def _tool_call(name: str, arguments: str) -> ModelResponse:
    return ModelResponse(
        role="assistant",
        tool_calls=[{"id": f"call-{name}", "type": "function", "function": {"name": name, "arguments": arguments}}],
        response_usage=USAGE,
    )


@pytest.mark.parametrize("cache_session", [True, False])
async def test_retried_async_continue_keeps_the_run_once_in_the_session_metrics(tmp_path, cache_session):
    """A continue that fails after a model call and is retried takes the run's earlier tokens out of the session
    metrics once, as the session read holds them, so they match the run, whether the session is cached or read again.
    """
    agent = Agent(
        model=ScriptedModel(
            [
                _tool_call("delete_file", '{"path": "a"}'),
                _tool_call("count_files", "{}"),
                RuntimeError("provider unavailable"),
                ModelResponse(role="assistant", content="done", response_usage=USAGE),
            ]
        ),
        tools=[delete_file, count_files],
        db=SqliteDb(db_file=str(tmp_path / "agent.db")),
        cache_session=cache_session,
        retries=1,
        delay_between_retries=0,
        telemetry=False,
    )

    paused = await agent.arun("delete a", session_id="s")
    for requirement in paused.active_requirements:
        requirement.confirm()
    run_output = await agent.acontinue_run(run_response=paused, session_id="s")

    session_metrics = agent.get_session("s").session_data["session_metrics"]
    assert session_metrics["total_tokens"] == run_output.metrics.total_tokens == 30


def test_checkpointed_run_is_counted_once_in_the_session_metrics(tmp_path):
    """A tool-batch checkpoint writes the running run to the session, so its final write counts the run once."""
    agent = Agent(
        model=ScriptedModel(
            [_tool_call("count_files", "{}"), ModelResponse(role="assistant", content="done", response_usage=USAGE)]
        ),
        tools=[count_files],
        db=SqliteDb(db_file=str(tmp_path / "agent.db")),
        checkpoint="tool-batch",
        telemetry=False,
    )

    run_output = agent.run("count", session_id="s")

    assert (
        agent.get_session("s").session_data["session_metrics"]["total_tokens"] == run_output.metrics.total_tokens == 20
    )


async def test_continued_run_duration_is_its_wall_clock_time(tmp_path):
    """A continued run's duration runs from its start to its end, the wait for the continue included."""
    clock = [100.0]

    class TimedModel(ScriptedModel):
        """Each model call takes one second on the fake clock."""

        def _next(self) -> ModelResponse:
            clock[0] += 1.0
            return super()._next()

    agent = Agent(
        model=TimedModel(
            [
                _tool_call("delete_file", '{"path": "a"}'),
                ModelResponse(role="assistant", content="done", response_usage=USAGE),
            ]
        ),
        tools=[delete_file],
        db=SqliteDb(db_file=str(tmp_path / "agent.db")),
        telemetry=False,
    )

    with patch("agno.utils.timer.perf_counter", side_effect=lambda: clock[0]):
        paused = await agent.arun("delete a", session_id="s")
        paused_duration = paused.metrics.duration
        for requirement in paused.active_requirements:
            requirement.confirm()
        clock[0] += 50.0
        run_output = await agent.acontinue_run(run_response=paused, session_id="s")

    assert paused_duration == 1.0
    assert run_output.metrics.duration == 52.0


def test_run_read_back_resumes_its_timer_from_created_at():
    """A run read back has no timer, so its continued duration counts from created_at, the run's start."""
    from agno.metrics import RunMetrics

    metrics = RunMetrics(duration=1.0)
    with patch("agno.metrics.time", return_value=1052.0), patch("agno.utils.timer.perf_counter", return_value=500.0):
        metrics.resume_timer(created_at=1000)
    with patch("agno.utils.timer.perf_counter", return_value=501.0):
        metrics.stop_timer()

    assert metrics.duration == 53.0


def _stored_totals(agent: Agent, session_id: str):
    session = agent.get_session(session_id)
    return session.session_data["session_metrics"]["total_tokens"], sum(
        run.metrics.total_tokens for run in session.runs
    )


def test_continue_stream_closed_after_its_first_event_keeps_the_run_counted(tmp_path):
    """A continue stream closed before the run wrote itself back puts the run back in the session metrics, so a
    later continue by run id counts it once."""
    answer = ModelResponse(role="assistant", content="done", response_usage=USAGE)
    agent = Agent(
        model=ScriptedModel([_tool_call("delete_file", '{"path": "a"}'), answer, answer]),
        tools=[delete_file],
        db=SqliteDb(db_file=str(tmp_path / "agent.db")),
        cache_session=True,
        telemetry=False,
    )

    paused = agent.run("delete a", session_id="s")
    for requirement in paused.active_requirements:
        requirement.confirm()
    stream = agent.continue_run(run_response=paused, session_id="s", stream=True)
    next(stream)
    stream.close()
    agent.continue_run(run_id=paused.run_id, requirements=paused.requirements, session_id="s")

    session_total, runs_total = _stored_totals(agent, "s")
    assert session_total == runs_total


def test_continue_stream_closed_after_it_completes_counts_the_run_once(tmp_path):
    """A continue stream closed after the run wrote itself back leaves the session metrics as the run wrote them."""
    agent = Agent(
        model=ScriptedModel(
            [
                _tool_call("delete_file", '{"path": "a"}'),
                ModelResponse(role="assistant", content="done", response_usage=USAGE),
            ]
        ),
        tools=[delete_file],
        db=SqliteDb(db_file=str(tmp_path / "agent.db")),
        cache_session=True,
        telemetry=False,
    )

    paused = agent.run("delete a", session_id="s")
    for requirement in paused.active_requirements:
        requirement.confirm()
    stream = agent.continue_run(run_response=paused, session_id="s", stream=True, stream_events=True)
    for event in stream:
        if isinstance(event, RunCompletedEvent):
            break
    stream.close()

    assert _stored_totals(agent, "s") == (20, 20)


def test_continue_stream_closed_after_it_pauses_again_counts_the_run_once(tmp_path):
    """A continue stream closed after the run paused again and wrote itself back leaves the session metrics as the
    run wrote them, so a later continue by run id counts it once."""
    agent = Agent(
        model=ScriptedModel(
            [
                _tool_call("delete_file", '{"path": "a"}'),
                ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {
                            "id": "call-b",
                            "type": "function",
                            "function": {"name": "delete_file", "arguments": '{"path": "b"}'},
                        }
                    ],
                    response_usage=USAGE,
                ),
                ModelResponse(role="assistant", content="done", response_usage=USAGE),
            ]
        ),
        tools=[delete_file],
        db=SqliteDb(db_file=str(tmp_path / "agent.db")),
        cache_session=True,
        telemetry=False,
    )

    paused = agent.run("delete a and b", session_id="s")
    for requirement in paused.active_requirements:
        requirement.confirm()
    stream = agent.continue_run(run_response=paused, session_id="s", stream=True, stream_events=True)
    for event in stream:
        if isinstance(event, RunPausedEvent):
            break
    stream.close()
    for requirement in event.requirements:
        if not requirement.is_resolved():
            requirement.confirm()
    agent.continue_run(run_id=paused.run_id, requirements=event.requirements, session_id="s")

    assert _stored_totals(agent, "s") == (30, 30)


def test_continue_interrupted_in_a_confirmed_tool_keeps_the_run_counted(tmp_path):
    """A KeyboardInterrupt in a confirmed tool cancels the continued run, which writes itself back to the session
    metrics."""

    @tool(requires_confirmation=True)
    def interrupt(path: str) -> str:
        """Delete a file."""
        raise KeyboardInterrupt()

    agent = Agent(
        model=ScriptedModel([_tool_call("interrupt", '{"path": "a"}')]),
        tools=[interrupt],
        db=SqliteDb(db_file=str(tmp_path / "agent.db")),
        cache_session=True,
        telemetry=False,
    )

    paused = agent.run("delete a", session_id="s")
    for requirement in paused.active_requirements:
        requirement.confirm()
    run_output = agent.continue_run(run_response=paused, session_id="s")

    assert run_output.status == RunStatus.cancelled
    assert _stored_totals(agent, "s") == (10, 10)
