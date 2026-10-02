"""What an Agent does with a tool call's streamed argument fragments.

A fragmenting provider emits one fragment event per handful of argument
characters, so a single tool call can produce hundreds of them. A subscriber
rendering a call while the model is still writing it needs every fragment,
attributed to the call it belongs to and offered exactly once. The stored run
needs none of them, which is why the default skip list keeps them out of
storage without keeping them off the stream.

A fragment is attributed exactly the way Agno's own tool call aggregators
attribute it: one entry per provider stream index, a missing index read as
zero, and an entry's id taken from whichever of its deltas last carried one.
So where a provider is ambiguous the run and a subscriber read it the same way
and cannot disagree, which is all a subscriber needs. Those indexes restart at
zero every turn, and the turn ends when the run takes a call up, so a later
turn's fragment that carries no id of its own must not land on an earlier
turn's finished call. Nothing else is held back or rewritten. A fragment
offered twice, by a provider stream that restarts, goes out twice, because a
subscriber can only append what it is sent and the run's own reassembly is
doubled in the same way.
"""

import asyncio
import json
import logging
from contextlib import contextmanager
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

import pytest
from pydantic import BaseModel

from agno.agent import Agent
from agno.agent._response import handle_model_response_chunk
from agno.db.sqlite import SqliteDb
from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.agent import RunEvent, RunOutput
from agno.session import AgentSession
from agno.tools import tool
from agno.utils import log as agno_log
from agno.utils.tools import REFUSED_TOOL_CALL_ERROR, ToolCallArgsStream


