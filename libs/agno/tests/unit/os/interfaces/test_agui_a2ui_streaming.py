"""Progressive painting of a generated A2UI surface.

A client paints a generated surface from the render call's argument fragments as
they arrive. The generation tool holds the agent's event stream open while its
render subagent works, so those fragments need a channel of their own to get
out; otherwise the surface only appears once generation has finished.
"""

import asyncio
import json
from contextvars import ContextVar
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")
pytest.importorskip("ag_ui_a2ui_toolkit", reason="ag_ui_a2ui_toolkit not installed")

from ag_ui_a2ui_toolkit import A2UI_SCHEMA_CONTEXT_DESCRIPTION, GENERATE_A2UI_TOOL_NAME  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.models.response import ToolExecution  # noqa: E402
from agno.os.app import AgentOS  # noqa: E402
from agno.os.interfaces.agui import AGUI  # noqa: E402
from agno.os.interfaces.agui.a2ui import (  # noqa: E402
    RENDER_A2UI_TOOL_NAME,
    A2UIRenderAttempt,
    get_a2ui_tools,
)
from agno.os.interfaces.agui.a2ui_stream import (  # noqa: E402
    A2UIRenderStream,
    A2UIRun,
    ToolPresence,
    current_a2ui_run,
    resolve_entity_tools,
)
from agno.os.interfaces.agui.handlers import (  # noqa: E402
    RENDER_A2UI_TOOL_NAME_FALLBACK,
    close_open_spans,
    on_a2ui_render_stream,
    process_event,
)
from agno.os.interfaces.agui.router import _track_spans, run_entity  # noqa: E402
from agno.os.interfaces.agui.state import StreamState  # noqa: E402
from agno.os.interfaces.agui.stream import async_stream_agno_response_as_agui_events  # noqa: E402
from agno.run.agent import (  # noqa: E402
    ReasoningStartedEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunEvent,
    ToolCallStartedEvent,
)
from agno.tools.function import Function  # noqa: E402

CATALOG_ID = "declarative-gen-ui-catalog"

COMPONENTS = [
    {"id": "root", "component": "Column", "children": ["title"]},
    {"id": "title", "component": "Text", "text": "Quarterly sales"},
]


# =============================================================================
# The channel itself
# =============================================================================


@pytest.mark.asyncio
async def test_pushed_fragments_come_back_in_order():
    stream = A2UIRenderStream()

    stream.push({"kind": "start"})
    stream.push({"kind": "args"})

    assert stream.drain() == [{"kind": "start"}, {"kind": "args"}]
    assert stream.drain() == []


@pytest.mark.asyncio
async def test_waiting_returns_as_soon_as_something_is_pushed():
    stream = A2UIRenderStream()
    waiter = asyncio.ensure_future(stream.wait())
    await asyncio.sleep(0)

    assert not waiter.done()

    stream.push({"kind": "start"})
    await asyncio.wait_for(waiter, 1)


@pytest.mark.asyncio
async def test_draining_rearms_the_wait():
    stream = A2UIRenderStream()
    stream.push({"kind": "start"})
    stream.drain()

    waiter = asyncio.ensure_future(stream.wait())
    await asyncio.sleep(0)

    assert not waiter.done()
    waiter.cancel()


# =============================================================================
# Deciding whether a run needs the channel
# =============================================================================


def generation_answer(entity: Any) -> ToolPresence:
    return resolve_entity_tools(entity).generates_a2ui()


def test_an_agent_carrying_the_generation_tool_is_recognized():
    class Stub:
        assistant_message_role = "assistant"

    agent = Agent(id="a", name="A", tools=[get_a2ui_tools({"model": Stub()})])

    assert generation_answer(agent) is ToolPresence.PRESENT


def test_an_agent_with_other_tools_is_not():
    agent = Agent(id="a", name="A", tools=[Function(name="search_web", entrypoint=lambda: "")])

    assert generation_answer(agent) is ToolPresence.ABSENT


def test_an_agent_with_no_tools_is_not():
    assert generation_answer(Agent(id="a", name="A")) is ToolPresence.ABSENT


def test_tools_behind_a_factory_cannot_be_inspected():
    """A callable is resolved by the agent later, so whether the run will
    generate a surface is not knowable here.

    Answered as "no", such a run painted its surface in one go with nothing
    saying why, so the answer is its own value and this caller prepares a
    channel on the maybe: an unread one costs the run nothing.
    """

    def build_tools():
        return []

    agent = Agent(id="a", name="A", tools=build_tools)

    assert generation_answer(agent) is ToolPresence.UNKNOWN


# =============================================================================
# Translating fragments into events
# =============================================================================


def test_a_start_fragment_opens_a_nested_tool_call():
    state = StreamState(thread_id="t", run_id="r")

    events = on_a2ui_render_stream(
        {"kind": "start", "tool_call_id": "inner", "tool_call_name": RENDER_A2UI_TOOL_NAME}, state
    )

    assert [event.type for event in events] == ["TOOL_CALL_START"]
    assert events[0].tool_call_name == RENDER_A2UI_TOOL_NAME
    assert "inner" in state.active_tool_call_ids


def test_a_start_fragment_finishes_an_open_text_message_first():
    state = StreamState(thread_id="t", run_id="r")
    state.open_text_message()

    events = on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)

    assert [event.type for event in events] == ["TEXT_MESSAGE_END", "TOOL_CALL_START"]
    assert state.text_message_open is False


def test_argument_fragments_become_argument_events():
    state = StreamState(thread_id="t", run_id="r")
    on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)

    events = on_a2ui_render_stream({"kind": "args", "tool_call_id": "inner", "delta": '{"a":'}, state)

    assert [event.type for event in events] == ["TOOL_CALL_ARGS"]
    assert events[0].delta == '{"a":'


def test_an_empty_fragment_emits_nothing():
    state = StreamState(thread_id="t", run_id="r")
    on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)

    assert on_a2ui_render_stream({"kind": "args", "tool_call_id": "inner", "delta": ""}, state) == []


def test_arguments_for_a_call_that_was_never_started_are_dropped():
    """Arguments only mean something for a call the client has been told about.

    Every tool-call event names a call, and one the client never saw opened is
    one it has nothing to attach the arguments to.
    """
    state = StreamState(thread_id="t", run_id="r")

    assert on_a2ui_render_stream({"kind": "args", "tool_call_id": "inner", "delta": '{"a":'}, state) == []


