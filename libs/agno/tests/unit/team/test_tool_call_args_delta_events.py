"""Teams emit a tool call's argument fragments where a call can be made.

The team model, the team's output model and the chunk handler exposed on the
Team class all sit on a stream of provider deltas, so a caller that renders a
tool call while its arguments are still arriving must see fragments from each.
A member agent's own calls reach the caller through the team as well, and a
team run told not to stream events delivers neither its own nor its members'.

A fragment is attributed exactly the way Agno's own tool call aggregators
attribute it: one entry per provider stream index, a missing index read as
zero, and an entry's id taken from whichever of its deltas last carried one.
Those indexes restart at zero every turn, and the turn ends when the run takes
a call up, so a later turn's fragment that carries no id of its own must not
land on an earlier turn's finished call. Nothing else is held back or
rewritten: a stream that restarts offers its fragments again and they go out
again.
"""

import asyncio
import json
import logging
from contextlib import contextmanager
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

import pytest
from pydantic import BaseModel

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.agent import RunEvent
from agno.run.team import TeamRunEvent, TeamRunOutput
from agno.session import TeamSession
from agno.team import Team
from agno.tools import tool
from agno.utils import log as agno_log
from agno.utils.tools import REFUSED_TOOL_CALL_ERROR, ToolCallArgsStream


class _ScriptedStreamModel(Model):
    """Replays a fixed script of provider deltas, one turn per model call.

    Each entry in ``turns`` is the list of deltas for one turn. The script is
    finite: a call past its end fails the test rather than replaying a turn,
    so a run that loops longer than intended is visible instead of silent.
    """

    def __init__(self, turns: List[List[ModelResponse]]):
        super().__init__(id="scripted-stream", name="scripted-stream", provider="test")
        self._turns = list(turns)
        self._turn = 0

    def _next_turn(self) -> List[ModelResponse]:
        assert self._turn < len(self._turns), f"model called {self._turn + 1} times, script holds {len(self._turns)}"
        turn = self._turns[self._turn]
        self._turn += 1
        return turn

    @property
    def turns_taken(self) -> int:
        """Turns the run has asked for, so a test can say the run really ran."""
        return self._turn

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield from self._next_turn()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        for delta in self._next_turn():
            yield delta

    def _aggregate_turn(self) -> ModelResponse:
        """The same turn as one finished response, for the non-streaming path."""
        turn = self._next_turn()
        aggregated = ModelResponse(role="assistant")
        fragments = [call for delta in turn for call in (delta.tool_calls or [])]
        if fragments:
            aggregated.tool_calls = self.parse_tool_calls(fragments)
        content = "".join(delta.content for delta in turn if isinstance(delta.content, str))
        if content:
            aggregated.content = content
        return aggregated

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._aggregate_turn()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._aggregate_turn()

    def _parse_provider_response(self, response, **kwargs) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def parse_tool_calls(self, tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Reassemble the fragments by index, as OpenAI-compatible models do."""
        calls: Dict[int, Dict[str, Any]] = {}
        order: List[int] = []
        for fragment in tool_calls_data:
            index = fragment.get("index", 0)
            if index not in calls:
                calls[index] = {"id": None, "type": "function", "function": {"name": "", "arguments": ""}}
                order.append(index)
            entry = calls[index]
            if fragment.get("id"):
                entry["id"] = fragment["id"]
            function = fragment.get("function") or {}
            if function.get("name"):
                entry["function"]["name"] = function["name"]
            if function.get("arguments"):
                entry["function"]["arguments"] += function["arguments"]
        return [calls[index] for index in order]


def _fragment(
    index: int,
    arguments: str = "",
    tool_call_id: Optional[str] = None,
    tool_name: Optional[str] = None,
) -> ModelResponse:
    function: Dict[str, Any] = {"arguments": arguments}
    if tool_name is not None:
        function["name"] = tool_name
    tool_call: Dict[str, Any] = {"index": index, "type": "function", "function": function}
    if tool_call_id is not None:
        tool_call["id"] = tool_call_id
    return ModelResponse(role="assistant", tool_calls=[tool_call])


def _unnumbered_fragment(
    arguments: str = "",
    tool_call_id: Optional[str] = None,
    tool_name: Optional[str] = None,
) -> ModelResponse:
    """One fragment from a provider that puts no stream index on its deltas."""
    function: Dict[str, Any] = {"arguments": arguments}
    if tool_name is not None:
        function["name"] = tool_name
    tool_call: Dict[str, Any] = {"type": "function", "function": function}
    if tool_call_id is not None:
        tool_call["id"] = tool_call_id
    return ModelResponse(role="assistant", tool_calls=[tool_call])


def _chunks(text: str, size: int) -> List[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def save_note(note: str) -> str:
    """Save a note.

    Args:
        note: the note to save
    """
    return "saved"


def save_other(note: str) -> str:
    """Save a note somewhere else.

    Args:
        note: the note to save
    """
    return "saved"


class _Note(BaseModel):
    note: str


CHUNK_SIZE = 5


def _tool_call_turns(tool_call_id: str, tool_name: str = "save_note") -> Tuple[List[List[ModelResponse]], str]:
    """One turn streaming a single tool call in fragments, then a reply turn."""
    arguments = json.dumps({"note": "the sea is wide and the boat is small"})
    fragments = [_fragment(0, tool_call_id=tool_call_id, tool_name=tool_name)]
    fragments += [_fragment(0, chunk) for chunk in _chunks(arguments, CHUNK_SIZE)]
    return [fragments, [ModelResponse(role="assistant", content="done")]], arguments


@contextmanager
def _records_logged_at(level: int) -> Iterator[List[logging.LogRecord]]:
    """Everything Agno logs at ``level`` or above, whichever logger carried it.

    ``log_error`` writes to a process-global logger that a team run rebinds to
    the team logger and never rebinds back, so the same line is carried by one
    logger or another depending on what else ran earlier in the process. What
    these tests assert is what a run reported, so they read every logger the
    helper can be bound to and stay out of that.
    """
    records: List[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collector(level)
    loggers = list(
        {id(value): value for value in vars(agno_log).values() if isinstance(value, logging.Logger)}.values()
    )
    for agno_logger in loggers:
        agno_logger.addHandler(handler)
    try:
        yield records
    finally:
        for agno_logger in loggers:
            agno_logger.removeHandler(handler)


@pytest.fixture
def errors_logged() -> Iterator[List[logging.LogRecord]]:
    with _records_logged_at(logging.ERROR) as records:
        yield records


@pytest.fixture
def warnings_logged() -> Iterator[List[logging.LogRecord]]:
    with _records_logged_at(logging.WARNING) as records:
        yield records


def _events_named(events, event_name: str):
    return [event for event in events if event.event == event_name]


def _content_of(events) -> str:
    """The reply a caller assembles out of the run's content events."""
    return "".join(event.content for event in _events_named(events, TeamRunEvent.run_content.value))


def _assert_fragments_assemble(events, arguments: str, tool_call_id: str, tool_name: str) -> None:
    deltas = _events_named(events, TeamRunEvent.tool_call_args_delta.value)
    assert len(deltas) == len(_chunks(arguments, CHUNK_SIZE))
    assert "".join(delta.tool_args_delta for delta in deltas) == arguments
    assert {delta.tool_call_id for delta in deltas} == {tool_call_id}
    assert {delta.tool_name for delta in deltas} == {tool_name}


# ---------------------------------------------------------------------------
# Team model
# ---------------------------------------------------------------------------


def test_team_streams_tool_call_arg_fragments():
    turns, arguments = _tool_call_turns("call_team")
    team = Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_note])

    events = list(team.run("go", stream=True, stream_events=True))

    _assert_fragments_assemble(events, arguments, "call_team", "save_note")

    # The finished events still arrive unchanged, and agree with the fragments.
    started = _events_named(events, TeamRunEvent.tool_call_started.value)
    assert len(started) == 1
    assert started[0].tool.tool_call_id == "call_team"
    assert started[0].tool.tool_args == json.loads(arguments)