class _ScriptedStreamModel(Model):
    """Replays a fixed script of provider deltas, one turn per model call.

    A call's id and function name ride its first fragment, which often carries
    no arguments; every later fragment carries only an argument chunk and the
    index that ties it back to the call. Each entry in ``turns`` is the list of
    deltas for one model turn.

    The script is finite: a call past its end fails the test rather than
    replaying a turn, so a run that loops longer than intended is visible.
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

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield from self._next_turn()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        for delta in self._next_turn():
            yield delta

    def invoke(self, *args, **kwargs) -> ModelResponse:
        raise AssertionError("the streaming paths are the ones under test")

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        raise AssertionError("the streaming paths are the ones under test")

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


class _AggregatingStreamModel(_ScriptedStreamModel):
    """Also answers the non-streaming paths, with the turn as one response."""

    def _aggregate_turn(self) -> ModelResponse:
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


class _NonStreamedCallModel(_AggregatingStreamModel):
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


class _ToolRecordingModel(_AggregatingStreamModel):
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


def _unidentified_fragment(arguments: str = "", tool_name: Optional[str] = None) -> ModelResponse:
    """One fragment from a provider that puts neither an index nor an id on it.

    Ollama hands tool calls over this way, and Agno gives a call with no id of
    its own one only once the finished call is assembled, so while such a
    provider's fragments are arriving there is nothing to send them under.
    """
    return _unnumbered_fragment(arguments, tool_name=tool_name)


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
    return "saved other"


class _Note(BaseModel):
    note: str


CHUNK_SIZE = 5


def _tool_call_turns() -> Tuple[List[List[ModelResponse]], str]:
    """One turn streaming a single tool call in fragments, then a reply turn."""
    arguments = json.dumps({"note": "the sea is wide and the boat is small"})
    fragments = [_fragment(0, tool_call_id="call_a", tool_name="save_note")]
    fragments += [_fragment(0, chunk) for chunk in _chunks(arguments, CHUNK_SIZE)]
    return [fragments, [ModelResponse(role="assistant", content="the note is saved")]], arguments


def _interleaved_call_turns() -> Tuple[List[List[ModelResponse]], str, str]:
    """One turn that streams two calls at once, their fragments interleaved.

    The two argument strings differ in length, so the shorter call runs out of
    fragments while the longer one is still streaming.
    """
    first = json.dumps({"note": "first"})
    second = json.dumps({"note": "second, and a good deal longer than the first"})
    fragments = [
        _fragment(0, tool_call_id="call_a", tool_name="save_note"),
        _fragment(1, tool_call_id="call_b", tool_name="save_other"),
    ]
    first_chunks = _chunks(first, CHUNK_SIZE)
    second_chunks = _chunks(second, CHUNK_SIZE)
    for position in range(max(len(first_chunks), len(second_chunks))):
        if position < len(first_chunks):
            fragments.append(_fragment(0, first_chunks[position]))
        if position < len(second_chunks):
            fragments.append(_fragment(1, second_chunks[position]))
    return [fragments, [ModelResponse(role="assistant", content="both are saved")]], first, second


def _two_turn_calls() -> Tuple[List[List[ModelResponse]], str, str]:
    """Two tool call turns, the second opening with a fragment that has no id.

    A provider ties later fragments back to a call by an index that restarts at
    zero on every turn, so the second turn's opening fragment carries index
    zero and no id of its own. It belongs to the call the second turn goes on
    to announce, never to the first turn's finished call.
    """
    first = json.dumps({"note": "first"})
    second = json.dumps({"note": "second"})
    first_fragments = [_fragment(0, tool_call_id="call_a", tool_name="save_note")]
    first_fragments += [_fragment(0, chunk) for chunk in _chunks(first, CHUNK_SIZE)]
    second_fragments = [
        _fragment(0, second[:4]),
        _fragment(0, second[4:], tool_call_id="call_b", tool_name="save_other"),
    ]
    reply = [ModelResponse(role="assistant", content="both are saved")]
    return [first_fragments, second_fragments, reply], first, second


def _quiet_model() -> _ScriptedStreamModel:
    """A model whose single turn is plain content, so it streams no fragments."""
    return _ScriptedStreamModel([[ModelResponse(role="assistant", content="draft")]])


def _events_named(events, event_name: str):
    return [event for event in events if event.event == event_name]


def _assembled(events, tool_call_id: str) -> str:
    deltas = _events_named(events, RunEvent.tool_call_args_delta.value)
    return "".join(delta.tool_args_delta for delta in deltas if delta.tool_call_id == tool_call_id)


def _stored(run_output) -> List[str]:
    return [event.event for event in (run_output.events or [])]


# ---------------------------------------------------------------------------
# Streaming a call's arguments
# ---------------------------------------------------------------------------


def test_agent_streams_tool_call_arg_fragments():
    turns, arguments = _tool_call_turns()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    events = list(agent.run("go", stream=True, stream_events=True))

    deltas = _events_named(events, RunEvent.tool_call_args_delta.value)
    assert len(deltas) == len(_chunks(arguments, CHUNK_SIZE))
    assert "".join(delta.tool_args_delta for delta in deltas) == arguments
    assert {delta.tool_call_id for delta in deltas} == {"call_a"}
    assert {delta.tool_name for delta in deltas} == {"save_note"}

    # The finished events still arrive unchanged, and agree with the fragments.
    started = _events_named(events, RunEvent.tool_call_started.value)
    completed = _events_named(events, RunEvent.tool_call_completed.value)
    assert len(started) == 1
    assert len(completed) == 1
    assert started[0].tool.tool_args == json.loads(arguments)
    assert started[0].tool.tool_call_id == "call_a"


async def test_agent_streams_tool_call_arg_fragments_async():
    turns, arguments = _tool_call_turns()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    deltas = _events_named(events, RunEvent.tool_call_args_delta.value)
    assert "".join(delta.tool_args_delta for delta in deltas) == arguments
    assert {delta.tool_call_id for delta in deltas} == {"call_a"}
    assert _events_named(events, RunEvent.tool_call_started.value)[0].tool.tool_args == json.loads(arguments)


def test_agent_resolves_tool_call_id_from_index_on_later_fragments():
    """Only the first fragment carries the id, and it carries no arguments at
    all; every emitted fragment must still name the call it belongs to."""
    turns, _ = _tool_call_turns()
    later_fragments = turns[0][1:]
    assert all(call.get("id") is None for delta in later_fragments for call in delta.tool_calls)

    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    events = list(agent.run("go", stream=True, stream_events=True))

    deltas = _events_named(events, RunEvent.tool_call_args_delta.value)
    assert deltas
    assert all(delta.tool_call_id == "call_a" for delta in deltas)
    assert all(delta.tool_name == "save_note" for delta in deltas)


def test_agent_keeps_interleaved_tool_calls_apart():
    turns, first, second = _interleaved_call_turns()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note, save_other])

    events = list(agent.run("go", stream=True, stream_events=True))

    assembled: Dict[str, str] = {}
    names: Dict[str, Optional[str]] = {}
    for delta in _events_named(events, RunEvent.tool_call_args_delta.value):
        assembled[delta.tool_call_id] = assembled.get(delta.tool_call_id, "") + delta.tool_args_delta
        names[delta.tool_call_id] = delta.tool_name
    assert assembled == {"call_a": first, "call_b": second}
    assert names == {"call_a": "save_note", "call_b": "save_other"}


def _unnumbered_call_turns() -> Tuple[List[List[ModelResponse]], str]:
    """One call from a provider that numbers none of its deltas.

    The opening delta carries the id and the name, and every later one carries
    only argument text. Agno's own aggregators, the OpenAI chat, watsonx,
    cerebras and litellm ones among them, read a missing index as zero, so all
    of these deltas belong to the one call the turn made.
    """
    arguments = json.dumps({"note": "the sea is wide and the boat is small"})
    fragments = [_unnumbered_fragment(tool_call_id="call_a", tool_name="save_note")]
    fragments += [_unnumbered_fragment(chunk) for chunk in _chunks(arguments, CHUNK_SIZE)]
    return [fragments, [ModelResponse(role="assistant", content="the note is saved")]], arguments


def _assert_the_unnumbered_calls_arguments_streamed_whole(events, arguments: str) -> None:
    """The client was sent what the run itself assembled, not a prefix of it."""
    started = _events_named(events, RunEvent.tool_call_started.value)
    assert [json.dumps(event.tool.tool_args) for event in started] == [arguments]
    assert _assembled(events, "call_a") == arguments


def test_agent_streams_the_whole_arguments_of_a_provider_that_numbers_no_call():
    turns, arguments = _unnumbered_call_turns()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    events = list(agent.run("go", stream=True, stream_events=True))

    _assert_the_unnumbered_calls_arguments_streamed_whole(events, arguments)


async def test_agent_streams_the_whole_arguments_of_a_provider_that_numbers_no_call_async():
    turns, arguments = _unnumbered_call_turns()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    _assert_the_unnumbered_calls_arguments_streamed_whole(events, arguments)


# ---------------------------------------------------------------------------
# Turn and stream boundaries
# ---------------------------------------------------------------------------


def test_agent_does_not_carry_tool_call_ids_across_turns():
    turns, first, _ = _two_turn_calls()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note, save_other])

    events = list(agent.run("go", stream=True, stream_events=True))

    # One model request per scripted turn, so nothing here rides on the fake
    # having a turn left to hand out twice.
    assert len(_events_named(events, RunEvent.model_request_started.value)) == len(turns)
    assert json.loads(_assembled(events, "call_a")) == json.loads(first)


async def test_agent_does_not_carry_tool_call_ids_across_turns_async():
    turns, first, _ = _two_turn_calls()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note, save_other])

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    assert len(_events_named(events, RunEvent.model_request_started.value)) == len(turns)
    assert json.loads(_assembled(events, "call_a")) == json.loads(first)


def _cached_model(turns: List[List[ModelResponse]], cache_dir) -> _ScriptedStreamModel:
    """A scripted model that records its stream and replays it on the next run."""
    model = _ScriptedStreamModel(turns)
    model.cache_response = True
    model.cache_dir = str(cache_dir)
    return model


def _assert_a_cached_response_keeps_its_turns_apart(live, cached, first: str) -> None:
    """The replayed turns are held apart by what the run did, not by a request.

    A cache hit yields the deltas the recorded run produced and asks the model
    for nothing, so the event that says a model request has started never
    arrives. A turn boundary keyed on that event would let the second turn's
    opening fragment, which carries index zero and no id, land on the call the
    first turn already finished.
    """
    assert not _events_named(cached, RunEvent.model_request_started.value)
    assert _events_named(cached, RunEvent.tool_call_args_delta.value)
    assert json.loads(_assembled(cached, "call_a")) == json.loads(first)
    assert _assembled(cached, "call_a") == _assembled(live, "call_a")


def test_agent_does_not_carry_tool_call_ids_across_the_turns_of_a_cached_response(tmp_path):
    turns, first, _ = _two_turn_calls()
    recording = Agent(model=_cached_model(turns, tmp_path), tools=[save_note, save_other])

    live = list(recording.run("go", stream=True, stream_events=True))
    # An empty script: a cache hit asks the model for nothing, so a miss fails
    # the run rather than quietly streaming the turns a second time.
    replaying = Agent(model=_cached_model([], tmp_path), tools=[save_note, save_other])
    cached = list(replaying.run("go", stream=True, stream_events=True))

    _assert_a_cached_response_keeps_its_turns_apart(live, cached, first)


async def test_agent_does_not_carry_tool_call_ids_across_the_turns_of_a_cached_response_async(tmp_path):
    turns, first, _ = _two_turn_calls()
    recording = Agent(model=_cached_model(turns, tmp_path), tools=[save_note, save_other])

    live = [event async for event in recording.arun("go", stream=True, stream_events=True)]
    replaying = Agent(model=_cached_model([], tmp_path), tools=[save_note, save_other])
    cached = [event async for event in replaying.arun("go", stream=True, stream_events=True)]

    _assert_a_cached_response_keeps_its_turns_apart(live, cached, first)


def _assert_a_restarted_stream_offers_its_fragments_again(
    events, model, turns, arguments: str, warnings: List[logging.LogRecord]
) -> None:
    """Every fragment the restarted stream produced went out, retraced or not.

    A subscriber can only append what it is sent, so text held back can never
    be made up for and text sent can never be taken back. Holding a fragment
    back on the guess that a client already has it is what dropped real
    argument text, so the fragments are passed on as the provider wrote them
    and the assembled string is checked where it can be: against the finished
    call, by the subscriber that has to render it.
    """
    # The stream really did drop and restart, and it restarted inside the turn
    # rather than costing the run a model request.
    assert model.attempts > 1
    assert len(_events_named(events, RunEvent.model_request_started.value)) == len(turns)
    retraced = "".join(_chunks(arguments, CHUNK_SIZE)[:3])
    assert _assembled(events, "call_a") == retraced + arguments
    # A restart leaves the run's own reassembly of the arguments doubled too,
    # so the call fails to decode and is never started. It is closed out all
    # the same, rather than left open on a client for good.
    assert not _events_named(events, RunEvent.tool_call_started.value)
    reported = _events_named(events, RunEvent.tool_call_error.value)
    assert [event.tool.tool_call_id for event in reported] == ["call_a"]
    assert reported[0].error == REFUSED_TOOL_CALL_ERROR
    # The run reports the request that dropped and the doubled arguments its
    # own reassembly then could not decode, and nothing else: the fragments
    # went out as they arrived, so there is nothing to say of them.
    logged = [record.getMessage() for record in warnings]
    assert len(logged) == 2, logged
    assert any("Model provider error" in message for message in logged)
    assert any("Unable to decode function arguments" in message for message in logged)


def _restarting_agent(turns) -> Tuple[Agent, _DroppedStreamModel]:
    # Four deltas in: the call's announcement and three argument fragments.
    model = _DroppedStreamModel(turns, fail_after=4)
    model.retries = 1
    model.delay_between_retries = 0
    return Agent(model=model, tools=[save_note]), model


def test_agent_streams_a_restarted_streams_fragments_again(warnings_logged):
    turns, arguments = _tool_call_turns()
    agent, model = _restarting_agent(turns)

    events = list(agent.run("go", stream=True, stream_events=True))

    _assert_a_restarted_stream_offers_its_fragments_again(events, model, turns, arguments, warnings_logged)


async def test_agent_streams_a_restarted_streams_fragments_again_async(warnings_logged):
    turns, arguments = _tool_call_turns()
    agent, model = _restarting_agent(turns)

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

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
    opening = _fragment(0, arguments[:4], tool_call_id="call_a", tool_name="save_note")
    opening.content = text
    fragments = [opening]
    fragments += [_fragment(0, chunk) for chunk in _chunks(arguments[4:], CHUNK_SIZE)]
    return [fragments, [ModelResponse(role="assistant", content="the note is saved")]], text, arguments


def test_agent_sends_a_chunks_text_before_the_tool_call_it_announces():
    turns, text, arguments = _text_and_fragment_turns()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    events = list(agent.run("go", stream=True, stream_events=True))

    first_fragment = next(
        position for position, event in enumerate(events) if event.event == RunEvent.tool_call_args_delta.value
    )
    said = next(
        position
        for position, event in enumerate(events)
        if event.event == RunEvent.run_content.value and event.content == text
    )
    assert said < first_fragment
    # The whole argument string still reaches the client, opening chunk included.
    assert _assembled(events, "call_a") == arguments


async def test_agent_sends_a_chunks_text_before_the_tool_call_it_announces_async():
    turns, text, arguments = _text_and_fragment_turns()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    first_fragment = next(
        position for position, event in enumerate(events) if event.event == RunEvent.tool_call_args_delta.value
    )
    said = next(
        position
        for position, event in enumerate(events)
        if event.event == RunEvent.run_content.value and event.content == text
    )
    assert said < first_fragment
    assert _assembled(events, "call_a") == arguments


@contextmanager
def _records_logged_at(level: int) -> Iterator[List[logging.LogRecord]]:
    """Everything Agno logs at ``level`` or above, whichever logger carried it.

    ``log_warning`` and ``log_error`` write to a process-global logger that a
    team run rebinds to the team logger and never rebinds back, so the same
    line is carried by one logger or another depending on what else ran
    earlier in the process. What these tests assert is what a run reported, so
    they read every logger the helpers can be bound to and stay out of that.
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
def warnings_logged() -> Iterator[List[logging.LogRecord]]:
    with _records_logged_at(logging.WARNING) as records:
        yield records