def test_arguments_arriving_after_the_call_ended_are_dropped():
    """The end is the client's last word on that call.

    A late fragment would reopen a call the client has already finished with,
    which is the same hazard the end branch already guards against, from the
    other side.
    """
    state = StreamState(thread_id="t", run_id="r")
    on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)
    on_a2ui_render_stream({"kind": "end", "tool_call_id": "inner"}, state)

    assert on_a2ui_render_stream({"kind": "args", "tool_call_id": "inner", "delta": '{"late"'}, state) == []


def test_an_end_fragment_closes_the_call_once():
    state = StreamState(thread_id="t", run_id="r")
    on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)

    first = on_a2ui_render_stream({"kind": "end", "tool_call_id": "inner"}, state)
    again = on_a2ui_render_stream({"kind": "end", "tool_call_id": "inner"}, state)

    assert [event.type for event in first] == ["TOOL_CALL_END"]
    assert again == []


def test_an_end_for_a_call_that_never_started_is_dropped():
    """An end names a call the client was told about.

    One for a call it never saw opened is not merely useless: the client's
    event verifier rejects it, and rejects it fatally, so the run loses every
    event after it too.
    """
    state = StreamState(thread_id="t", run_id="r")

    assert on_a2ui_render_stream({"kind": "end", "tool_call_id": "inner"}, state) == []
    assert state.ended_tool_call_ids == set()


@pytest.mark.parametrize("first_call_is", ["still open", "already ended"])
def test_a_second_start_under_the_same_id_is_dropped(first_call_is):
    """A wire id belongs to one call, and the client buffers arguments by it.

    A second start under a spent id, whether a duplicate or an attempt reusing
    a rejected one's id, appends this surface to the buffer the client still
    holds for the other, so the two parse as one malformed object and neither
    paints. Refused here, the first surface survives whole.
    """
    state = StreamState(thread_id="t", run_id="r")
    on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)
    if first_call_is == "already ended":
        on_a2ui_render_stream({"kind": "end", "tool_call_id": "inner"}, state)

    assert on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state) == []

    # The first call's own span is untouched, so it is still ended exactly once.
    assert ("inner" in state.active_tool_call_ids) is (first_call_is == "still open")


def test_a_fragment_without_a_call_id_is_dropped_without_touching_the_run():
    """Dropped rather than raised, and dropped whole.

    An id is mandatory on every tool-call event, so a fragment without one
    cannot become an event at all: the choice is between dropping it and
    tearing down a run whose generated surface still arrives as the tool
    result, and dropping is the right one. What it must not do is half-apply
    the fragment, so nothing is opened, closed or reparented on the way out.
    """
    state = StreamState(thread_id="t", run_id="r")
    state.open_text_message()

    assert on_a2ui_render_stream({"kind": "start", "delta": "x"}, state) == []
    assert on_a2ui_render_stream({"kind": "args", "delta": "x"}, state) == []
    assert on_a2ui_render_stream({"kind": "end"}, state) == []

    assert state.active_tool_call_ids == set()
    assert state.text_message_open is True


def test_an_unknown_fragment_kind_is_ignored_and_the_call_still_works():
    """The kinds are a closed set this package pushes to itself, so an unknown
    one is a bug here rather than anything a client or a model sent. Ignoring
    it keeps the rest of that call renderable, which is worth more than
    refusing a whole surface over one fragment nobody can act on."""
    state = StreamState(thread_id="t", run_id="r")
    on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)

    assert on_a2ui_render_stream({"kind": "something-new", "tool_call_id": "inner"}, state) == []

    # The call it named is untouched, so the fragments around it still paint.
    assert "inner" in state.active_tool_call_ids
    assert [event.type for event in on_a2ui_render_stream({"kind": "end", "tool_call_id": "inner"}, state)] == [
        "TOOL_CALL_END"
    ]


# =============================================================================
# Interleaving with the agent's own events
# =============================================================================


async def _collect(stream: AsyncIterator[Any]) -> List[Any]:
    return [event async for event in stream]


@pytest.mark.asyncio
async def test_a_run_without_generation_is_unaffected():
    async def agent_events() -> AsyncIterator[Any]:
        yield RunContentEvent(event=RunEvent.run_content.value, content="hello")
        yield RunCompletedEvent()

    events = await _collect(async_stream_agno_response_as_agui_events(agent_events(), thread_id="t", run_id="r"))

    assert [event.type for event in events] == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]


@pytest.mark.asyncio
async def test_fragments_pushed_while_the_agent_is_busy_are_emitted_before_it_resumes():
    render_stream = A2UIRenderStream()
    released = asyncio.Event()

    async def agent_events() -> AsyncIterator[Any]:
        yield RunContentEvent(event=RunEvent.run_content.value, content="working")
        # Stand in for a generation tool: the agent produces nothing while its
        # subagent streams.
        render_stream.push({"kind": "start", "tool_call_id": "inner"})
        render_stream.push({"kind": "args", "tool_call_id": "inner", "delta": "{"})
        # Bounded: nothing releases this if the fragments are held back until
        # the run moves on, and a suite that hangs reports nothing at all.
        await asyncio.wait_for(released.wait(), 10)
        render_stream.push({"kind": "end", "tool_call_id": "inner"})
        yield RunCompletedEvent()

    collected: List[Any] = []
    source = async_stream_agno_response_as_agui_events(
        agent_events(), thread_id="t", run_id="r", a2ui_render_stream=render_stream
    )

    async for event in source:
        collected.append(event)
        # The agent is blocked at this point, so seeing the fragment at all
        # proves it did not have to wait for the run to move on.
        if event.type == "TOOL_CALL_ARGS":
            released.set()

    assert [event.type for event in collected] == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "RUN_FINISHED",
    ]


@pytest.mark.asyncio
async def test_fragments_pushed_at_the_very_end_are_not_lost():
    render_stream = A2UIRenderStream()

    async def agent_events() -> AsyncIterator[Any]:
        yield RunCompletedEvent()
        render_stream.push({"kind": "start", "tool_call_id": "inner"})

    events = await _collect(
        async_stream_agno_response_as_agui_events(
            agent_events(), thread_id="t", run_id="r", a2ui_render_stream=render_stream
        )
    )

    assert "TOOL_CALL_START" in [event.type for event in events]