async def test_team_streams_tool_call_arg_fragments_async():
    turns, arguments = _tool_call_turns("call_team")
    team = Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_note])

    events = [event async for event in team.arun("go", stream=True, stream_events=True)]

    _assert_fragments_assemble(events, arguments, "call_team", "save_note")


def test_team_streams_the_whole_arguments_of_a_provider_that_numbers_no_call():
    """A provider that puts no index on any delta still streams every fragment.

    Agno's own aggregators, the OpenAI chat, watsonx, cerebras and litellm
    ones among them, read a missing index as zero, so every one of these
    deltas belongs to the one call the turn made.
    """
    arguments = json.dumps({"note": "the sea is wide and the boat is small"})
    fragments = [_unnumbered_fragment(tool_call_id="call_team", tool_name="save_note")]
    fragments += [_unnumbered_fragment(chunk) for chunk in _chunks(arguments, CHUNK_SIZE)]
    turns = [fragments, [ModelResponse(role="assistant", content="done")]]
    team = Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_note])

    events = list(team.run("go", stream=True, stream_events=True))

    _assert_fragments_assemble(events, arguments, "call_team", "save_note")
    # What the client was sent is what the run itself assembled.
    started = _events_named(events, TeamRunEvent.tool_call_started.value)
    assert [json.dumps(event.tool.tool_args) for event in started] == [arguments]


def test_team_emits_no_fragments_without_stream_events():
    turns, _ = _tool_call_turns("call_team")
    model = _ScriptedStreamModel(turns)
    team = Team(members=[], model=model, tools=[save_note])

    events = list(team.run("go", stream=True, stream_events=False))

    # The run took the tool call turn and the reply turn after it and answered,
    # so what is absent below is fragments rather than the whole stream.
    assert model.turns_taken == len(turns)
    assert _content_of(events) == "done"
    assert not _events_named(events, TeamRunEvent.tool_call_args_delta.value)


# ---------------------------------------------------------------------------
# Member agents
# ---------------------------------------------------------------------------

_DELEGATE_TOOL = "delegate_task_to_member"


def _delegating_turns(member_id: str) -> Tuple[List[List[ModelResponse]], str]:
    """A leader turn that streams its delegation call in fragments."""
    arguments = json.dumps({"member_id": member_id, "task": "write the note"})
    fragments = [_fragment(0, tool_call_id="call_lead", tool_name=_DELEGATE_TOOL)]
    fragments += [_fragment(0, chunk) for chunk in _chunks(arguments, CHUNK_SIZE)]
    return [fragments, [ModelResponse(role="assistant", content="done")]], arguments


def _team_with_a_calling_member() -> Tuple[Team, str, str]:
    """A leader that delegates to a member, and a member that calls a tool."""
    member_turns, member_arguments = _tool_call_turns("call_member")
    leader_turns, leader_arguments = _delegating_turns("writer")
    member = Agent(name="writer", model=_ScriptedStreamModel(member_turns), tools=[save_note])
    return Team(members=[member], model=_ScriptedStreamModel(leader_turns)), leader_arguments, member_arguments


def _fragments_by_event(events) -> Dict[str, str]:
    """What a caller assembles from each of the two fragment event names.

    A member agent sends its fragments under its own name, the leader under
    the team's, so a team run carries both.
    """
    return {
        name: "".join(event.tool_args_delta for event in _events_named(events, name))
        for name in (RunEvent.tool_call_args_delta.value, TeamRunEvent.tool_call_args_delta.value)
    }


def _assert_both_the_leaders_and_the_members_call_streamed(events, leader: str, member: str) -> None:
    """Every fragment of both calls reached the caller, under its own call id."""
    assert _fragments_by_event(events) == {
        TeamRunEvent.tool_call_args_delta.value: leader,
        RunEvent.tool_call_args_delta.value: member,
    }
    member_deltas = _events_named(events, RunEvent.tool_call_args_delta.value)
    assert {delta.tool_call_id for delta in member_deltas} == {"call_member"}
    assert {delta.tool_name for delta in member_deltas} == {"save_note"}
    # The member made that call on those arguments, so the fragments and the
    # run agree about what its model asked for.
    completed = _events_named(events, RunEvent.tool_call_completed.value)
    assert [json.dumps(event.tool.tool_args) for event in completed] == [member]


def test_team_streams_a_members_tool_call_arg_fragments():
    team, leader, member = _team_with_a_calling_member()

    events = list(team.run("go", stream=True, stream_events=True))

    _assert_both_the_leaders_and_the_members_call_streamed(events, leader, member)


async def test_team_streams_a_members_tool_call_arg_fragments_async():
    team, leader, member = _team_with_a_calling_member()

    events = [event async for event in team.arun("go", stream=True, stream_events=True)]

    _assert_both_the_leaders_and_the_members_call_streamed(events, leader, member)


def _assert_a_run_told_not_to_stream_events_delivers_no_fragments(events, member_arguments: str) -> None:
    """A team run told not to stream events is told that of its members too.

    A member is run with events on whatever the caller asked for, so that the
    leader can read them, and they reach the caller through the team. So a
    guard on the team's own model alone leaves a caller that opted out holding
    its members' fragments.
    """
    assert _fragments_by_event(events) == {
        TeamRunEvent.tool_call_args_delta.value: "",
        RunEvent.tool_call_args_delta.value: "",
    }
    # The member ran and made its call, and its other events arrive as before,
    # so the absence above is the flag's doing and not an empty stream.
    completed = _events_named(events, RunEvent.tool_call_completed.value)
    assert [json.dumps(event.tool.tool_args) for event in completed] == [member_arguments]
    assert _events_named(events, RunEvent.run_started.value)


def test_team_delivers_no_members_fragments_without_stream_events():
    team, _leader, member = _team_with_a_calling_member()

    events = list(team.run("go", stream=True, stream_events=False))

    _assert_a_run_told_not_to_stream_events_delivers_no_fragments(events, member)


async def test_team_delivers_no_members_fragments_without_stream_events_async():
    team, _leader, member = _team_with_a_calling_member()

    events = [event async for event in team.arun("go", stream=True, stream_events=False)]

    _assert_a_run_told_not_to_stream_events_delivers_no_fragments(events, member)


# ---------------------------------------------------------------------------
# Team output model
# ---------------------------------------------------------------------------