@pytest.fixture
def errors_logged() -> Iterator[List[logging.LogRecord]]:
    with _records_logged_at(logging.ERROR) as records:
        yield records


def _unnamed_call_turns() -> Tuple[List[List[ModelResponse]], str]:
    """A turn whose fragments name no call at all, then a reply turn."""
    arguments = json.dumps({"note": "the sea is wide and the boat is small"})
    fragments = [_unidentified_fragment(tool_name="save_note")]
    fragments += [_unidentified_fragment(chunk) for chunk in _chunks(arguments, CHUNK_SIZE)]
    return [fragments, [ModelResponse(role="assistant", content="the note is saved")]], arguments


def _agent_on_a_provider_that_names_no_call() -> Tuple[Agent, str]:
    turns, arguments = _unnamed_call_turns()
    return Agent(model=_ScriptedStreamModel(turns), tools=[save_note]), arguments


def _assert_the_arguments_arrive_whole_with_the_finished_call(events, arguments: str) -> None:
    """No fragment reached a subscriber, and the finished call carried it all.

    Which is what a subscriber was handed before any of this streamed: one
    complete set of arguments, once, with the call Agno announces.
    """
    assert [event for event in events if event.event == RunEvent.tool_call_args_delta.value] == []
    announcements = [event for event in events if event.event == RunEvent.tool_call_started.value]
    assert [json.dumps(event.tool.tool_args) for event in announcements] == [arguments]
    assert announcements[0].tool.tool_call_id


class TestAProviderThatNamesNoCallSendsItsArgumentsWithTheFinishedCall:
    """A provider whose fragments carry neither a stream index nor a call id.

    Nothing but a guess could tie such a fragment to a call, so none of them
    go out. What a subscriber gets is the behaviour it had before arguments
    streamed at all, and a warning naming the run it happened in, once for the
    stream rather than once for each of the fragments.
    """

    def test_the_arguments_arrive_whole_with_the_finished_call(self, warnings_logged):
        agent, arguments = _agent_on_a_provider_that_names_no_call()

        events = list(agent.run("go", stream=True, stream_events=True))

        _assert_the_arguments_arrive_whole_with_the_finished_call(events, arguments)
        # One warning for the stream, though the provider split the arguments
        # over as many fragments as the chunk size allows.
        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        assert len(warnings) == 1, warnings
        assert "neither a tool call id nor a provider stream index" in warnings[0]
        # A server carries many conversations at once, so the warning has to
        # say which run left a subscriber without the streamed arguments.
        run_started = _events_named(events, RunEvent.run_started.value)[0]
        assert f"session_id={run_started.session_id}" in warnings[0]
        assert f"run_id={run_started.run_id}" in warnings[0]

    async def test_the_arguments_arrive_whole_with_the_finished_call_async(self, warnings_logged):
        agent, arguments = _agent_on_a_provider_that_names_no_call()

        events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

        _assert_the_arguments_arrive_whole_with_the_finished_call(events, arguments)
        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        assert len(warnings) == 1, warnings

    def test_the_tool_still_runs_on_the_arguments_the_model_asked_for(self, warnings_logged):
        agent, arguments = _agent_on_a_provider_that_names_no_call()

        events = list(agent.run("go", stream=True, stream_events=True))

        completions = [event for event in events if event.event == RunEvent.tool_call_completed.value]
        assert [json.dumps(event.tool.tool_args) for event in completions] == [arguments]
        assert [event.tool.result for event in completions] == ["saved"]
        # The call itself went through, so the one thing said of this run is
        # what a subscriber was short of, said once however many fragments
        # arrived. Anything else would be a report about a healthy call.
        reported = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        assert len(reported) == 1, reported
        assert "neither a tool call id nor a provider stream index" in reported[0]