@pytest.mark.asyncio
async def test_a_run_that_ends_mid_generation_closes_the_nested_call():
    render_stream = A2UIRenderStream()

    async def agent_events() -> AsyncIterator[Any]:
        render_stream.push({"kind": "start", "tool_call_id": "inner"})
        render_stream.push({"kind": "args", "tool_call_id": "inner", "delta": '{"partial"'})
        yield RunCompletedEvent()

    events = await _collect(
        async_stream_agno_response_as_agui_events(
            agent_events(), thread_id="t", run_id="r", a2ui_render_stream=render_stream
        )
    )

    types = [event.type for event in events]
    assert types == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "RUN_FINISHED"]


# =============================================================================
# Carrying the run's context, and unwinding early
# =============================================================================


@pytest.mark.asyncio
async def test_context_the_run_sets_survives_into_its_next_event():
    """A run's context is its own: nothing about interleaving may discard it.

    Every event of an A2UI-enabled run goes through the interleaving path, so a
    context variable a tool sets while producing one event has to still be set
    while producing the next, exactly as it is without interleaving.
    """
    marker: ContextVar[Optional[str]] = ContextVar("test_marker", default=None)
    observed: List[Optional[str]] = []

    async def agent_events() -> AsyncIterator[Any]:
        marker.set("set-by-the-run")
        yield RunContentEvent(event=RunEvent.run_content.value, content="working")
        observed.append(marker.get())
        yield RunCompletedEvent()

    await _collect(
        async_stream_agno_response_as_agui_events(
            agent_events(), thread_id="t", run_id="r", a2ui_render_stream=A2UIRenderStream()
        )
    )

    assert observed == ["set-by-the-run"]


@pytest.mark.asyncio
async def test_context_the_run_sets_survives_without_interleaving_too():
    """The baseline the test above has to match."""
    marker: ContextVar[Optional[str]] = ContextVar("test_marker_plain", default=None)
    observed: List[Optional[str]] = []

    async def agent_events() -> AsyncIterator[Any]:
        marker.set("set-by-the-run")
        yield RunContentEvent(event=RunEvent.run_content.value, content="working")
        observed.append(marker.get())
        yield RunCompletedEvent()

    await _collect(async_stream_agno_response_as_agui_events(agent_events(), thread_id="t", run_id="r"))

    assert observed == ["set-by-the-run"]


@pytest.mark.asyncio
async def test_a_client_leaving_mid_generation_finalizes_the_run():
    """Closing the mapper has to leave the run finalized, not merely cancelled.

    The response is abandoned while the generation tool still holds the run
    open. Whatever the run does on the way out, such as recording that it was
    cancelled, has to have happened by the time the mapper is closed: the
    request is over and nothing else will drive it.
    """
    render_stream = A2UIRenderStream()
    finalized = asyncio.Event()
    tool_returns = asyncio.Event()

    async def agent_events() -> AsyncIterator[Any]:
        try:
            render_stream.push({"kind": "start", "tool_call_id": "inner"})
            await tool_returns.wait()
            yield RunCompletedEvent()
        finally:
            finalized.set()

    source = async_stream_agno_response_as_agui_events(
        agent_events(), thread_id="t", run_id="r", a2ui_render_stream=render_stream
    )

    async for event in source:
        if event.type == "TOOL_CALL_START":
            break

    await source.aclose()

    assert finalized.is_set()


@pytest.mark.asyncio
async def test_a_client_leaving_between_events_closes_the_agent_stream():
    """The same, with the run suspended at one of its own events.

    Nothing is in flight here, so there is nothing to cancel: the agent's stream
    has to be closed for its cleanup to run at all.
    """
    render_stream = A2UIRenderStream()
    finalized = asyncio.Event()

    async def agent_events() -> AsyncIterator[Any]:
        try:
            yield RunContentEvent(event=RunEvent.run_content.value, content="working")
            yield RunCompletedEvent()
        finally:
            finalized.set()

    source = async_stream_agno_response_as_agui_events(
        agent_events(), thread_id="t", run_id="r", a2ui_render_stream=render_stream
    )

    async for event in source:
        if event.type == "TEXT_MESSAGE_CONTENT":
            break

    await source.aclose()

    assert finalized.is_set()


@pytest.mark.asyncio
async def test_fragments_are_flushed_when_the_run_fails():
    """A failing run does not take the surface it already drew with it.

    The run pushes its last fragment once the earlier one has reached the
    client, so the fragment is buffered at the moment the failure surfaces.
    """
    render_stream = A2UIRenderStream()
    first_fragment_arrived = asyncio.Event()

    async def agent_events() -> AsyncIterator[Any]:
        render_stream.push({"kind": "start", "tool_call_id": "inner"})
        # Bounded for the same reason as the gate above.
        await asyncio.wait_for(first_fragment_arrived.wait(), 10)
        render_stream.push({"kind": "args", "tool_call_id": "inner", "delta": '{"partial"'})
        raise RuntimeError("the run failed")
        yield RunCompletedEvent()  # pragma: no cover

    collected: List[Any] = []
    source = async_stream_agno_response_as_agui_events(
        agent_events(), thread_id="t", run_id="r", a2ui_render_stream=render_stream
    )

    with pytest.raises(RuntimeError, match="the run failed"):
        async for event in source:
            collected.append(event)
            if event.type == "TOOL_CALL_START":
                first_fragment_arrived.set()
                # Hand the loop back so the run pushes its last fragment and fails.
                await asyncio.sleep(0)

    assert [event.type for event in collected] == ["TOOL_CALL_START", "TOOL_CALL_ARGS"]


# =============================================================================
# Over the wire, while the surface is still being generated
# =============================================================================


def _chunk(delta: Dict[str, Any]) -> Any:
    from openai.types.chat import ChatCompletionChunk

    return ChatCompletionChunk.model_validate(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }
    )