class _ToolRecordingModel(_ScriptedStreamModel):
    """Remembers the tools it was handed, once per stream it was asked for.

    A path that hands its model none of the run's tools can still be answered
    with a call, because a provider can call a built-in tool of its own, so
    what the path passed is worth pinning beside what came back.
    """

    def __init__(self, turns: List[List[ModelResponse]]):
        super().__init__(turns)
        self.tools_seen: List[Optional[List[Any]]] = []

    def response_stream(self, *args, **kwargs):
        self.tools_seen.append(kwargs.get("tools"))
        return super().response_stream(*args, **kwargs)

    def aresponse_stream(self, *args, **kwargs):
        self.tools_seen.append(kwargs.get("tools"))
        return super().aresponse_stream(*args, **kwargs)


def _team_with_a_recording_output_model() -> Tuple[Team, _ToolRecordingModel, str]:
    """An output model whose script calls a tool, over a quiet team model."""
    output_turns, arguments = _tool_call_turns("call_output", tool_name="save_output")
    output_model = _ToolRecordingModel(output_turns)
    team = Team(
        members=[Agent(name="member", model=_ScriptedStreamModel([]))],
        model=_ScriptedStreamModel([[ModelResponse(role="assistant", content="draft")]]),
        output_model=output_model,
        tools=[save_note],
    )
    return team, output_model, arguments


def _assert_the_output_models_call_reached_the_client(
    events, output_model: _ToolRecordingModel, arguments: str, errors: List[logging.LogRecord]
) -> None:
    """A call can arrive here even though the path hands the model no tools.

    The output model is asked for the finished answer, never for work, so the
    run passes it none of the team's tools. A provider can still answer with a
    call to a built-in tool of its own, and then its fragments have to be
    attributed and its call closed out like any other. The script stands in for
    that provider, and the run refuses to find the function, which is why the
    call the client was shown ends as a reported failure rather than as one it
    waits on for good.
    """
    assert output_model.tools_seen == [None]
    assert output_model.turns_taken == 2, "the output model did not run its whole script"
    assert _content_of(events) == "done"
    _assert_fragments_assemble(events, arguments, "call_output", "save_output")
    reported = _events_named(events, TeamRunEvent.tool_call_error.value)
    assert [event.tool.tool_call_id for event in reported] == ["call_output"]
    assert reported[0].error == REFUSED_TOOL_CALL_ERROR
    assert [record.getMessage() for record in errors] == ["Function save_output not found"]


def test_team_output_model_streams_and_closes_out_a_tool_call(errors_logged):
    team, output_model, arguments = _team_with_a_recording_output_model()

    events = list(team.run("go", stream=True, stream_events=True))

    _assert_the_output_models_call_reached_the_client(events, output_model, arguments, errors_logged)


async def test_team_output_model_streams_and_closes_out_a_tool_call_async(errors_logged):
    team, output_model, arguments = _team_with_a_recording_output_model()

    events = [event async for event in team.arun("go", stream=True, stream_events=True)]

    _assert_the_output_models_call_reached_the_client(events, output_model, arguments, errors_logged)


def _team_with_a_two_turn_output_model() -> Tuple[Team, str, str]:
    """An output model that calls a tool on each of two turns of its own."""
    turns, first, second = _two_turn_calls()
    return (
        Team(
            members=[Agent(name="member", model=_ScriptedStreamModel([]))],
            model=_ScriptedStreamModel([[ModelResponse(role="assistant", content="draft")]]),
            output_model=_ToolRecordingModel(turns),
            tools=[save_note, save_other],
        ),
        first,
        second,
    )


def _assert_the_output_models_turns_are_held_apart(
    events, first: str, second: str, warnings: List[logging.LogRecord]
) -> None:
    """This path's turn boundary is the request event the chunk handler sees.

    The team's own loop reads that event itself, so nothing but the chunk
    handler bounds a turn here. Without it the second turn's opening fragment,
    which carries index zero and no id, would be appended to the arguments the
    first turn's call was already made with. Bounded, that fragment belongs to
    no call yet, and the run says so instead of placing it.
    """
    assert _assembled(events, "call_a") == first
    assert _assembled(events, "call_b") == second[4:]
    reported = [record.getMessage() for record in warnings if record.levelno == logging.WARNING]
    assert len(reported) == 1, reported
    assert "neither a tool call id nor a provider stream index" in reported[0]


def test_team_output_model_does_not_carry_tool_call_ids_across_its_turns(warnings_logged):
    team, first, second = _team_with_a_two_turn_output_model()

    events = list(team.run("go", stream=True, stream_events=True))

    _assert_the_output_models_turns_are_held_apart(events, first, second, warnings_logged)


async def test_team_output_model_does_not_carry_tool_call_ids_across_its_turns_async(warnings_logged):
    team, first, second = _team_with_a_two_turn_output_model()

    events = [event async for event in team.arun("go", stream=True, stream_events=True)]

    _assert_the_output_models_turns_are_held_apart(events, first, second, warnings_logged)


_ANNOUNCED_ARGUMENTS = json.dumps({"title": "the plan", "thought": "the sea is wide"})


def _announced_call_chunks() -> List[ModelResponse]:
    """The chunks a provider writes for a built-in tool it ran itself.

    First the call's arguments a fragment at a time, then the two chunks the
    provider announces the finished call with, then its closing reply. The
    call is named ``think``, which is also how the run recognises a reasoning
    step, so one script covers every announcement this path can carry.
    """
    execution = ToolExecution(
        tool_call_id="call_builtin",
        tool_name="think",
        tool_args=json.loads(_ANNOUNCED_ARGUMENTS),
        result="thought about it",
    )
    chunks = [_fragment(0, tool_call_id="call_builtin", tool_name="think")]
    chunks += [_fragment(0, chunk) for chunk in _chunks(_ANNOUNCED_ARGUMENTS, CHUNK_SIZE)]
    chunks.append(
        ModelResponse(
            content="think(...)",
            tool_executions=[execution],
            event=ModelResponseEvent.tool_call_started.value,
        )
    )
    chunks.append(
        ModelResponse(
            content="thought about it",
            tool_executions=[execution],
            event=ModelResponseEvent.tool_call_completed.value,
        )
    )
    chunks.append(ModelResponse(role="assistant", content="done"))
    return chunks


class _ProviderAnnouncingModel(_ScriptedStreamModel):
    """A provider that ran a built-in tool of its own and announces the call.

    This path hands its model none of the run's tools, so the shared function
    call machinery has no function to find and never announces a call here. A
    provider that ran a built-in tool is the only thing that can, and it does
    so in its own stream, which is what this stands in for.
    """

    def __init__(self):
        super().__init__([])
        self._script = _announced_call_chunks()

    def response_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        return iter(self._script)

    async def aresponse_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        for chunk in self._script:
            yield chunk


def _team_with_an_announcing_output_model() -> Team:
    return Team(
        members=[Agent(name="member", model=_ScriptedStreamModel([]))],
        model=_ScriptedStreamModel([[ModelResponse(role="assistant", content="draft")]]),
        output_model=_ProviderAnnouncingModel(),
    )