class _StructuredArgumentsModel(_ScriptedStreamModel):
    """A provider that hands its arguments over as a mapping, not as text.

    Mistral's streamed deltas type them either way, and the adapters that meet
    a mapping turn it into JSON text on the way to the finished call, so the
    run makes the call the model asked for while no delta ever carried the
    text a subscriber could be sent a piece of.
    """

    def parse_tool_calls(self, tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        as_text: List[Dict[str, Any]] = []
        for fragment in tool_calls_data:
            function = dict(fragment.get("function") or {})
            if isinstance(function.get("arguments"), (dict, list)):
                function["arguments"] = json.dumps(function["arguments"])
            as_text.append({**fragment, "function": function})
        return super().parse_tool_calls(as_text)


def _agent_on_a_provider_that_writes_no_argument_text() -> Tuple[Agent, str]:
    note = {"note": "the sea is wide and the boat is small"}
    turns = [
        [
            _fragment(0, tool_call_id="call_a", tool_name="save_note"),
            ModelResponse(role="assistant", tool_calls=[{"index": 0, "function": {"arguments": note}}]),
        ],
        [ModelResponse(role="assistant", content="the note is saved")],
    ]
    return Agent(model=_StructuredArgumentsModel(turns), tools=[save_note]), json.dumps(note)


class TestAProviderThatWritesNoArgumentTextSendsItsArgumentsWithTheFinishedCall:
    """A provider whose deltas carry the arguments as a structure.

    There is no piece of the model's own text to pass on, and serialising the
    structure here would put a subscriber on text this library wrote rather
    than the model. So nothing goes out, the run is unaffected, and the reason
    is said once for the stream.
    """

    def test_the_arguments_arrive_whole_with_the_finished_call(self, warnings_logged):
        agent, arguments = _agent_on_a_provider_that_writes_no_argument_text()

        events = list(agent.run("go", stream=True, stream_events=True))

        _assert_the_arguments_arrive_whole_with_the_finished_call(events, arguments)
        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        assert len(warnings) == 1, warnings
        assert "as a structure rather than as the text" in warnings[0]
        # Named, so the call can be found, and said of what the client holds
        # rather than of a whole copy of the arguments it never receives.
        assert "call_a" in warnings[0] and "save_note" in warnings[0]
        assert "are therefore incomplete" in warnings[0]
        assert "Agno's own record of the call is unaffected" in warnings[0]
        run_started = _events_named(events, RunEvent.run_started.value)[0]
        assert f"session_id={run_started.session_id}" in warnings[0]
        assert f"run_id={run_started.run_id}" in warnings[0]

    async def test_the_arguments_arrive_whole_with_the_finished_call_async(self, warnings_logged):
        agent, arguments = _agent_on_a_provider_that_writes_no_argument_text()

        events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

        _assert_the_arguments_arrive_whole_with_the_finished_call(events, arguments)
        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        assert len(warnings) == 1, warnings

    def test_the_tool_still_runs_on_the_arguments_the_model_asked_for(self, warnings_logged):
        agent, arguments = _agent_on_a_provider_that_writes_no_argument_text()

        events = list(agent.run("go", stream=True, stream_events=True))

        completions = [event for event in events if event.event == RunEvent.tool_call_completed.value]
        assert [json.dumps(event.tool.tool_args) for event in completions] == [arguments]
        assert [event.tool.result for event in completions] == ["saved"]
        # The call itself went through, so the one thing said of this run is
        # what a subscriber was short of, said once for the stream. Anything
        # else would be a report about a healthy call.
        reported = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        assert len(reported) == 1, reported
        assert "as a structure rather than as the text" in reported[0]


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


def _refused_agent(turns) -> Agent:
    return Agent(model=_ScriptedStreamModel(turns), tools=[save_note, save_other], tool_call_limit=1)


def _assert_refusal_is_closed_out(events, second: str) -> None:
    # The client was shown the second call while it was still being written.
    assert _assembled(events, "call_b") == second
    # The limit let only the first of the two run.
    started = {event.tool.tool_call_id for event in _events_named(events, RunEvent.tool_call_started.value)}
    assert started == {"call_a"}
    # So the call the client is holding is closed out rather than left open.
    errors = _events_named(events, RunEvent.tool_call_error.value)
    assert [event.tool.tool_call_id for event in errors] == ["call_b"]
    assert errors[0].tool.tool_name == "save_other"
    assert errors[0].error == REFUSED_TOOL_CALL_ERROR
    assert errors[0].tool.tool_call_error


def test_agent_closes_out_a_tool_call_the_run_refuses():
    turns, second = _refused_call_turns()

    events = list(_refused_agent(turns).run("go", stream=True, stream_events=True))

    _assert_refusal_is_closed_out(events, second)


async def test_agent_closes_out_a_tool_call_the_run_refuses_async():
    turns, second = _refused_call_turns()

    events = [event async for event in _refused_agent(turns).arun("go", stream=True, stream_events=True)]

    _assert_refusal_is_closed_out(events, second)


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


def test_agent_leaves_a_refused_tool_call_out_of_the_runs_tool_list():
    turns, _ = _refused_call_turns()
    agent = _refused_agent(turns)
    assert not agent.store_events

    streamed = list(agent.run("go", stream=True, stream_events=True, yield_run_output=True))

    _assert_the_runs_tool_list_holds_only_the_call_it_made(streamed[-1])


async def test_agent_leaves_a_refused_tool_call_out_of_the_runs_tool_list_async():
    turns, _ = _refused_call_turns()
    agent = _refused_agent(turns)

    streamed = [event async for event in agent.arun("go", stream=True, stream_events=True, yield_run_output=True)]

    _assert_the_runs_tool_list_holds_only_the_call_it_made(streamed[-1])


def test_agent_keeps_the_same_tool_calls_whether_or_not_its_events_stream():
    """The same model behaviour ends on the same tool list either way.

    Whether a caller subscribed to the events is no part of what the run did,
    so it can be no part of what the run reports having done.
    """
    subscribed = list(
        _refused_agent(_refused_call_turns()[0]).run("go", stream=True, stream_events=True, yield_run_output=True)
    )
    unsubscribed = list(
        _refused_agent(_refused_call_turns()[0]).run("go", stream=True, stream_events=False, yield_run_output=True)
    )

    assert _tool_calls_the_run_kept(subscribed[-1]) == _tool_calls_the_run_kept(unsubscribed[-1])
    assert _tool_calls_the_run_kept(unsubscribed[-1]) == [("call_a", False)]


def test_agent_closes_out_a_call_naming_a_tool_it_does_not_have(errors_logged):
    arguments = json.dumps({"note": "nowhere to put this"})
    fragments = [_fragment(0, tool_call_id="call_ghost", tool_name="save_nowhere")]
    fragments += [_fragment(0, chunk) for chunk in _chunks(arguments, CHUNK_SIZE)]
    turns = [fragments, [ModelResponse(role="assistant", content="there is no such tool")]]
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    events = list(agent.run("go", stream=True, stream_events=True))

    assert _assembled(events, "call_ghost") == arguments
    assert not _events_named(events, RunEvent.tool_call_started.value)
    errors = _events_named(events, RunEvent.tool_call_error.value)
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
    assert _events_named(events, RunEvent.tool_call_args_delta.value), "nothing streamed, so nothing to close"
    assert not _events_named(events, RunEvent.tool_call_started.value)
    reported = _events_named(events, RunEvent.tool_call_error.value)
    assert [event.tool.tool_call_id for event in reported] == ["call_a"]
    assert reported[0].error == REFUSED_TOOL_CALL_ERROR
    # The error itself still reaches the caller, after the closure.
    assert [event.event for event in events[-2:]] == [
        RunEvent.tool_call_error.value,
        RunEvent.run_error.value,
    ]


def test_agent_closes_out_a_call_a_raising_stream_left_open():
    turns, _ = _tool_call_turns()
    # Three deltas in: the call's announcement and two argument fragments.
    agent = Agent(model=_RaisingStreamModel(turns, fail_after=3), tools=[save_note])

    events = list(agent.run("go", stream=True, stream_events=True))

    _assert_a_raising_stream_closes_the_call_it_left_open(events)


async def test_agent_closes_out_a_call_a_raising_stream_left_open_async():
    turns, _ = _tool_call_turns()
    agent = Agent(model=_RaisingStreamModel(turns, fail_after=3), tools=[save_note])

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    _assert_a_raising_stream_closes_the_call_it_left_open(events)


# ---------------------------------------------------------------------------
# A call the run pauses for the caller to confirm
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def save_on_confirmation(note: str) -> str:
    """Save a note, once the caller has agreed to it.

    Args:
        note: the note to save
    """
    return "saved"


def _agent_awaiting_confirmation() -> Tuple[Agent, str]:
    arguments = json.dumps({"note": "the sea is wide"})
    fragments = [_fragment(0, tool_call_id="call_a", tool_name="save_on_confirmation")]
    fragments += [_fragment(0, chunk) for chunk in _chunks(arguments, CHUNK_SIZE)]
    turns = [fragments, [ModelResponse(role="assistant", content="the note is saved")]]
    return Agent(model=_ScriptedStreamModel(turns), tools=[save_on_confirmation]), arguments


def _assert_a_paused_call_is_not_reported_as_never_run(events, arguments: str) -> None:
    """A call waiting on the caller is neither refused nor finished.

    Its arguments streamed before the run could know it would pause, and the
    run holds it open on purpose: the caller has still to say yes. Reporting it
    as a call that was not run would be a lie about a call that may yet be.
    """
    assert _assembled(events, "call_a") == arguments
    assert _events_named(events, RunEvent.run_paused.value)
    assert not _events_named(events, RunEvent.tool_call_error.value)


def test_agent_does_not_report_a_call_awaiting_confirmation_as_never_run():
    agent, arguments = _agent_awaiting_confirmation()

    *events, paused = list(agent.run("go", stream=True, stream_events=True, yield_run_output=True))

    _assert_a_paused_call_is_not_reported_as_never_run(events, arguments)
    assert paused.is_paused
    assert [(tool.tool_call_id, tool.requires_confirmation) for tool in paused.tools] == [("call_a", True)]


async def test_agent_does_not_report_a_call_awaiting_confirmation_as_never_run_async():
    agent, arguments = _agent_awaiting_confirmation()

    *events, paused = [
        event async for event in agent.arun("go", stream=True, stream_events=True, yield_run_output=True)
    ]

    _assert_a_paused_call_is_not_reported_as_never_run(events, arguments)
    assert paused.is_paused
    assert [(tool.tool_call_id, tool.requires_confirmation) for tool in paused.tools] == [("call_a", True)]


# ---------------------------------------------------------------------------
# Nothing is held back on a guess about what the client already has
# ---------------------------------------------------------------------------


def save_map(entry: Dict[str, Any]) -> str:
    """Save a map.

    Args:
        entry: the map to save
    """
    return "mapped"


def _nested_call_beside_an_announcement() -> Tuple[List[List[ModelResponse]], str, str]:
    """A call whose arguments nest, with a second call announced part way through.

    The nesting is the point: the second half of the argument string opens the
    same way the first half did, so anything treating a call's later fragments
    as a possible repeat of its earlier ones reads the second half as the
    first and drops what lies between them.
    """
    nested = json.dumps({"entry": {"entry": 1}})
    head, tail = nested[: len('{"entry": ')], nested[len('{"entry": ') :]
    assert tail.startswith(head), "the fixture no longer has a second half that opens like the first"
    second = json.dumps({"note": "beside it"})
    fragments = [
        _fragment(0, tool_call_id="call_a", tool_name="save_map"),
        _fragment(0, head),
        # A second call announced while the first is still being written. It
        # carries a tool call and no argument text, which is exactly the shape
        # of the first delta of a stream that has started over.
        _fragment(1, tool_call_id="call_b", tool_name="save_note"),
        _fragment(0, tail),
        _fragment(1, second),
    ]
    return [fragments, [ModelResponse(role="assistant", content="both are saved")]], nested, second


def test_agent_streams_the_whole_arguments_of_a_call_a_second_call_was_announced_beside():
    turns, nested, second = _nested_call_beside_an_announcement()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_map, save_note])

    events = list(agent.run("go", stream=True, stream_events=True))

    assert _assembled(events, "call_a") == nested
    assert _assembled(events, "call_b") == second
    # Both calls really were made on those arguments, so the fragments and the
    # run agree about what the model asked for.
    announced = {
        event.tool.tool_call_id: event.tool.tool_args
        for event in _events_named(events, RunEvent.tool_call_started.value)
    }
    assert announced == {"call_a": json.loads(nested), "call_b": json.loads(second)}