def _tool_call_frame(name: Optional[str], arguments: str, call_id: Optional[str] = None) -> Dict[str, Any]:
    function: Dict[str, Any] = {"arguments": arguments}
    if name is not None:
        function["name"] = name
    frame: Dict[str, Any] = {"index": 0, "function": function}
    if call_id is not None:
        frame["id"] = call_id
        frame["type"] = "function"
    return {"tool_calls": [frame]}


async def post_agui(app: Any, body: Dict[str, Any], on_event: Any) -> Any:
    """POST an AG-UI request and hand each event over as the server sends it.

    The app is driven directly rather than through an HTTP client, because
    httpx's ASGI transport runs the whole app before returning a response and
    would hide the very thing under test.

    A run reports its own failure in band, so the status code says only that
    the response started. That check lives here rather than in each caller,
    where it can be forgotten.
    """
    payload = json.dumps(body).encode()
    request_sent = False
    never = asyncio.Event()

    async def receive() -> Dict[str, Any]:
        nonlocal request_sent
        if request_sent:
            # The response watches this for a client disconnect and abandons the
            # stream the moment one arrives, so stay silent instead.
            await never.wait()
        request_sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    received: List[Dict[str, Any]] = []
    status: Dict[str, Any] = {}
    buffered = b""

    async def send(message: Dict[str, Any]) -> None:
        nonlocal buffered
        if message["type"] == "http.response.start":
            status["code"] = message["status"]
            return
        if message["type"] != "http.response.body":
            return
        buffered += message.get("body", b"")
        while b"\n\n" in buffered:
            frame, buffered = buffered.split(b"\n\n", 1)
            for line in frame.decode().split("\n"):
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    received.append(event)
                    on_event(event)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/agui",
            "raw_path": b"/agui",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"test"), (b"content-type", b"application/json")],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
        },
        receive,
        send,
    )

    errors = [event for event in received if event.get("type") == "RUN_ERROR"]
    assert not errors, f"the run failed in band: {errors}"
    return status.get("code"), received


@pytest.mark.asyncio
async def test_fragments_reach_the_client_before_generation_finishes():
    """The regression net for progressive painting.

    The render subagent stops after its first fragment and waits for the test to
    confirm it arrived. If fragments were held back until the generation tool
    returned, nothing would ever confirm it and the wait would time out.
    """
    pytest.importorskip("openai")
    from agno.models.openai import OpenAIChat

    first_fragment_arrived = asyncio.Event()
    fragments = ['{"surfaceId": "sales", ', '"components": ', json.dumps(COMPONENTS), "}"]
    turns = {"n": 0}

    class PlannerModel(OpenAIChat):
        async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:  # type: ignore[override]
            turns["n"] += 1
            if turns["n"] == 1:
                yield self._parse_provider_response_delta(
                    _chunk(_tool_call_frame(GENERATE_A2UI_TOOL_NAME, "{}", call_id="outer"))
                )
            elif turns["n"] == 2:
                yield self._parse_provider_response_delta(
                    _chunk(_tool_call_frame(RENDER_A2UI_TOOL_NAME, "", call_id="inner"))
                )
                for index, fragment in enumerate(fragments):
                    yield self._parse_provider_response_delta(_chunk(_tool_call_frame(None, fragment)))
                    if index == 0:
                        await asyncio.wait_for(first_fragment_arrived.wait(), 10)
            else:
                yield self._parse_provider_response_delta(_chunk({"content": "Rendered."}))

    model = PlannerModel(id="m", api_key="x")
    agent = Agent(
        id="a2ui-agent",
        name="A2UI Agent",
        model=model,
        tools=[get_a2ui_tools({"model": model})],
    )
    app = AgentOS(id="a2ui-os", agents=[agent], interfaces=[AGUI(agent=agent)]).get_app()

    body = {
        "threadId": "thread-1",
        "runId": "run-1",
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": "show me a sales card"}],
        "tools": [],
        "context": [
            {
                "description": A2UI_SCHEMA_CONTEXT_DESCRIPTION,
                "value": json.dumps({"catalogId": CATALOG_ID, "components": [{"name": "Column"}, {"name": "Text"}]}),
            }
        ],
        "forwardedProps": {},
    }

    # The nested call is found by the tool it names, not by the provider's own
    # id for it: every attempt is emitted under an id of its own, because a
    # client buffers argument fragments per id and providers reuse theirs
    # across attempts.
    nested: Dict[str, str] = {}

    def on_event(event: Dict[str, Any]) -> None:
        if event.get("type") == "TOOL_CALL_START" and event.get("toolCallName") == RENDER_A2UI_TOOL_NAME:
            nested["id"] = event["toolCallId"]
        if event.get("type") == "TOOL_CALL_ARGS" and event.get("toolCallId") == nested.get("id"):
            first_fragment_arrived.set()

    status, received = await post_agui(app, body, on_event)

    assert status == 200
    types = [event.get("type") for event in received]
    assert "RUN_ERROR" not in types

    inner_id = nested["id"]
    assert inner_id != "inner"
    inner_args = [
        event for event in received if event.get("type") == "TOOL_CALL_ARGS" and event.get("toolCallId") == inner_id
    ]
    assert len(inner_args) == len(fragments), "the surface must stream in pieces, not arrive whole"

    # The client reads the catalog off the streamed arguments, so the first
    # fragment has to name it.
    streamed = [event["delta"] for event in inner_args]
    assert f'"catalogId": "{CATALOG_ID}"' in streamed[0]
    assert streamed[0].startswith("{")

    # Named once here because this run renders once. The ids belong to the
    # attempt rather than to the run, so a run that retries names them again
    # on the next attempt; that is pinned by the retry test further down.
    inner_starts = [
        index
        for index, event in enumerate(received)
        if event.get("type") == "TOOL_CALL_START" and event.get("toolCallId") == inner_id
    ]
    assert len(inner_starts) == 1
    assert sum("catalogId" in fragment for fragment in streamed) == 1

    # The nested render call opens, and closes, while the generation call that
    # produced it is still running: that is what progressive painting means,
    # and the outer call's own ordering says nothing about it.
    outer_start = next(
        index
        for index, event in enumerate(received)
        if event.get("type") == "TOOL_CALL_START" and event.get("toolCallId") == "outer"
    )
    inner_end = next(
        index
        for index, event in enumerate(received)
        if event.get("type") == "TOOL_CALL_END" and event.get("toolCallId") == inner_id
    )
    outer_result = next(index for index, event in enumerate(received) if event.get("type") == "TOOL_CALL_RESULT")
    assert outer_start < inner_starts[0] < inner_end < outer_result

    # The committed surface is the model's own, with the catalog stamped on.
    envelope = json.loads(received[outer_result]["content"])
    operations = {key: value for entry in envelope["a2ui_operations"] for key, value in entry.items()}
    assert operations["createSurface"] == {"surfaceId": "sales", "catalogId": CATALOG_ID}
    assert operations["updateComponents"]["components"] == COMPONENTS