def _assert_the_output_model_path_adds_only_the_fragments(events) -> None:
    """The fragments are what this path gained; its silence is as it was.

    A team's output model path has never announced a call the output model
    made, nor read one as a reasoning step, and threading it the record that
    attributes a call's argument fragments does not change that. An agent's
    output model path does announce both. That difference between the two is
    older than the fragments and is left alone here, because changing which
    lifecycle events a client sees is a decision of its own and not something
    to thread a fragment stream into.
    """
    _assert_fragments_assemble(events, _ANNOUNCED_ARGUMENTS, "call_builtin", "think")
    assert not _events_named(events, TeamRunEvent.tool_call_started.value)
    assert not _events_named(events, TeamRunEvent.tool_call_completed.value)
    assert not _events_named(events, TeamRunEvent.reasoning_step.value)
    assert not _events_named(events, TeamRunEvent.tool_call_error.value)


def test_team_output_model_adds_only_the_argument_fragments():
    team = _team_with_an_announcing_output_model()

    events = list(team.run("go", stream=True, stream_events=True))

    _assert_the_output_model_path_adds_only_the_fragments(events)


async def test_team_output_model_adds_only_the_argument_fragments_async():
    team = _team_with_an_announcing_output_model()

    events = [event async for event in team.arun("go", stream=True, stream_events=True)]

    _assert_the_output_model_path_adds_only_the_fragments(events)


# ---------------------------------------------------------------------------
# Chunk handler on the Team class
# ---------------------------------------------------------------------------


@pytest.fixture
def chunk_handler_team() -> Team:
    return Team(members=[], model=_ScriptedStreamModel([]))


def test_team_chunk_handler_carries_tool_call_identities_across_chunks(chunk_handler_team: Team):
    """A later fragment names its call only through the per-stream record.

    The record reaches the handler through the wrapper on the Team class, so
    this also holds the wrapper to forwarding it.
    """
    session = TeamSession(session_id="session_1")
    run_response = TeamRunOutput(run_id="run_1", team_id="team_1", team_name="Team")
    tool_args_stream = ToolCallArgsStream(session.session_id, run_response.run_id)

    first = _fragment(0, tool_call_id="call_a", tool_name="save_note")
    later = _fragment(0, '{"note":')
    assert later.tool_calls[0].get("id") is None

    events = []
    for chunk in (first, later):
        chunk.event = ModelResponseEvent.assistant_response.value
        events.extend(
            chunk_handler_team._handle_model_response_chunk(
                session=session,
                run_response=run_response,
                full_model_response=ModelResponse(),
                model_response_event=chunk,
                stream_events=True,
                tool_args_stream=tool_args_stream,
            )
        )

    deltas = _events_named(events, TeamRunEvent.tool_call_args_delta.value)
    assert len(deltas) == 1
    assert deltas[0].tool_call_id == "call_a"
    assert deltas[0].tool_name == "save_note"
    assert deltas[0].tool_args_delta == '{"note":'


def _through_the_chunk_handler(team: Team, tool_args_stream: ToolCallArgsStream, chunks) -> List[Any]:
    """Every event the handler yields for a run of chunks, in order."""
    session = TeamSession(session_id="session_1")
    run_response = TeamRunOutput(run_id="run_1", team_id="team_1", team_name="Team")
    events: List[Any] = []
    for chunk in chunks:
        events.extend(
            team._handle_model_response_chunk(
                session=session,
                run_response=run_response,
                full_model_response=ModelResponse(),
                model_response_event=chunk,
                stream_events=True,
                tool_args_stream=tool_args_stream,
            )
        )
    return events


def test_team_chunk_handler_drops_its_stream_indexes_when_a_fallback_is_activated(
    chunk_handler_team: Team, warnings_logged
):
    """A replaced model's numbering is not the numbering of the one taking over.

    A fallback model answers the request the primary failed part way through,
    and its stream indexes start again at zero. Without a boundary there, its
    opening fragment, which carries index zero and no id, would be appended to
    the arguments of the call the replaced model was still writing, and a
    subscriber would render two models' text as one call's arguments.
    """
    tool_args_stream = ToolCallArgsStream("session_1", "run_1")
    replaced = _fragment(0, '{"note":', tool_call_id="call_a", tool_name="save_note")
    replaced.event = ModelResponseEvent.assistant_response.value
    taking_over = _fragment(0, ' "the sea is wide"}')
    taking_over.event = ModelResponseEvent.assistant_response.value

    events = _through_the_chunk_handler(
        chunk_handler_team,
        tool_args_stream,
        (
            replaced,
            ModelResponse(event=ModelResponseEvent.fallback_model_activated.value),
            taking_over,
        ),
    )

    deltas = _events_named(events, TeamRunEvent.tool_call_args_delta.value)
    assert [(delta.tool_call_id, delta.tool_args_delta) for delta in deltas] == [("call_a", '{"note":')]
    # The fragment after the boundary belongs to no call yet, and the run says
    # so rather than placing it on the replaced model's call.
    reported = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
    assert len(reported) == 1, reported
    assert "neither a tool call id nor a provider stream index" in reported[0]
    # The replaced model's call will never be made under its own id either, so
    # the client is not left waiting on it.
    closed = _events_named(events, TeamRunEvent.tool_call_error.value)
    assert [event.tool.tool_call_id for event in closed] == ["call_a"]
    assert closed[0].error == REFUSED_TOOL_CALL_ERROR


# ---------------------------------------------------------------------------
# Parser model
# ---------------------------------------------------------------------------


class _NonStreamedCallModel(_ScriptedStreamModel):
    """Remembers the tool calls it handed back on the non-streamed path.

    The parser model is asked for a finished response inside its stream, so a
    test that path streams no fragments is only worth something if the model
    really did answer it with a call.
    """

    def __init__(self, turns: List[List[ModelResponse]]):
        super().__init__(turns)
        self.returned_tool_calls: List[Dict[str, Any]] = []

    def _aggregate_turn(self) -> ModelResponse:
        aggregated = super()._aggregate_turn()
        self.returned_tool_calls.extend(aggregated.tool_calls or [])
        return aggregated


def _parser_model_turns() -> List[List[ModelResponse]]:
    """One turn calling a tool in fragments, then one answering the output schema."""
    turns, _ = _tool_call_turns("call_parser")
    return [turns[0], [ModelResponse(role="assistant", content=json.dumps({"note": "parsed"}))]]


def _team_with_a_calling_parser_model() -> Tuple[Team, _NonStreamedCallModel]:
    parser = _NonStreamedCallModel(_parser_model_turns())
    team = Team(
        members=[Agent(name="member", model=_ScriptedStreamModel([]))],
        model=_ScriptedStreamModel([[ModelResponse(role="assistant", content=json.dumps({"note": "draft"}))]]),
        parser_model=parser,
        output_schema=_Note,
    )
    return team, parser