async def test_agent_streams_the_whole_arguments_of_a_call_a_second_call_was_announced_beside_async():
    turns, nested, second = _nested_call_beside_an_announcement()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_map, save_note])

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    assert _assembled(events, "call_a") == nested
    assert _assembled(events, "call_b") == second


def _same_call_id_twice() -> Tuple[List[List[ModelResponse]], str]:
    """Two turns calling the same tool, under one id, on the same arguments.

    Which is every call a provider makes twice under a reused id, and every
    call to a tool that takes no arguments at all.
    """
    arguments = json.dumps({"note": "again"})
    turn = [_fragment(0, tool_call_id="call_a", tool_name="save_note")]
    turn += [_fragment(0, chunk) for chunk in _chunks(arguments, CHUNK_SIZE)]
    reply = [ModelResponse(role="assistant", content="saved twice")]
    return [list(turn), list(turn), reply], arguments


def test_agent_streams_a_call_id_a_later_turn_uses_again():
    turns, arguments = _same_call_id_twice()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    events = list(agent.run("go", stream=True, stream_events=True))

    # Both turns really ran, and each streamed the arguments in full: a turn
    # whose call happens to repeat an earlier one is still a call of its own.
    assert len(_events_named(events, RunEvent.model_request_started.value)) == len(turns)
    deltas = _events_named(events, RunEvent.tool_call_args_delta.value)
    assert len(deltas) == 2 * len(_chunks(arguments, CHUNK_SIZE))
    assert _assembled(events, "call_a") == arguments * 2