class _StubModel:
    """Enough of a model to build a generation tool; never called."""

    assistant_message_role = "assistant"


class _EntityDrivenBy:
    """The least an entity can be: ``run_entity`` only ever calls ``arun``.

    ``tools`` carries a generation tool so the run takes the interleaving path,
    which isolates the router's own drive site from the plain one above.
    """

    def __init__(self, stream: Any, tools: Optional[List[Any]] = None) -> None:
        self._stream = stream
        self.tools = tools

    def arun(self, **kwargs: Any) -> Any:
        return self._stream


def _run_input() -> Any:
    from ag_ui.core import RunAgentInput

    return RunAgentInput.model_validate(
        {
            "threadId": "thread-1",
            "runId": "run-1",
            "state": None,
            "messages": [{"id": "m1", "role": "user", "content": "show me a card"}],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
    )


# =============================================================================
# Closing what this package drives
# =============================================================================


class FinalizationProbe:
    """An agent stream that records whether whoever drove it closed it.

    Deliberately not an async generator: one left unreferenced is finalized by
    the event loop's own hooks, which would make a source nobody closed
    indistinguishable from a closed one. This object stays referenced by the
    test for as long as the assertion needs it, and records only a close it was
    actually asked for.
    """

    def __init__(self, chunks: List[Any], on_close: Optional[Any] = None) -> None:
        self._chunks = list(chunks)
        self._on_close = on_close
        self.closed = False

    def __aiter__(self) -> "FinalizationProbe":
        return self

    async def __anext__(self) -> Any:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def aclose(self) -> None:
        self.closed = True
        if self._on_close is not None:
            self._on_close()


def two_events() -> List[Any]:
    return [RunContentEvent(event=RunEvent.run_content.value, content="working"), RunCompletedEvent()]


@pytest.mark.asyncio
async def test_the_interleaving_path_closes_the_agent_stream_it_drove():
    """The run's own cleanup runs only if whoever drove it closes it.

    Iterating a stream never closes it, so a run left suspended is a run that
    never finalized: a cancelled run goes unpersisted and whatever it held open
    stays open.
    """
    probe = FinalizationProbe(two_events())

    await _collect(
        async_stream_agno_response_as_agui_events(
            probe, thread_id="t", run_id="r", a2ui_render_stream=A2UIRenderStream()
        )
    )

    assert probe.closed


@pytest.mark.asyncio
async def test_the_plain_path_closes_the_agent_stream_it_drove():
    """The same, on the path a run without generation takes.

    That is every ordinary AG-UI run, and it is the level whose own comment
    promises the finalization.
    """
    probe = FinalizationProbe(two_events())

    await _collect(async_stream_agno_response_as_agui_events(probe, thread_id="t", run_id="r"))

    assert probe.closed


@pytest.mark.asyncio
async def test_a_client_leaving_closes_the_stream_the_router_drove():
    """The outermost drive site, and the only one a real client reaches.

    A client that goes away mid-run leaves the router's own generator to be
    closed, and nothing passes that close on to the mapper, so neither the
    mapper's cleanup nor the run's happens at all.
    """
    probe = FinalizationProbe(two_events())
    entity = _EntityDrivenBy(probe, tools=[get_a2ui_tools({"model": _StubModel()})])
    stream = run_entity(entity, _run_input())  # type: ignore[arg-type]

    async for event in stream:
        if event.type == "TEXT_MESSAGE_CONTENT":
            break

    await stream.aclose()

    # Asserted with nothing awaited in between: an unreferenced generator is
    # finalized by the loop, and that would answer the question for us.
    assert probe.closed


@pytest.mark.asyncio
async def test_a_fragment_pushed_while_the_agent_stream_closes_is_not_lost():
    """The last place a fragment can arrive from.

    A source with cleanup of its own can push while it is being closed, which
    is after the merge loop has already broken out. That is the only fragment
    the drain past the loop can ever see.
    """
    render_stream = A2UIRenderStream()
    probe = FinalizationProbe(
        [RunCompletedEvent()],
        on_close=lambda: render_stream.push({"kind": "start", "tool_call_id": "late"}),
    )

    events = await _collect(
        async_stream_agno_response_as_agui_events(probe, thread_id="t", run_id="r", a2ui_render_stream=render_stream)
    )

    types = [event.type for event in events]
    assert "TOOL_CALL_START" in types
    assert types.index("TOOL_CALL_START") < types.index("RUN_FINISHED")


# =============================================================================
# Span lifecycle of the nested render call
# =============================================================================


def test_a_retry_paints_under_an_id_of_its_own():
    """Each attempt mints its own wire id, so a retry never reopens a spent one.

    The id is what a client buffers a surface under, which is why the identity
    type owns it rather than the provider, whose call ids repeat across
    attempts. Both spans are opened once and closed once.
    """
    state = StreamState(thread_id="t", run_id="r")

    attempts = []
    for call_id in (A2UIRenderAttempt.new().call_id, A2UIRenderAttempt.new().call_id):
        collected = []
        collected.extend(on_a2ui_render_stream({"kind": "start", "tool_call_id": call_id}, state))
        collected.extend(on_a2ui_render_stream({"kind": "args", "tool_call_id": call_id, "delta": '{"bad"'}, state))
        collected.extend(on_a2ui_render_stream({"kind": "end", "tool_call_id": call_id}, state))
        attempts.append([event.type for event in collected])

    assert attempts == [["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END"]] * 2
    assert state.active_tool_call_ids == set()
    assert len(state.ended_tool_call_ids) == 2


def test_the_nested_call_is_parented_to_the_message_the_generation_call_hangs_off():
    """The render call belongs under the generation call that produced it.

    Both hang off the same assistant message, which is the grouping a client
    uses to show the surface as part of that turn rather than a turn of its own.
    """
    state = StreamState(thread_id="t", run_id="r")
    state.open_text_message()
    parent = state.text_message_id

    events = on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)

    start = next(event for event in events if event.type == "TOOL_CALL_START")
    assert start.parent_message_id == parent