def _assert_the_parser_model_streamed_no_fragments(
    events, parser: _NonStreamedCallModel, errors: List[logging.LogRecord]
) -> None:
    """The parser model answers inside its stream with one finished response.

    A tool call therefore arrives already assembled and there are no fragments
    to attribute, which is why this path carries no per-stream record. A change
    that made the parser model stream its response would fail here rather than
    quietly dropping the fragments it started producing.
    """
    # A call really did arrive, already assembled, so the absence of fragments
    # is the path's doing and not an inert script.
    assert parser.returned_tool_calls, "the parser model no longer answers with one finished response"
    assert not _events_named(events, TeamRunEvent.tool_call_args_delta.value)
    assert not _events_named(events, RunEvent.tool_call_args_delta.value)
    # It is handed no tools either, so the run refuses to find the function it
    # named and says so once.
    assert [record.getMessage() for record in errors] == ["Function save_note not found"]


def test_team_parser_model_emits_no_tool_call_arg_fragments(errors_logged):
    team, parser = _team_with_a_calling_parser_model()

    events = list(team.run("go", stream=True, stream_events=True))

    _assert_the_parser_model_streamed_no_fragments(events, parser, errors_logged)


async def test_team_parser_model_emits_no_tool_call_arg_fragments_async(errors_logged):
    team, parser = _team_with_a_calling_parser_model()

    events = [event async for event in team.arun("go", stream=True, stream_events=True)]

    _assert_the_parser_model_streamed_no_fragments(events, parser, errors_logged)


# ---------------------------------------------------------------------------
# Event storage
# ---------------------------------------------------------------------------


def _team_storing_events(tmp_path, db_name: str, **kwargs) -> Tuple[Team, str]:
    turns, arguments = _tool_call_turns("call_team")
    team = Team(
        members=[],
        model=_ScriptedStreamModel(turns),
        tools=[save_note],
        db=SqliteDb(db_file=str(tmp_path / db_name)),
        store_events=True,
        **kwargs,
    )
    return team, arguments


def _stored(run_output) -> List[str]:
    return [event.event for event in (run_output.events or [])]


def test_team_keeps_tool_call_arg_fragments_out_of_the_stored_run_by_default(tmp_path):
    team, arguments = _team_storing_events(tmp_path, "default_team.db")

    events = list(team.run("go", stream=True, stream_events=True))
    run_output = team.get_last_run_output()

    # The subscriber still sees every fragment: the skip list governs storage.
    _assert_fragments_assemble(events, arguments, "call_team", "save_note")

    stored = _stored(run_output)
    assert TeamRunEvent.tool_call_args_delta.value not in stored
    # Held to the same standard as the content delta it is being grouped with,
    # and the low frequency events are stored as before.
    assert TeamRunEvent.run_content.value not in stored
    assert TeamRunEvent.tool_call_started.value in stored
    assert TeamRunEvent.tool_call_completed.value in stored


async def test_team_keeps_tool_call_arg_fragments_out_of_the_stored_run_by_default_async(tmp_path):
    team, arguments = _team_storing_events(tmp_path, "default_team_async.db")

    events = [event async for event in team.arun("go", stream=True, stream_events=True)]
    run_output = await team.aget_last_run_output()

    _assert_fragments_assemble(events, arguments, "call_team", "save_note")

    stored = _stored(run_output)
    assert TeamRunEvent.tool_call_args_delta.value not in stored
    assert TeamRunEvent.run_content.value not in stored
    assert TeamRunEvent.tool_call_started.value in stored


def test_team_stores_tool_call_arg_fragments_when_the_caller_asks_for_them(tmp_path, skips_but_the_argument_fragments):
    # Asking for the fragments back re-enables nothing else the default keeps
    # out of storage, the content deltas included.
    team, arguments = _team_storing_events(
        tmp_path,
        "opted_in_team.db",
        events_to_skip=skips_but_the_argument_fragments(Team(members=[], model=_ScriptedStreamModel([]))),
    )

    list(team.run("go", stream=True, stream_events=True))
    run_output = team.get_last_run_output()

    fragments = [event for event in (run_output.events or []) if event.event == TeamRunEvent.tool_call_args_delta.value]
    assert "".join(event.tool_args_delta for event in fragments) == arguments
    assert TeamRunEvent.run_content.value not in _stored(run_output)


def _team_storing_a_members_events(tmp_path, db_name: str, **kwargs) -> Tuple[Team, str, str]:
    """A leader that delegates to a member, both streaming a call, both stored."""
    member_turns, member_arguments = _tool_call_turns("call_member")
    leader_turns, leader_arguments = _delegating_turns("writer")
    team = Team(
        members=[Agent(name="writer", model=_ScriptedStreamModel(member_turns), tools=[save_note])],
        model=_ScriptedStreamModel(leader_turns),
        db=SqliteDb(db_file=str(tmp_path / db_name)),
        store_events=True,
        **kwargs,
    )
    return team, leader_arguments, member_arguments


def _stored_fragments(run_output, event_name: str) -> str:
    return "".join(event.tool_args_delta for event in (run_output.events or []) if event.event == event_name)


def test_team_keeps_its_members_tool_call_arg_fragments_out_of_the_stored_run_by_default(tmp_path):
    """A member's fragments are the team's to store, and by default it stores none.

    A member agent's calls reach the caller through the team, so the team's
    own default has to keep them out of its stored run as well as its
    leader's. A team run with real members would otherwise store every
    fragment of every member's every call.
    """
    team, leader, member = _team_storing_a_members_events(tmp_path, "default_member_team.db")

    events = list(team.run("go", stream=True, stream_events=True))
    run_output = team.get_last_run_output()

    # The caller still sees both calls stream: the skip list governs storage.
    _assert_both_the_leaders_and_the_members_call_streamed(events, leader, member)

    stored = _stored(run_output)
    assert RunEvent.tool_call_args_delta.value not in stored
    assert TeamRunEvent.tool_call_args_delta.value not in stored
    # The member really did run under this team, so the absence above is the
    # skip list's doing and not a run that never delegated.
    assert RunEvent.tool_call_completed.value in stored


def test_team_stores_its_members_tool_call_arg_fragments_when_the_caller_asks_for_them(
    tmp_path, skips_but_the_argument_fragments
):
    """Asked for, a member's fragments are stored under the member's own event name."""
    team, leader, member = _team_storing_a_members_events(
        tmp_path,
        "opted_in_member_team.db",
        events_to_skip=skips_but_the_argument_fragments(Team(members=[], model=_ScriptedStreamModel([]))),
    )

    list(team.run("go", stream=True, stream_events=True))
    run_output = team.get_last_run_output()

    assert _stored_fragments(run_output, RunEvent.tool_call_args_delta.value) == member
    assert _stored_fragments(run_output, TeamRunEvent.tool_call_args_delta.value) == leader
    # Asking for the fragments back re-enables nothing else the default keeps
    # out of storage, the content deltas of either name included.
    assert RunEvent.run_content.value not in _stored(run_output)
    assert TeamRunEvent.run_content.value not in _stored(run_output)


# Stream boundaries
# ---------------------------------------------------------------------------