async def test_agent_streams_a_call_id_a_later_turn_uses_again_async():
    turns, arguments = _same_call_id_twice()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    assert len(_events_named(events, RunEvent.model_request_started.value)) == len(turns)
    assert _assembled(events, "call_a") == arguments * 2


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
    return len(_events_named(events, RunEvent.tool_call_args_delta.value)) == 2


def _assert_the_cancelled_run_ends_and_nothing_waits_on_it(events) -> None:
    """The run ends on its terminal events with the call it streamed undecided.

    A cancellation is raised where the run's events are consumed, so the
    stream that was writing the arguments is closed rather than read to the
    end. Nothing can be added to a stream nobody is reading, and the call a
    client is holding is closed out by the terminal events the run does end
    on.
    """
    assert _events_named(events, RunEvent.tool_call_args_delta.value), "nothing streamed, so nothing to cancel"
    assert not _events_named(events, RunEvent.tool_call_started.value)
    assert [event.event for event in events[-2:]] == [
        RunEvent.run_cancelled.value,
        RunEvent.run_completed.value,
    ]


class _InterruptedStreamModel(_ScriptedStreamModel):
    """Streams part of a turn and is then interrupted at the keyboard."""

    def __init__(self, turns: List[List[ModelResponse]], interrupt_after: int):
        super().__init__(turns)
        self._interrupt_after = interrupt_after

    def _up_to_the_interruption(self) -> List[ModelResponse]:
        return self._next_turn()[: self._interrupt_after]

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield from self._up_to_the_interruption()
        raise KeyboardInterrupt()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        for delta in self._up_to_the_interruption():
            yield delta
        raise KeyboardInterrupt()


def _assert_the_interruption_was_left_to_the_run(events) -> None:
    """Nothing on the way out treats an interrupt as a call to report on.

    A keyboard interrupt is not a provider saying a call will not be made, and
    catching it to say so is catching it: what the caller sees is the run's own
    interrupt handling, and no reported call among it.
    """
    assert _events_named(events, RunEvent.tool_call_args_delta.value), "nothing streamed, so nothing to report"
    assert not _events_named(events, RunEvent.tool_call_error.value)
    assert [event.event for event in events[-2:]] == [
        RunEvent.run_cancelled.value,
        RunEvent.run_completed.value,
    ]


def test_agent_leaves_a_keyboard_interrupt_to_the_run():
    turns, _ = _tool_call_turns()
    agent = Agent(model=_InterruptedStreamModel(turns, interrupt_after=3), tools=[save_note])

    events = list(agent.run("go", stream=True, stream_events=True))

    _assert_the_interruption_was_left_to_the_run(events)


async def test_agent_leaves_a_keyboard_interrupt_to_the_run_async():
    turns, _ = _tool_call_turns()
    agent = Agent(model=_InterruptedStreamModel(turns, interrupt_after=3), tools=[save_note])

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    _assert_the_interruption_was_left_to_the_run(events)


def test_agent_cancelled_while_a_calls_arguments_stream_ends_the_run():
    turns, _ = _tool_call_turns()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    events: List[Any] = []
    for event in agent.run("go", stream=True, stream_events=True):
        events.append(event)
        if _arguments_are_part_written(events):
            Agent.cancel_run(event.run_id)

    _assert_the_cancelled_run_ends_and_nothing_waits_on_it(events)


def test_agent_cancelled_while_a_calls_arguments_stream_closes_its_stream_cleanly():
    """The stream the cancelled run abandoned is closed without complaint.

    A cancellation is raised where the events are consumed, so the stream
    writing the arguments is closed rather than read to the end. An async
    generator that yields while it is being closed makes that closing raise,
    and the loop reports it where nothing asserting on the run would see it.
    """
    turns, _ = _tool_call_turns()
    agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])

    async def consume() -> List[Any]:
        events: List[Any] = []
        async for event in agent.arun("go", stream=True, stream_events=True):
            events.append(event)
            if _arguments_are_part_written(events):
                await Agent.acancel_run(event.run_id)
        return events

    with _asyncio_errors_reported() as reported:
        # A loop of this test's own, because a stream a cancelled run
        # abandoned is closed when the loop that ran it is closed.
        events = asyncio.run(consume())

    _assert_the_cancelled_run_ends_and_nothing_waits_on_it(events)
    assert [record.getMessage() for record in reported] == []


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


def _agent_with_a_recording_output_model() -> Tuple[Agent, _ToolRecordingModel, str]:
    """An output model whose script calls a tool, over a quiet agent model."""
    turns, arguments = _tool_call_turns()
    output_model = _ToolRecordingModel(turns)
    return Agent(model=_quiet_model(), output_model=output_model, tools=[save_note]), output_model, arguments


def _assert_the_output_models_call_reached_the_client(
    events, output_model: _ToolRecordingModel, arguments: str, errors: List[logging.LogRecord]
) -> None:
    """A call can arrive here even though the path hands the model no tools.

    The output model is asked for the finished answer, never for work, so the
    run passes it none of the agent's tools. A provider can still answer with
    a call to a built-in tool of its own, and then its fragments have to be
    attributed and its call closed out like any other. The script stands in for
    that provider, and the run refuses to find the function, which is why the
    call the client was shown ends as a reported failure rather than as one it
    waits on for good.
    """
    assert output_model.tools_seen == [None]
    assert _assembled(events, "call_a") == arguments
    assert not _events_named(events, RunEvent.tool_call_started.value)
    reported = _events_named(events, RunEvent.tool_call_error.value)
    assert [event.tool.tool_call_id for event in reported] == ["call_a"]
    assert reported[0].error == REFUSED_TOOL_CALL_ERROR
    assert [record.getMessage() for record in errors] == ["Function save_note not found"]


def test_agent_output_model_streams_and_closes_out_a_tool_call(errors_logged):
    agent, output_model, arguments = _agent_with_a_recording_output_model()

    events = list(agent.run("go", stream=True, stream_events=True))

    _assert_the_output_models_call_reached_the_client(events, output_model, arguments, errors_logged)


async def test_agent_output_model_streams_and_closes_out_a_tool_call_async(errors_logged):
    agent, output_model, arguments = _agent_with_a_recording_output_model()

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    _assert_the_output_models_call_reached_the_client(events, output_model, arguments, errors_logged)


def _agent_with_a_two_turn_output_model() -> Tuple[Agent, str, str]:
    """An output model that calls a tool on each of two turns of its own."""
    turns, first, second = _two_turn_calls()
    return (
        Agent(model=_quiet_model(), output_model=_ToolRecordingModel(turns), tools=[save_note, save_other]),
        first,
        second,
    )