def test_a_later_nested_call_still_parents_to_the_generation_call_s_message():
    """The parent is recorded when the first nested call opens, not looked up.

    The run goes on producing messages after the surface starts, and the id of
    the message that is merely most recent is not the one the generation call
    hangs off. Without the record the parent silently follows the newest
    message, which regroups the surface under a turn that did not produce it.
    """
    state = StreamState(thread_id="t", run_id="r")
    state.open_text_message()
    generation_message = state.text_message_id

    on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)
    on_a2ui_render_stream({"kind": "end", "tool_call_id": "inner"}, state)
    # A later message of the run's own, opened and closed.
    state.open_text_message()
    state.close_text_message()
    assert state.text_message_id != generation_message

    events = on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner-2"}, state)

    assert events[0].parent_message_id == generation_message


def test_the_nested_call_reuses_the_parent_the_generation_call_was_given():
    """The generation call's own parent is a message that is already closed."""
    state = StreamState(thread_id="t", run_id="r")
    state.set_pending_tool_calls_parent_id("outer-parent")

    events = on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)

    assert events[0].parent_message_id == "outer-parent"


def test_a_nested_call_with_no_parent_invents_no_message():
    """Nothing is fabricated when no parent is known: the field is optional, and
    an assistant message the run never produced is worse than an absent id."""
    state = StreamState(thread_id="t", run_id="r")

    events = on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)

    assert [event.type for event in events] == ["TOOL_CALL_START"]
    assert events[0].parent_message_id is None


def test_the_fallback_tool_name_is_the_toolkits_own():
    """A fragment carrying no name still has to be named what the toolkit calls
    the render tool, and this pins the literal to it."""
    assert RENDER_A2UI_TOOL_NAME_FALLBACK == RENDER_A2UI_TOOL_NAME

    state = StreamState(thread_id="t", run_id="r")
    events = on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)

    assert events[0].tool_call_name == RENDER_A2UI_TOOL_NAME


def test_a_failed_run_closes_spans_through_the_public_surface():
    """The router has to close what a failed run left open, so closing is part
    of this module's interface rather than a private helper reached across it."""
    from agno.os.interfaces.agui import router as agui_router

    assert agui_router.close_open_spans is close_open_spans


# =============================================================================
# The two span tallies, side by side
# =============================================================================


def a_render_call_started_again_under_a_spent_id(state: StreamState) -> List[Any]:
    """A render call, ended, then a start under the same id, which is refused."""
    return (
        on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)
        + on_a2ui_render_stream({"kind": "end", "tool_call_id": "inner"}, state)
        + on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)
    )


def a_reasoning_session_left_open(state: StreamState) -> List[Any]:
    return process_event(ReasoningStartedEvent(event=RunEvent.reasoning_started.value), state)


def a_render_call_inside_the_generation_call(state: StreamState) -> List[Any]:
    return process_event(
        ToolCallStartedEvent(
            event=RunEvent.tool_call_started.value,
            tool=ToolExecution(tool_call_id="outer", tool_name=GENERATE_A2UI_TOOL_NAME, tool_args={}),
        ),
        state,
    ) + on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)


def a_text_message_reopened_after_a_render_call(state: StreamState) -> List[Any]:
    return (
        process_event(RunContentEvent(event=RunEvent.run_content.value, content="working"), state)
        + on_a2ui_render_stream({"kind": "start", "tool_call_id": "inner"}, state)
        + process_event(RunContentEvent(event=RunEvent.run_content.value, content="more"), state)
    )


SPAN_SEQUENCES: Dict[str, Any] = {
    "a-render-call-started-again-under-a-spent-id": a_render_call_started_again_under_a_spent_id,
    "a-reasoning-session-left-open": a_reasoning_session_left_open,
    "a-render-call-inside-the-generation-call": a_render_call_inside_the_generation_call,
    "a-text-message-reopened-after-a-render-call": a_text_message_reopened_after_a_render_call,
}


def closing_shape(state: StreamState) -> List[Any]:
    """What closing this tally's open spans would emit, by type and subject."""
    return [
        (
            type(event).__name__,
            getattr(event, "tool_call_id", None) or getattr(event, "message_id", None),
        )
        for event in close_open_spans(state)
    ]


@pytest.mark.parametrize("sequence", list(SPAN_SEQUENCES), ids=list(SPAN_SEQUENCES))
def test_both_span_tallies_would_close_the_same_spans(sequence):
    """There is one event-to-span transition function, and there are two.

    The mapper keeps a tally for the events it emits, and the router keeps a
    second one because the mapper's goes out of scope when a run raises. Only
    the router's runs on the failure path, so a rule added to the mapper and
    not mirrored costs the client a span that stays open past RUN_ERROR, which
    is terminal.
    """
    drive = SPAN_SEQUENCES[sequence]

    mapper_tally = StreamState(thread_id="t", run_id="r")
    emitted = drive(mapper_tally)

    router_tally = StreamState()
    for event in emitted:
        _track_spans(event, router_tally)

    assert closing_shape(router_tally) == closing_shape(mapper_tally)


# =============================================================================
# A retried surface, over the channel
# =============================================================================


class _ScriptedRenderModel:
    """A model whose render turns are scripted, streamed as a provider streams.

    One entry per subagent turn, each a dict of render arguments. The call id is
    reused across turns, which is what a provider that numbers its calls per
    turn does, and what makes the second attempt indistinguishable from the
    first to anything keying on the id alone.
    """

    assistant_message_role = "assistant"

    def __init__(self, script: List[Dict[str, Any]]) -> None:
        self.script = list(script)
        self.calls: List[str] = []

    async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[Any]:
        self.calls.append(kwargs["messages"][0].content)
        payload = json.dumps(self.script.pop(0))
        yield _delta(name=RENDER_A2UI_TOOL_NAME, arguments="", call_id="inner")
        for start in range(0, len(payload), 24):
            yield _delta(arguments=payload[start : start + 24])