class _DroppedStreamModel(_ScriptedStreamModel):
    """Dies part way through a turn, the way a provider stream that drops does.

    ``Model.retries`` restarts the whole stream, so the next attempt replays the
    turn from its first fragment, including the fragments the dead attempt had
    already delivered.
    """

    def __init__(self, turns: List[List[ModelResponse]], fail_after: int):
        super().__init__(turns)
        self._fail_after = fail_after
        self.attempts = 0
        self._pending: Optional[List[ModelResponse]] = None

    def _attempt_deltas(self) -> List[ModelResponse]:
        """The deltas of the turn under way, taken once and replayed on retry."""
        if self._pending is None:
            self._pending = self._next_turn()
        return self._pending

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        deltas = self._attempt_deltas()
        self.attempts += 1
        if self.attempts == 1:
            yield from deltas[: self._fail_after]
            raise ModelProviderError(message="stream dropped", model_name=self.name, model_id=self.id)
        self._pending = None
        yield from deltas

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        deltas = self._attempt_deltas()
        self.attempts += 1
        if self.attempts == 1:
            for delta in deltas[: self._fail_after]:
                yield delta
            raise ModelProviderError(message="stream dropped", model_name=self.name, model_id=self.id)
        self._pending = None
        for delta in deltas:
            yield delta


def _two_turn_calls() -> Tuple[List[List[ModelResponse]], str, str]:
    """Two tool call turns, the second opening with a fragment that has no id.

    A provider ties later fragments back to a call by an index that restarts at
    zero on every turn, so the second turn's opening fragment carries index zero
    and no id of its own. It belongs to the call the second turn goes on to
    announce, never to the first turn's finished call.
    """
    first = json.dumps({"note": "first"})
    second = json.dumps({"note": "second"})
    first_fragments = [_fragment(0, tool_call_id="call_a", tool_name="save_note")]
    first_fragments += [_fragment(0, chunk) for chunk in _chunks(first, CHUNK_SIZE)]
    second_fragments = [
        _fragment(0, second[:4]),
        _fragment(0, second[4:], tool_call_id="call_b", tool_name="save_other"),
    ]
    reply = [ModelResponse(role="assistant", content="done")]
    return [first_fragments, second_fragments, reply], first, second


def _assembled(events, tool_call_id: str) -> str:
    deltas = _events_named(events, TeamRunEvent.tool_call_args_delta.value)
    return "".join(delta.tool_args_delta for delta in deltas if delta.tool_call_id == tool_call_id)


def _assert_turns_stay_apart(events, first: str, second: str) -> None:
    """No turn's call carries any of another turn's argument text."""
    # The second turn's opening fragment carries index zero and no id, and the
    # indexes of a finished turn are dropped, so nothing places it: it is not
    # appended to the first turn's call.
    assert _assembled(events, "call_a") == first
    # What the provider does name of the second turn's call is streamed, head
    # or no head. The subscriber that renders it checks the assembled string
    # against the finished call rather than being handed a guess.
    assert _assembled(events, "call_b") == second[4:]
    announced = {
        event.tool.tool_call_id: event.tool.tool_args
        for event in _events_named(events, TeamRunEvent.tool_call_started.value)
    }
    assert announced["call_b"] == json.loads(second)


def test_team_does_not_carry_tool_call_ids_across_turns():
    turns, first, second = _two_turn_calls()
    team = Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_note, save_other])

    events = list(team.run("go", stream=True, stream_events=True))

    # One model request per scripted turn, so nothing here rides on the fake
    # having a turn left to hand out twice.
    assert len(_events_named(events, TeamRunEvent.model_request_started.value)) == len(turns)
    _assert_turns_stay_apart(events, first, second)


async def test_team_does_not_carry_tool_call_ids_across_turns_async():
    turns, first, second = _two_turn_calls()
    team = Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_note, save_other])

    events = [event async for event in team.arun("go", stream=True, stream_events=True)]

    assert len(_events_named(events, TeamRunEvent.model_request_started.value)) == len(turns)
    _assert_turns_stay_apart(events, first, second)


def _cached_model(turns: List[List[ModelResponse]], cache_dir) -> _ScriptedStreamModel:
    """A scripted model that records its stream and replays it on the next run."""
    model = _ScriptedStreamModel(turns)
    model.cache_response = True
    model.cache_dir = str(cache_dir)
    return model


def test_team_does_not_carry_tool_call_ids_across_the_turns_of_a_cached_response(tmp_path):
    """A cache hit replays the calls a run made and makes no request of its own.

    The event that says a model request has started is the one thing a cached
    response never emits, so a turn boundary keyed on it would let the second
    turn's opening fragment, which carries index zero and no id, land on the
    call the first turn already finished.
    """
    turns, first, second = _two_turn_calls()
    recording = Team(members=[], model=_cached_model(turns, tmp_path), tools=[save_note, save_other])

    live = list(recording.run("go", stream=True, stream_events=True))
    # An empty script: a cache hit asks the model for nothing, so a miss fails
    # the run rather than quietly streaming the turns a second time.
    replaying = Team(members=[], model=_cached_model([], tmp_path), tools=[save_note, save_other])
    cached = list(replaying.run("go", stream=True, stream_events=True))

    assert not _events_named(cached, TeamRunEvent.model_request_started.value)
    _assert_turns_stay_apart(cached, first, second)
    assert _assembled(cached, "call_a") == _assembled(live, "call_a")


def _assert_a_restarted_stream_offers_its_fragments_again(
    events, model, turns, arguments: str, warnings: List[logging.LogRecord]
) -> None:
    """Every fragment the restarted stream produced went out, retraced or not.

    A subscriber can only append what it is sent, so holding a fragment back
    on the guess that it already has it is what dropped real argument text.
    """
    # The stream really did drop and restart, and it restarted inside the turn
    # rather than costing the run a model request.
    assert model.attempts > 1
    assert len(_events_named(events, TeamRunEvent.model_request_started.value)) == len(turns)
    retraced = "".join(_chunks(arguments, CHUNK_SIZE)[:3])
    assert _assembled(events, "call_team") == retraced + arguments
    # The run's own reassembly is doubled the same way, so the call fails to
    # decode and is never started. It is closed out all the same.
    assert not _events_named(events, TeamRunEvent.tool_call_started.value)
    reported = _events_named(events, TeamRunEvent.tool_call_error.value)
    assert [event.tool.tool_call_id for event in reported] == ["call_team"]
    assert reported[0].error == REFUSED_TOOL_CALL_ERROR
    # The run reports the request that dropped and the doubled arguments its
    # own reassembly then could not decode, and nothing else: the fragments
    # went out as they arrived, so there is nothing to say of them.
    logged = [record.getMessage() for record in warnings]
    assert len(logged) == 2, logged
    assert any("Model provider error" in message for message in logged)
    assert any("Unable to decode function arguments" in message for message in logged)


def _restarting_team(turns) -> Tuple[Team, "_DroppedStreamModel"]:
    # Four deltas in: the call's announcement and three argument fragments.
    model = _DroppedStreamModel(turns, fail_after=4)
    model.retries = 1
    model.delay_between_retries = 0
    return Team(members=[], model=model, tools=[save_note]), model


def test_team_streams_a_restarted_streams_fragments_again(warnings_logged):
    turns, arguments = _tool_call_turns("call_team")
    team, model = _restarting_team(turns)

    events = list(team.run("go", stream=True, stream_events=True))

    _assert_a_restarted_stream_offers_its_fragments_again(events, model, turns, arguments, warnings_logged)