def _assert_the_output_models_turns_are_held_apart(
    events, first: str, second: str, warnings: List[logging.LogRecord]
) -> None:
    """This path's turn boundary is the request event the chunk handler sees.

    The agent's own loop reads that event itself, so nothing but the chunk
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


def test_agent_output_model_does_not_carry_tool_call_ids_across_its_turns(warnings_logged):
    agent, first, second = _agent_with_a_two_turn_output_model()

    events = list(agent.run("go", stream=True, stream_events=True))

    _assert_the_output_models_turns_are_held_apart(events, first, second, warnings_logged)


async def test_agent_output_model_does_not_carry_tool_call_ids_across_its_turns_async(warnings_logged):
    agent, first, second = _agent_with_a_two_turn_output_model()

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

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
    chunks.append(ModelResponse(role="assistant", content="the note is saved"))
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


def _assert_the_output_model_path_adds_only_the_fragments(events) -> None:
    """The fragments are what this path gained; its announcements are as they were.

    An agent's output model path announced a provider's own call, and read a
    call to ``think`` as a reasoning step, before it carried any fragments,
    and it still does. A team's output model path announces neither. That
    difference between the two is older than the fragments and is left alone
    here, because changing which lifecycle events a client sees is a decision
    of its own and not something to thread a fragment stream into.
    """
    assert _assembled(events, "call_builtin") == _ANNOUNCED_ARGUMENTS
    announced = _events_named(events, RunEvent.tool_call_started.value)
    assert [event.tool.tool_call_id for event in announced] == ["call_builtin"]
    finished = _events_named(events, RunEvent.tool_call_completed.value)
    assert [event.tool.tool_call_id for event in finished] == ["call_builtin"]
    assert [event.content.title for event in _events_named(events, RunEvent.reasoning_step.value)] == ["the plan"]
    # The provider answered the call it announced, so nothing is left to close out.
    assert not _events_named(events, RunEvent.tool_call_error.value)


def test_agent_output_model_adds_only_the_argument_fragments():
    agent = Agent(model=_quiet_model(), output_model=_ProviderAnnouncingModel())

    events = list(agent.run("go", stream=True, stream_events=True))

    _assert_the_output_model_path_adds_only_the_fragments(events)


async def test_agent_output_model_adds_only_the_argument_fragments_async():
    agent = Agent(model=_quiet_model(), output_model=_ProviderAnnouncingModel())

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    _assert_the_output_model_path_adds_only_the_fragments(events)


# ---------------------------------------------------------------------------
# Chunk handler
# ---------------------------------------------------------------------------


def _through_the_chunk_handler(agent: Agent, tool_args_stream: ToolCallArgsStream, chunks) -> List[Any]:
    """Every event the handler yields for a run of chunks, in order."""
    session = AgentSession(session_id="session_1")
    run_response = RunOutput(run_id="run_1", agent_id="agent_1", agent_name="Agent")
    events: List[Any] = []
    for chunk in chunks:
        events.extend(
            handle_model_response_chunk(
                agent,
                session=session,
                run_response=run_response,
                model_response=ModelResponse(),
                model_response_event=chunk,
                stream_events=True,
                tool_args_stream=tool_args_stream,
            )
        )
    return events


def test_agent_chunk_handler_drops_its_stream_indexes_when_a_fallback_is_activated(warnings_logged):
    """A replaced model's numbering is not the numbering of the one taking over.

    A fallback model answers the request the primary failed part way through,
    and its stream indexes start again at zero. Without a boundary there, its
    opening fragment, which carries index zero and no id, would be appended to
    the arguments of the call the replaced model was still writing, and a
    subscriber would render two models' text as one call's arguments.
    """
    agent = Agent(model=_quiet_model(), tools=[save_note])
    tool_args_stream = ToolCallArgsStream("session_1", "run_1")
    replaced = _fragment(0, '{"note":', tool_call_id="call_a", tool_name="save_note")
    replaced.event = ModelResponseEvent.assistant_response.value
    taking_over = _fragment(0, ' "the sea is wide"}')
    taking_over.event = ModelResponseEvent.assistant_response.value

    events = _through_the_chunk_handler(
        agent,
        tool_args_stream,
        (
            replaced,
            ModelResponse(event=ModelResponseEvent.fallback_model_activated.value),
            taking_over,
        ),
    )

    deltas = _events_named(events, RunEvent.tool_call_args_delta.value)
    assert [(delta.tool_call_id, delta.tool_args_delta) for delta in deltas] == [("call_a", '{"note":')]
    # The fragment after the boundary belongs to no call yet, and the run says
    # so rather than placing it on the replaced model's call.
    reported = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
    assert len(reported) == 1, reported
    assert "neither a tool call id nor a provider stream index" in reported[0]
    # The replaced model's call will never be made under its own id either, so
    # the client is not left waiting on it.
    closed = _events_named(events, RunEvent.tool_call_error.value)
    assert [event.tool.tool_call_id for event in closed] == ["call_a"]
    assert closed[0].error == REFUSED_TOOL_CALL_ERROR


# ---------------------------------------------------------------------------
# Parser model
# ---------------------------------------------------------------------------


def _parser_model_turns() -> List[List[ModelResponse]]:
    """One turn calling a tool in fragments, then one answering the output schema."""
    turns, _ = _tool_call_turns()
    return [turns[0], [ModelResponse(role="assistant", content=json.dumps({"note": "parsed"}))]]


def _agent_with_a_calling_parser_model() -> Tuple[Agent, _NonStreamedCallModel]:
    parser = _NonStreamedCallModel(_parser_model_turns())
    agent = Agent(
        model=_ScriptedStreamModel([[ModelResponse(role="assistant", content=json.dumps({"note": "draft"}))]]),
        parser_model=parser,
        output_schema=_Note,
    )
    return agent, parser


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
    assert not _events_named(events, RunEvent.tool_call_args_delta.value)
    # It is handed no tools either, so the run refuses to find the function it
    # named and says so once.
    assert [record.getMessage() for record in errors] == ["Function save_note not found"]


def test_agent_parser_model_emits_no_tool_call_arg_fragments(errors_logged):
    agent, parser = _agent_with_a_calling_parser_model()

    events = list(agent.run("go", stream=True, stream_events=True))

    _assert_the_parser_model_streamed_no_fragments(events, parser, errors_logged)


async def test_agent_parser_model_emits_no_tool_call_arg_fragments_async(errors_logged):
    agent, parser = _agent_with_a_calling_parser_model()

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    _assert_the_parser_model_streamed_no_fragments(events, parser, errors_logged)


# ---------------------------------------------------------------------------
# Event storage
# ---------------------------------------------------------------------------


def _agent_storing_events(tmp_path, db_name: str, **kwargs) -> Tuple[Agent, str]:
    turns, arguments = _tool_call_turns()
    agent = Agent(
        model=_ScriptedStreamModel(turns),
        tools=[save_note],
        db=SqliteDb(db_file=str(tmp_path / db_name)),
        store_events=True,
        **kwargs,
    )
    return agent, arguments


def test_agent_keeps_tool_call_arg_fragments_out_of_the_stored_run_by_default(tmp_path):
    agent, arguments = _agent_storing_events(tmp_path, "default_agent.db")

    events = list(agent.run("go", stream=True, stream_events=True))
    run_output = agent.get_last_run_output()

    # The subscriber still sees every fragment: the skip list governs storage.
    deltas = [event for event in events if event.event == RunEvent.tool_call_args_delta.value]
    assert "".join(delta.tool_args_delta for delta in deltas) == arguments

    stored = _stored(run_output)
    assert RunEvent.tool_call_args_delta.value not in stored
    # Held to the same standard as the content delta it is being grouped with,
    # and the low frequency events are stored as before.
    assert RunEvent.run_content.value not in stored
    assert RunEvent.tool_call_started.value in stored
    assert RunEvent.tool_call_completed.value in stored


async def test_agent_keeps_tool_call_arg_fragments_out_of_the_stored_run_by_default_async(tmp_path):
    agent, arguments = _agent_storing_events(tmp_path, "default_agent_async.db")

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]
    run_output = await agent.aget_last_run_output()

    deltas = [event for event in events if event.event == RunEvent.tool_call_args_delta.value]
    assert "".join(delta.tool_args_delta for delta in deltas) == arguments

    stored = _stored(run_output)
    assert RunEvent.tool_call_args_delta.value not in stored
    assert RunEvent.run_content.value not in stored
    assert RunEvent.tool_call_started.value in stored


def test_agent_stores_tool_call_arg_fragments_when_the_caller_asks_for_them(tmp_path, skips_but_the_argument_fragments):
    # Asking for the fragments back re-enables nothing else the default keeps
    # out of storage, the content delta included.
    agent, arguments = _agent_storing_events(
        tmp_path,
        "opted_in_agent.db",
        events_to_skip=skips_but_the_argument_fragments(Agent(model=_quiet_model())),
    )

    list(agent.run("go", stream=True, stream_events=True))
    run_output = agent.get_last_run_output()

    fragments = [event for event in (run_output.events or []) if event.event == RunEvent.tool_call_args_delta.value]
    assert "".join(event.tool_args_delta for event in fragments) == arguments
    assert RunEvent.run_content.value not in _stored(run_output)


def test_agent_omits_tool_call_arg_fragments_without_events():
    turns, arguments = _tool_call_turns()

    streaming_agent = Agent(model=_ScriptedStreamModel(turns), tools=[save_note])
    streamed = list(streaming_agent.run("go", stream=True, stream_events=False))

    # The run did stream to the caller, so the absence of fragments is the
    # flag's doing and not an empty stream.
    assert _events_named(streamed, RunEvent.run_content.value)
    assert not _events_named(streamed, RunEvent.tool_call_args_delta.value)

    # Nothing is skipped by configuration here, so an empty store is this
    # path's doing: a run that never streamed creates no events to store,
    # fragments included.
    non_streaming_agent = Agent(
        model=_AggregatingStreamModel(_tool_call_turns()[0]),
        tools=[save_note],
        store_events=True,
        events_to_skip=[],
    )
    run_output = non_streaming_agent.run("go")
    assert run_output.events is None
    # The run still made the call, so the absence is not a broken run.
    assert run_output.tools[0].tool_args == json.loads(arguments)


# ---------------------------------------------------------------------------
# A run nested inside a tool call
# ---------------------------------------------------------------------------


def _inner_agent_making_a_call() -> Tuple[Agent, str, str]:
    """A second agent whose own turn streams a tool call in fragments.

    Returns the id that call streams under, so its fragments can be told
    apart from the outer run's own.
    """
    turns, arguments = _tool_call_turns()
    agent = Agent(name="inner", model=_ScriptedStreamModel(turns), tools=[save_note])
    return agent, "call_a", arguments


def _outer_agent_calling(nesting_tool) -> Agent:
    """An agent whose one turn calls the tool that runs the other agent.

    A tool's generator may yield run events, and the model's call handler
    bubbles them up rather than folding them into the tool's result. Agno's
    own team delegation and workflow tools have that shape, so a nested run's
    events reach this run the same way whoever wrote the tool arranged it.
    """
    arguments = json.dumps({"question": "write the note"})
    fragments = [_fragment(0, tool_call_id="call_outer", tool_name=nesting_tool.__name__)]
    fragments += [_fragment(0, chunk) for chunk in _chunks(arguments, CHUNK_SIZE)]
    turns = [fragments, [ModelResponse(role="assistant", content="the inner agent saved it")]]
    return Agent(name="outer", model=_ScriptedStreamModel(turns), tools=[nesting_tool])


def _agent_nesting_a_run() -> Tuple[Agent, str, str]:
    inner, call_id, arguments = _inner_agent_making_a_call()

    def ask_the_inner_agent(question: str):
        """Ask the inner agent to write a note.

        Args:
            question: what to ask it
        """
        yield from inner.run(question, stream=True, stream_events=True)

    return _outer_agent_calling(ask_the_inner_agent), call_id, arguments


def _agent_nesting_an_async_run() -> Tuple[Agent, str, str]:
    inner, call_id, arguments = _inner_agent_making_a_call()

    async def ask_the_inner_agent(question: str):
        """Ask the inner agent to write a note.

        Args:
            question: what to ask it
        """
        async for event in inner.arun(question, stream=True, stream_events=True):
            yield event

    return _outer_agent_calling(ask_the_inner_agent), call_id, arguments


def _assert_the_nested_runs_call_streamed(events, call_id: str, arguments: str) -> None:
    assert _assembled(events, call_id) == arguments


def test_agent_streams_a_nested_runs_tool_call_arg_fragments():
    agent, call_id, arguments = _agent_nesting_a_run()

    events = list(agent.run("go", stream=True, stream_events=True))

    _assert_the_nested_runs_call_streamed(events, call_id, arguments)


async def test_agent_streams_a_nested_runs_tool_call_arg_fragments_async():
    agent, call_id, arguments = _agent_nesting_an_async_run()

    events = [event async for event in agent.arun("go", stream=True, stream_events=True)]

    _assert_the_nested_runs_call_streamed(events, call_id, arguments)


def _assert_a_run_told_not_to_stream_events_delivers_no_fragments(events, arguments: str) -> None:
    """A run told not to stream events is told that of the runs it nests too.

    A nested run is run with events on so the tool running it can read them,
    and they reach the caller through this run. So a guard on this run's own
    model alone leaves a caller that opted out holding the nested run's
    fragments.
    """
    assert not _events_named(events, RunEvent.tool_call_args_delta.value)
    # The nested run made its call, and its other events arrive as before, so
    # the absence above is the flag's doing and not an empty stream.
    completed = _events_named(events, RunEvent.tool_call_completed.value)
    assert arguments in [json.dumps(event.tool.tool_args) for event in completed]
    assert _events_named(events, RunEvent.run_started.value)


def test_agent_delivers_no_nested_runs_fragments_without_stream_events():
    agent, _call_id, arguments = _agent_nesting_a_run()

    events = list(agent.run("go", stream=True, stream_events=False))

    _assert_a_run_told_not_to_stream_events_delivers_no_fragments(events, arguments)


async def test_agent_delivers_no_nested_runs_fragments_without_stream_events_async():
    agent, _call_id, arguments = _agent_nesting_an_async_run()

    events = [event async for event in agent.arun("go", stream=True, stream_events=False)]

    _assert_a_run_told_not_to_stream_events_delivers_no_fragments(events, arguments)