def _delta(name: Optional[str] = None, arguments: str = "", call_id: Optional[str] = None, index: int = 0) -> Any:
    function = type("Fn", (), {"name": name, "arguments": arguments})()
    entry = type("Entry", (), {"function": function, "index": index, "id": call_id})()
    return type("Delta", (), {"tool_calls": [entry]})()


INVALID_COMPONENTS = [{"id": "orphan", "component": "Text", "text": "nowhere"}]


@pytest.mark.asyncio
async def test_a_rejected_surface_is_retried_as_a_second_call_on_the_channel():
    """Recovery and interleaving together, which is the combination that hides
    an unbalanced span: each attempt owes the client a call of its own, and the
    run goes on emitting its own events afterwards, so an end left off the
    first attempt shows up as a tool call still open under the next message.
    """
    model = _ScriptedRenderModel(
        [
            {"surfaceId": "sales", "components": INVALID_COMPONENTS},
            {"surfaceId": "sales", "components": COMPONENTS},
        ]
    )
    tool = get_a2ui_tools({"model": model, "default_catalog_id": CATALOG_ID})
    render_stream = A2UIRenderStream()
    run = A2UIRun(render_stream=render_stream)
    committed: List[Dict[str, Any]] = []

    async def agent_events() -> AsyncIterator[Any]:
        token = current_a2ui_run.set(run)
        try:
            committed.append(json.loads(await tool.entrypoint(run_context=None)))
        finally:
            current_a2ui_run.reset(token)
        yield RunContentEvent(event=RunEvent.run_content.value, content="Rendered.")
        yield RunCompletedEvent()

    events = await _collect(
        async_stream_agno_response_as_agui_events(
            agent_events(), thread_id="t", run_id="r", a2ui_render_stream=render_stream
        )
    )

    types = [event.type for event in events]
    assert len(model.calls) == 2
    # Two calls, each opened and ended, and both finished before the run's own
    # next message: no span outlives the attempt that opened it.
    assert types.count("TOOL_CALL_START") == 2
    assert types.count("TOOL_CALL_END") == 2
    assert [kind for kind in types if kind != "TOOL_CALL_ARGS"] == [
        "TOOL_CALL_START",
        "TOOL_CALL_END",
        "TOOL_CALL_START",
        "TOOL_CALL_END",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]

    # Both attempts streamed to the client, each carrying the catalog once: the
    # client paints from the arguments alone and has no other source for it.
    streamed = [event.delta for event in events if event.type == "TOOL_CALL_ARGS"]
    assert sum("catalogId" in fragment for fragment in streamed) == 2

    # Only the surface that passed validation is committed as the result.
    operations = {key: value for entry in committed[0]["a2ui_operations"] for key, value in entry.items()}
    assert operations["updateComponents"]["components"] == COMPONENTS
    assert operations["createSurface"] == {"surfaceId": "sales", "catalogId": CATALOG_ID}


# =============================================================================
# The identity of one render attempt, painted against committed
# =============================================================================


class _TurnScriptedModel:
    """A model whose whole turns are scripted, streamed as a provider streams.

    One entry per subagent turn, each already a list of frames, so a turn can
    carry more than one render call.
    """

    assistant_message_role = "assistant"

    def __init__(self, turns: List[List[Any]]) -> None:
        self.turns = list(turns)
        self.calls: List[str] = []

    async def aprocess_response_stream(self, **kwargs: Any) -> AsyncIterator[Any]:
        self.calls.append(kwargs["messages"][0].content)
        for frame in self.turns.pop(0):
            yield frame


def render_call_frames(payload: Dict[str, Any], call_id: str, index: int = 0) -> List[Any]:
    """One render call, streamed the way an OpenAI-compatible provider streams it."""
    body = json.dumps(payload)
    frames = [_delta(name=RENDER_A2UI_TOOL_NAME, arguments="", call_id=call_id, index=index)]
    for start in range(0, len(body), 24):
        frames.append(_delta(arguments=body[start : start + 24], index=index))
    return frames


def prior_surface_message(surface_id: str, catalog_id: str = CATALOG_ID) -> Any:
    """A tool result carrying an already-rendered surface, as history replays it."""
    envelope = json.dumps(
        {
            "a2ui_operations": [
                {"version": "v0.9", "createSurface": {"surfaceId": surface_id, "catalogId": catalog_id}},
                {"version": "v0.9", "updateComponents": {"surfaceId": surface_id, "components": COMPONENTS}},
            ]
        }
    )
    return type("Msg", (), {"role": "tool", "content": envelope, "tool_calls": None})()


async def generate_over_the_channel(tool: Any, run: Any, **kwargs: Any) -> Any:
    """Run one generation with a real channel attached.

    Returns the AG-UI events the client would have received and the envelope
    the run committed, which is the pair the identity of an attempt has to
    agree across.
    """
    committed: Dict[str, Any] = {}

    async def agent_events() -> AsyncIterator[Any]:
        token = current_a2ui_run.set(run)
        try:
            committed["envelope"] = json.loads(await tool.entrypoint(run_context=None, **kwargs))
        finally:
            current_a2ui_run.reset(token)
        yield RunCompletedEvent()

    events = await _collect(
        async_stream_agno_response_as_agui_events(
            agent_events(), thread_id="t", run_id="r", a2ui_render_stream=run.render_stream
        )
    )
    return events, committed["envelope"]


def painted_attempts(events: List[Any]) -> List[Dict[str, Any]]:
    """Each render attempt as a progressively painting client reassembles it.

    Buffered per wire call id, because that is the key the AG-UI reducer
    buffers on: two attempts sharing an id are one buffer holding both sets of
    arguments, which parses as nothing and paints nothing.
    """
    order: List[str] = []
    buffers: Dict[str, str] = {}
    starts: Dict[str, int] = {}
    for event in events:
        if event.type == "TOOL_CALL_START":
            if event.tool_call_id not in order:
                order.append(event.tool_call_id)
                buffers[event.tool_call_id] = ""
            starts[event.tool_call_id] = starts.get(event.tool_call_id, 0) + 1
        elif event.type == "TOOL_CALL_ARGS":
            buffers[event.tool_call_id] += event.delta
    return [{"call_id": call_id, "starts": starts[call_id], "args": buffers[call_id]} for call_id in order]