async def test_team_streams_a_restarted_streams_fragments_again_async(warnings_logged):
    turns, arguments = _tool_call_turns("call_team")
    team, model = _restarting_team(turns)

    events = [event async for event in team.arun("go", stream=True, stream_events=True)]

    _assert_a_restarted_stream_offers_its_fragments_again(events, model, turns, arguments, warnings_logged)


# ---------------------------------------------------------------------------
# When a fragment is safe to send
# ---------------------------------------------------------------------------


def _text_and_fragment_turns() -> Tuple[List[List[ModelResponse]], str, str]:
    """A turn whose opening delta carries both a line of text and a tool call.

    A provider sends both in one chunk when the model says what it is about to
    do, and the saying comes before the call it announces.
    """
    text = "Saving that now. "
    arguments = json.dumps({"note": "the sea is wide"})
    opening = _fragment(0, arguments[:4], tool_call_id="call_team", tool_name="save_note")
    opening.content = text
    fragments = [opening]
    fragments += [_fragment(0, chunk) for chunk in _chunks(arguments[4:], CHUNK_SIZE)]
    return [fragments, [ModelResponse(role="assistant", content="the note is saved")]], text, arguments


def _assert_text_comes_first(events, text: str, arguments: str) -> None:
    first_fragment = next(
        position for position, event in enumerate(events) if event.event == TeamRunEvent.tool_call_args_delta.value
    )
    said = next(
        position
        for position, event in enumerate(events)
        if event.event == TeamRunEvent.run_content.value and event.content == text
    )
    assert said < first_fragment
    # The whole argument string still reaches the client, opening chunk included.
    assert _assembled(events, "call_team") == arguments


def test_team_sends_a_chunks_text_before_the_tool_call_it_announces():
    turns, text, arguments = _text_and_fragment_turns()
    team = Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_note])

    events = list(team.run("go", stream=True, stream_events=True))

    _assert_text_comes_first(events, text, arguments)


async def test_team_sends_a_chunks_text_before_the_tool_call_it_announces_async():
    turns, text, arguments = _text_and_fragment_turns()
    team = Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_note])

    events = [event async for event in team.arun("go", stream=True, stream_events=True)]

    _assert_text_comes_first(events, text, arguments)


def _refused_call_turns() -> Tuple[List[List[ModelResponse]], str]:
    """A turn asking for two tools, of which a limit of one lets only the first run."""
    first = json.dumps({"note": "first"})
    second = json.dumps({"note": "second"})
    fragments = [
        _fragment(0, tool_call_id="call_a", tool_name="save_note"),
        _fragment(1, tool_call_id="call_b", tool_name="save_other"),
    ]
    fragments += [_fragment(0, chunk) for chunk in _chunks(first, CHUNK_SIZE)]
    fragments += [_fragment(1, chunk) for chunk in _chunks(second, CHUNK_SIZE)]
    return [fragments, [ModelResponse(role="assistant", content="one of them is saved")]], second


def _refused_team(turns) -> Team:
    return Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_note, save_other], tool_call_limit=1)


def _assert_refusal_is_closed_out(events, second: str) -> None:
    # The client was shown the second call while it was still being written.
    assert _assembled(events, "call_b") == second
    # The limit let only the first of the two run.
    started = {event.tool.tool_call_id for event in _events_named(events, TeamRunEvent.tool_call_started.value)}
    assert started == {"call_a"}
    # So the call the client is holding is closed out rather than left open.
    errors = _events_named(events, TeamRunEvent.tool_call_error.value)
    assert [event.tool.tool_call_id for event in errors] == ["call_b"]
    assert errors[0].tool.tool_name == "save_other"
    assert errors[0].error == REFUSED_TOOL_CALL_ERROR
    assert errors[0].tool.tool_call_error


def test_team_closes_out_a_tool_call_the_run_refuses():
    turns, second = _refused_call_turns()

    events = list(_refused_team(turns).run("go", stream=True, stream_events=True))

    _assert_refusal_is_closed_out(events, second)


async def test_team_closes_out_a_tool_call_the_run_refuses_async():
    turns, second = _refused_call_turns()

    events = [event async for event in _refused_team(turns).arun("go", stream=True, stream_events=True)]

    _assert_refusal_is_closed_out(events, second)


def test_team_closes_out_a_call_naming_a_tool_it_does_not_have(errors_logged):
    arguments = json.dumps({"note": "nowhere to put this"})
    fragments = [_fragment(0, tool_call_id="call_ghost", tool_name="save_nowhere")]
    fragments += [_fragment(0, chunk) for chunk in _chunks(arguments, CHUNK_SIZE)]
    turns = [fragments, [ModelResponse(role="assistant", content="there is no such tool")]]
    team = Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_note])

    events = list(team.run("go", stream=True, stream_events=True))

    assert _assembled(events, "call_ghost") == arguments
    assert not _events_named(events, TeamRunEvent.tool_call_started.value)
    errors = _events_named(events, TeamRunEvent.tool_call_error.value)
    assert [event.tool.tool_call_id for event in errors] == ["call_ghost"]
    # The run says which tool it could not find, once.
    assert [record.getMessage() for record in errors_logged] == ["Function save_nowhere not found"]


class _RaisingStreamModel(_ScriptedStreamModel):
    """Streams part of a turn and then dies for good, without a retry."""

    def __init__(self, turns: List[List[ModelResponse]], fail_after: int):
        super().__init__(turns)
        self._fail_after = fail_after
        self.retries = 0

    def _up_to_the_failure(self) -> List[ModelResponse]:
        return self._next_turn()[: self._fail_after]

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield from self._up_to_the_failure()
        raise ModelProviderError(message="stream died", model_name=self.name, model_id=self.id)

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        for delta in self._up_to_the_failure():
            yield delta
        raise ModelProviderError(message="stream died", model_name=self.name, model_id=self.id)


def _assert_a_raising_stream_closes_the_call_it_left_open(events) -> None:
    """A stream that raised is still being read, so the closure can still go out.

    The call the client was shown will never be started or completed, and the
    turn it belonged to never reaches its end, so closing it out only after the
    loop would leave the client waiting on it for good.
    """
    assert _events_named(events, TeamRunEvent.tool_call_args_delta.value), "nothing streamed, so nothing to close"
    assert not _events_named(events, TeamRunEvent.tool_call_started.value)
    reported = _events_named(events, TeamRunEvent.tool_call_error.value)
    assert [event.tool.tool_call_id for event in reported] == ["call_team"]
    assert reported[0].error == REFUSED_TOOL_CALL_ERROR
    # The error itself still reaches the caller, after the closure.
    assert [event.event for event in events[-2:]] == [
        TeamRunEvent.tool_call_error.value,
        TeamRunEvent.run_error.value,
    ]


def test_team_closes_out_a_call_a_raising_stream_left_open():
    turns, _ = _tool_call_turns("call_team")
    # Three deltas in: the call's announcement and two argument fragments.
    team = Team(members=[], model=_RaisingStreamModel(turns, fail_after=3), tools=[save_note])

    events = list(team.run("go", stream=True, stream_events=True))

    _assert_a_raising_stream_closes_the_call_it_left_open(events)


async def test_team_closes_out_a_call_a_raising_stream_left_open_async():
    turns, _ = _tool_call_turns("call_team")
    team = Team(members=[], model=_RaisingStreamModel(turns, fail_after=3), tools=[save_note])

    events = [event async for event in team.arun("go", stream=True, stream_events=True)]

    _assert_a_raising_stream_closes_the_call_it_left_open(events)


@tool(requires_confirmation=True)
def save_on_confirmation(note: str) -> str:
    """Save a note, once the caller has agreed to it.

    Args:
        note: the note to save
    """
    return "saved"


def _team_awaiting_confirmation() -> Tuple[Team, str]:
    turns, arguments = _tool_call_turns("call_team", tool_name="save_on_confirmation")
    return Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_on_confirmation]), arguments


def _assert_a_paused_call_is_not_reported_as_never_run(events, arguments: str) -> None:
    """A call waiting on the caller is neither refused nor finished.

    Its arguments streamed before the run could know it would pause, and the
    run holds it open on purpose: the caller has still to say yes. Reporting it
    as a call that was not run would be a lie about a call that may yet be.
    """
    assert _assembled(events, "call_team") == arguments
    assert _events_named(events, TeamRunEvent.run_paused.value)
    assert not _events_named(events, TeamRunEvent.tool_call_error.value)


def test_team_does_not_report_a_call_awaiting_confirmation_as_never_run():
    team, arguments = _team_awaiting_confirmation()

    *events, paused = list(team.run("go", stream=True, stream_events=True, yield_run_output=True))

    _assert_a_paused_call_is_not_reported_as_never_run(events, arguments)
    assert paused.is_paused
    assert [(tool.tool_call_id, tool.requires_confirmation) for tool in paused.tools] == [("call_team", True)]


async def test_team_does_not_report_a_call_awaiting_confirmation_as_never_run_async():
    team, arguments = _team_awaiting_confirmation()

    *events, paused = [event async for event in team.arun("go", stream=True, stream_events=True, yield_run_output=True)]

    _assert_a_paused_call_is_not_reported_as_never_run(events, arguments)
    assert paused.is_paused
    assert [(tool.tool_call_id, tool.requires_confirmation) for tool in paused.tools] == [("call_team", True)]


def _tool_calls_the_run_kept(run_output) -> List[Tuple[Optional[str], bool]]:
    return [(tool.tool_call_id, bool(tool.tool_call_error)) for tool in run_output.tools]


def _assert_the_runs_tool_list_holds_only_the_call_it_made(run_output) -> None:
    """A refused call is told to the client and left out of the run's own list.

    That list is the framework's account of the calls the run made, and a call
    it declined to make is not one of them. Telling the client is the stream's
    job and stops there.
    """
    assert run_output.events is None
    assert _tool_calls_the_run_kept(run_output) == [("call_a", False)]


def test_team_leaves_a_refused_tool_call_out_of_the_runs_tool_list():
    turns, _ = _refused_call_turns()
    team = _refused_team(turns)
    assert not team.store_events

    streamed = list(team.run("go", stream=True, stream_events=True, yield_run_output=True))

    _assert_the_runs_tool_list_holds_only_the_call_it_made(streamed[-1])


async def test_team_leaves_a_refused_tool_call_out_of_the_runs_tool_list_async():
    turns, _ = _refused_call_turns()
    team = _refused_team(turns)

    streamed = [event async for event in team.arun("go", stream=True, stream_events=True, yield_run_output=True)]

    _assert_the_runs_tool_list_holds_only_the_call_it_made(streamed[-1])


def test_team_keeps_the_same_tool_calls_whether_or_not_its_events_stream():
    """The same model behaviour ends on the same tool list either way.

    Whether a caller subscribed to the events is no part of what the run did,
    so it can be no part of what the run reports having done.
    """
    subscribed = list(
        _refused_team(_refused_call_turns()[0]).run("go", stream=True, stream_events=True, yield_run_output=True)
    )
    unsubscribed = list(
        _refused_team(_refused_call_turns()[0]).run("go", stream=True, stream_events=False, yield_run_output=True)
    )

    assert _tool_calls_the_run_kept(subscribed[-1]) == _tool_calls_the_run_kept(unsubscribed[-1])
    assert _tool_calls_the_run_kept(unsubscribed[-1]) == [("call_a", False)]


# ---------------------------------------------------------------------------
# A run cancelled while a call's arguments are streaming
# ---------------------------------------------------------------------------


@contextmanager
def _asyncio_errors_reported() -> Iterator[List[logging.LogRecord]]:
    """What the event loop reports when it closes what a cancelled run left it.

    A stream nobody is reading any more is closed by the loop that ran it,
    when that loop is closed, and an error raised by that closing is reported
    to the asyncio logger rather than to the caller.
    """
    records: List[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collector(logging.ERROR)
    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.addHandler(handler)
    try:
        yield records
    finally:
        asyncio_logger.removeHandler(handler)


def _arguments_are_part_written(events) -> bool:
    """True once some of a call's arguments have gone out and the rest have not."""
    return len(_events_named(events, TeamRunEvent.tool_call_args_delta.value)) == 2


def _assert_the_cancelled_run_ends_and_nothing_waits_on_it(events) -> None:
    """The run ends on its terminal events with the call it streamed undecided.

    A cancellation is raised where the run's events are consumed, so the
    stream that was writing the arguments is closed rather than read to the
    end. Nothing can be added to a stream nobody is reading, and the call a
    client is holding is closed out by the terminal events the run does end
    on.
    """
    assert _events_named(events, TeamRunEvent.tool_call_args_delta.value), "nothing streamed, so nothing to cancel"
    assert not _events_named(events, TeamRunEvent.tool_call_started.value)
    assert [event.event for event in events[-2:]] == [
        TeamRunEvent.run_cancelled.value,
        TeamRunEvent.run_completed.value,
    ]


def test_team_cancelled_while_a_calls_arguments_stream_ends_the_run():
    turns, _ = _tool_call_turns("call_team")
    team = Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_note])

    events: List[Any] = []
    for event in team.run("go", stream=True, stream_events=True):
        events.append(event)
        if _arguments_are_part_written(events):
            Team.cancel_run(event.run_id)

    _assert_the_cancelled_run_ends_and_nothing_waits_on_it(events)


def test_team_cancelled_while_a_calls_arguments_stream_closes_its_stream_cleanly():
    """The stream the cancelled run abandoned is closed without complaint.

    A cancellation is raised where the events are consumed, so the stream
    writing the arguments is closed rather than read to the end. An async
    generator that yields while it is being closed makes that closing raise,
    and the loop reports it where nothing asserting on the run would see it.
    """
    turns, _ = _tool_call_turns("call_team")
    team = Team(members=[], model=_ScriptedStreamModel(turns), tools=[save_note])

    async def consume() -> List[Any]:
        events: List[Any] = []
        async for event in team.arun("go", stream=True, stream_events=True):
            events.append(event)
            if _arguments_are_part_written(events):
                await Team.acancel_run(event.run_id)
        return events

    with _asyncio_errors_reported() as reported:
        # A loop of this test's own, because a stream a cancelled run
        # abandoned is closed when the loop that ran it is closed.
        events = asyncio.run(consume())

    _assert_the_cancelled_run_ends_and_nothing_waits_on_it(events)
    assert [record.getMessage() for record in reported] == []