def committed_operations(envelope: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for entry in envelope["a2ui_operations"] for key, value in entry.items()}


def client_catalog_state(catalog_id: str = CATALOG_ID) -> Dict[str, Any]:
    """Run state carrying the catalog the client registered, as the router builds it.

    Supplied through state rather than configured on the tool, because that is
    where a served run's catalog comes from and it is the only arrangement in
    which the precedence between the two is load-bearing.
    """
    return {
        "ag-ui": {
            "context": [],
            "a2ui_schema": json.dumps({"catalogId": catalog_id, "components": [{"name": "Column"}, {"name": "Text"}]}),
        }
    }


def a_create_case() -> Any:
    model = _TurnScriptedModel([render_call_frames({"surfaceId": "sales", "components": COMPONENTS}, "inner")])
    tool = get_a2ui_tools({"model": model})
    run = A2UIRun(render_stream=A2UIRenderStream(), state=client_catalog_state())
    return tool, run, {}, "sales", CATALOG_ID, 1


def an_update_case() -> Any:
    """The model names a surface of its own while editing another.

    ``target_surface_id`` decides which surface is edited, so the id the model
    happened to write is not the one the operation carries.
    """
    model = _TurnScriptedModel([render_call_frames({"surfaceId": "ignored", "components": COMPONENTS}, "inner")])
    tool = get_a2ui_tools({"model": model})
    run = A2UIRun(
        render_stream=A2UIRenderStream(),
        state=client_catalog_state(),
        messages=[prior_surface_message("sales")],
    )
    return tool, run, {"intent": "update", "target_surface_id": "sales"}, "sales", CATALOG_ID, 1


def a_prior_surface_in_another_catalog_case() -> Any:
    """The surface being edited was registered in a catalog of its own.

    A client resolves an update's components against the catalog the surface
    was created under, so the fragments have to name that one and not the
    catalog this run happens to resolve.
    """
    model = _TurnScriptedModel([render_call_frames({"surfaceId": "ignored", "components": COMPONENTS}, "inner")])
    tool = get_a2ui_tools({"model": model})
    run = A2UIRun(
        render_stream=A2UIRenderStream(),
        state=client_catalog_state(),
        messages=[prior_surface_message("sales", catalog_id="a-catalog-of-its-own")],
    )
    return tool, run, {"intent": "update", "target_surface_id": "sales"}, "sales", "a-catalog-of-its-own", 1


def a_retry_then_heal_case() -> Any:
    """A rejected attempt and the one that healed it, under one provider id.

    Both are painted, because painting an attempt while it is written is the
    feature and what keeps the rejected one off the screen is the client's own
    paint gate. What the two attempts may not share is a wire id.
    """
    model = _TurnScriptedModel(
        [
            render_call_frames({"surfaceId": "sales", "components": INVALID_COMPONENTS}, "inner"),
            render_call_frames({"surfaceId": "sales", "components": COMPONENTS}, "inner"),
        ]
    )
    tool = get_a2ui_tools({"model": model})
    run = A2UIRun(render_stream=A2UIRenderStream(), state=client_catalog_state())
    return tool, run, {}, "sales", CATALOG_ID, 2


def two_render_calls_in_one_turn_case() -> Any:
    """One turn, two render calls, and the turn keeps the first.

    The client has painted the first by the time the second arrives and only
    one surface is committed, so committing the second would leave the first
    on screen with nothing behind it. The second is refused instead, which is
    also the only order in which the painted surface and the committed one can
    agree without unpainting anything.
    """
    model = _TurnScriptedModel(
        [
            render_call_frames({"surfaceId": "first", "components": COMPONENTS}, "c1", index=0)
            + render_call_frames({"surfaceId": "second", "components": COMPONENTS}, "c2", index=1)
        ]
    )
    tool = get_a2ui_tools({"model": model})
    run = A2UIRun(render_stream=A2UIRenderStream(), state=client_catalog_state())
    return tool, run, {}, "first", CATALOG_ID, 1


IDENTITY_CASES: Dict[str, Any] = {
    "create": a_create_case,
    "update-with-a-prior-surface": an_update_case,
    "the-prior-surface-is-in-another-catalog": a_prior_surface_in_another_catalog_case,
    "retry-then-heal": a_retry_then_heal_case,
    "two-render-calls-in-one-turn": two_render_calls_in_one_turn_case,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(IDENTITY_CASES), ids=list(IDENTITY_CASES))
async def test_the_surface_painted_is_the_surface_committed(case):
    """The identity of a render attempt, asserted across the two sites that choose it.

    Wire call id, surface id and catalog id are each computed once where the
    fragments are emitted and again where the envelope is built, from different
    precedence chains, and nothing requires the two to agree. Every
    disagreement so far has looked the same from the server: the run logs
    success and the client paints nothing, or paints a surface it then cannot
    reconcile with the one it is told to keep.

    A generation paints every attempt it makes, which is the whole point of
    streaming one, and what keeps a rejected attempt off the screen is the
    client's own paint gate. So the surface the run commits is the last one
    painted, and the agreement asserted here is with that attempt: each has a
    wire id of its own, opened once, because two attempts sharing one leave
    the client holding both sets of arguments in a single buffer, which parses
    as neither.
    """
    tool, run, kwargs, surface_id, catalog_id, painted_count = IDENTITY_CASES[case]()

    events, envelope = await generate_over_the_channel(tool, run, **kwargs)
    attempts = painted_attempts(events)

    # One wire id per attempt, opened once.
    assert [attempt["starts"] for attempt in attempts] == [1] * len(attempts)
    assert len({attempt["call_id"] for attempt in attempts}) == len(attempts)

    # The attempt the envelope commits is the last one painted, and it names
    # the surface and catalog the envelope does.
    assert len(attempts) == painted_count
    painted = json.loads(attempts[-1]["args"])
    assert (painted.get("surfaceId"), painted.get("catalogId")) == (surface_id, catalog_id)

    operations = committed_operations(envelope)
    created = operations.get("createSurface") or {}
    updated = operations.get("updateComponents") or {}
    assert (created.get("surfaceId") or updated.get("surfaceId")) == surface_id
    if created:
        assert created["catalogId"] == catalog_id
