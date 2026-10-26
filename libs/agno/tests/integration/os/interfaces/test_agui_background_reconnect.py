"""A real disconnect and reconnect against a live AG-UI server.

Everything here goes over a socket: a uvicorn process serves AgentOS, an HTTP
client reads part of a background run's event stream and then drops the
connection mid-run, and a second request picks the run up from the cursor it
last saw. The point is to prove that the run keeps going with nobody attached
and that the two connections together see exactly the stream one uninterrupted
connection would have seen.
"""

import asyncio
import json
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

import httpx
import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

import uvicorn

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os.app import AgentOS
from agno.os.event_streams import get_event_stream, set_event_stream
from agno.os.event_streams.in_memory import InMemoryEventStream
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.agui import background as background_module
from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.base import RunStatus
from agno.team import Team

CHUNKS = ["The ", "quick ", "brown ", "fox ", "jumps ", "over ", "the ", "lazy ", "dog."]
# Long enough that a client can disconnect part-way through with the run still
# producing, short enough to keep the test quick.
CHUNK_DELAY_SECONDS = 0.12

SERVER_START_TIMEOUT_SECONDS = 30.0
SERVER_START_POLL_SECONDS = 0.05
SERVER_STOP_TIMEOUT_SECONDS = 10.0

# Long enough for the whole answer to dribble out on a loaded machine, short
# enough that a run which never ends fails the test rather than hanging it.
RUN_COMPLETION_TIMEOUT_SECONDS = 60.0
STATUS_POLL_SECONDS = 0.02

TERMINAL_STATUSES = (RunStatus.completed, RunStatus.error, RunStatus.cancelled, RunStatus.paused)


class SlowModel(Model):
    """An offline model that dribbles out a fixed answer."""

    def __init__(self, chunks: List[str]):
        super().__init__(id="slow-test-model", name="slow-test-model", provider="test")
        self.instructions = None
        self._chunks = chunks

    def _response(self, text: str) -> ModelResponse:
        return ModelResponse(content=text, role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_system_message_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def aget_instructions_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def aget_system_message_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    def parse_args(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response("".join(self._chunks))

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response("".join(self._chunks))

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        for chunk in self._chunks:
            yield self._response(chunk)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        for chunk in self._chunks:
            await asyncio.sleep(CHUNK_DELAY_SECONDS)
            yield self._response(chunk)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return self._response("")

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._response("")


@pytest.fixture
def isolated_run_state() -> Iterator[None]:
    """Empty the buffered events and the started-run record between tests.

    Both are process globals that the server thread reads, so a run id one
    test used is otherwise still answerable in the next. Hand-picking a
    distinct id per test hides that rather than fixing it, and hides it least
    reliably in exactly the tests that name an id the server never saw.

    The drain task set is deliberately left alone: it holds the only strong
    reference keeping a live background run from being collected.
    """
    original = get_event_stream()
    set_event_stream(
        InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager()),
    )
    background_module._STARTED_RUNS.clear()
    background_module._STARTING_RUNS.clear()
    try:
        yield
    finally:
        set_event_stream(original)
        background_module._STARTED_RUNS.clear()
        background_module._STARTING_RUNS.clear()


@pytest.fixture
def agui_server(isolated_run_state: None) -> Iterator[str]:
    """A uvicorn server exposing an agent and a team over AG-UI.

    ``isolated_run_state`` is required rather than merely useful, and the
    order is the whole point: the server thread reads the event stream out of
    a process global, so the fresh one has to be installed before the thread
    starts and restored only after it has stopped. Requesting it here is what
    pins it either side of this fixture. A test that took the two
    independently could be handed them the other way round, and would then run
    against whichever stream the previous test left behind.
    """
    with tempfile.TemporaryDirectory() as directory:
        db = SqliteDb(db_file=str(Path(directory) / "agui-background.db"))
        agent = Agent(name="bg-agent", id="bg-agent", model=SlowModel(CHUNKS), db=db)
        member = Agent(name="member", id="member", model=SlowModel(CHUNKS), db=db)
        team = Team(name="bg-team", id="bg-team", members=[member], model=SlowModel(CHUNKS), db=db)

        agent_os = AgentOS(
            agents=[agent, member],
            teams=[team],
            interfaces=[AGUI(agent=agent, prefix="/agent"), AGUI(team=team, prefix="/team")],
        )

        # The listening socket is bound here and handed to uvicorn still open,
        # so nothing else on the machine can claim the port in between.
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])

        config = uvicorn.Config(agent_os.get_app(), host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + SERVER_START_TIMEOUT_SECONDS
            while not server.started:
                if not thread.is_alive():
                    raise RuntimeError("AG-UI test server thread exited before the server started")
                if time.monotonic() > deadline:
                    raise RuntimeError(f"AG-UI test server did not start within {SERVER_START_TIMEOUT_SECONDS}s")
                time.sleep(SERVER_START_POLL_SECONDS)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=SERVER_STOP_TIMEOUT_SECONDS)
            listener.close()


def request_body(
    *,
    thread_id: str,
    run_id: str,
    cursor: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    background: Dict[str, Any] = {"enabled": True}
    if cursor is not None:
        background["lastEventIndex"] = cursor[0]
        background["lastSubIndex"] = cursor[1]
    return {
        "threadId": thread_id,
        "runId": run_id,
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": "describe a fox"}],
        "tools": [],
        "context": [],
        "forwardedProps": {"agnoBackground": background},
    }


def cursor_of(event: Dict[str, Any]) -> Tuple[int, int]:
    marker = event["metadata"]["agnoBackground"]
    return marker["eventIndex"], marker["subIndex"]


def content_of(events: List[Dict[str, Any]]) -> List[str]:
    """The answer text deltas, in the order they arrived."""
    return [event["delta"] for event in events if event["type"] == "TEXT_MESSAGE_CONTENT"]


def identity(event: Dict[str, Any]) -> Dict[str, Any]:
    """The parts of an event that must be identical across a reconnect.

    Every field the server sends is derived from the buffered Agno event, down
    to the raw payload a RAW event carries, so the whole event is compared. The
    exception is the protocol's optional timestamp: it is wall clock, so a leg
    that carried one could never replay equal.
    """
    return {key: value for key, value in event.items() if key != "timestamp"}


async def wait_for_terminal_status(run_id: str) -> RunStatus:
    """Wait for the run to end, and report how.

    The status lives in the process-global event stream the server thread
    writes to, so this reads the very record the server keeps rather than
    inferring from a sleep that a run had time to finish.
    """
    stream = get_event_stream()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + RUN_COMPLETION_TIMEOUT_SECONDS
    while True:
        status = await stream.get_run_status(run_id)
        if status in TERMINAL_STATUSES:
            return status
        assert loop.time() < deadline, f"run {run_id} never reached a terminal status (last seen {status})"
        await asyncio.sleep(STATUS_POLL_SECONDS)


async def read_events(
    client: httpx.AsyncClient,
    url: str,
    body: Dict[str, Any],
    *,
    stop_after_content: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Read AG-UI events, optionally dropping the connection part-way through.

    Stopping is counted in answer text rather than in events, so a leg that is
    cut short always holds content a later leg must not repeat.
    """
    events: List[Dict[str, Any]] = []
    content_seen = 0
    async with client.stream("POST", url, json=body) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            events.append(event)
            if event["type"] == "TEXT_MESSAGE_CONTENT":
                content_seen += 1
                if stop_after_content is not None and content_seen >= stop_after_content:
                    break
    return events


@pytest.mark.asyncio
@pytest.mark.parametrize("entity", ["agent", "team"])
async def test_disconnect_and_reconnect_delivers_every_event_once(agui_server: str, entity: str):
    url = f"{agui_server}/{entity}/agui"
    thread_id = f"{entity}-interrupted"
    run_id = f"{entity}-interrupted-run"

    async with httpx.AsyncClient(timeout=60.0) as client:
        first_leg = await read_events(
            client, url, request_body(thread_id=thread_id, run_id=run_id), stop_after_content=3
        )
        assert content_of(first_leg) == CHUNKS[:3]

        # Nothing is attached for a moment: the run has to survive on its own.
        await asyncio.sleep(CHUNK_DELAY_SECONDS * 3)

        resumed = await read_events(
            client, url, request_body(thread_id=thread_id, run_id=run_id, cursor=cursor_of(first_leg[-1]))
        )
        # The whole run from the top, which is what an uninterrupted client
        # would have received.
        whole_run = await read_events(client, url, request_body(thread_id=thread_id, run_id=run_id))

    assert resumed[-1]["type"] == "RUN_FINISHED"
    assert content_of(resumed) == CHUNKS[3:]
    assert [identity(event) for event in first_leg + resumed] == [identity(event) for event in whole_run]

    cursors = [cursor_of(event) for event in first_leg + resumed]
    assert cursors == sorted(cursors)
    assert len(set(cursors)) == len(cursors)


@pytest.mark.asyncio
@pytest.mark.parametrize("entity", ["agent", "team"])
async def test_run_completes_after_the_client_goes_away(agui_server: str, entity: str):
    """The run reaches its end with nobody attached, and the client picks it up after.

    Waiting on the run's recorded status rather than on a sleep is what tells
    a run that carried on from one that was merely still going when the second
    connection arrived: the run is known to be over before that request goes
    out, so the events it receives can only have been buffered while nothing
    was reading them.
    """
    url = f"{agui_server}/{entity}/agui"
    thread_id = f"{entity}-detached"
    run_id = f"{entity}-detached-run"

    async with httpx.AsyncClient(timeout=60.0) as client:
        first_leg = await read_events(
            client, url, request_body(thread_id=thread_id, run_id=run_id), stop_after_content=2
        )
        assert content_of(first_leg) == CHUNKS[:2]

        assert await wait_for_terminal_status(run_id) == RunStatus.completed

        resumed = await read_events(
            client, url, request_body(thread_id=thread_id, run_id=run_id, cursor=cursor_of(first_leg[-1]))
        )

    assert resumed[-1]["type"] == "RUN_FINISHED"
    # Picking up where the first leg stopped, instead of answering again from
    # the top, is what tells a run that kept going from one that started over.
    assert content_of(resumed) == CHUNKS[2:]
    assert content_of(first_leg + resumed) == CHUNKS


@pytest.mark.asyncio
@pytest.mark.parametrize("entity", ["agent", "team"])
async def test_resuming_from_a_position_already_passed_replays_only_what_follows(agui_server: str, entity: str):
    url = f"{agui_server}/{entity}/agui"
    thread_id = f"{entity}-rewind"
    run_id = f"{entity}-rewind-run"

    async with httpx.AsyncClient(timeout=60.0) as client:
        whole_run = await read_events(client, url, request_body(thread_id=thread_id, run_id=run_id))
        assert whole_run[-1]["type"] == "RUN_FINISHED"

        # A position the finished run went past long ago.
        pivot = [index for index, event in enumerate(whole_run) if event["type"] == "TEXT_MESSAGE_CONTENT"][2]
        rest = await read_events(
            client, url, request_body(thread_id=thread_id, run_id=run_id, cursor=cursor_of(whole_run[pivot]))
        )

    assert content_of(rest) == CHUNKS[3:]
    assert rest[-1]["type"] == "RUN_FINISHED"
    assert [identity(event) for event in whole_run[: pivot + 1] + rest] == [identity(event) for event in whole_run]


@pytest.mark.asyncio
async def test_reconnecting_to_another_threads_run_is_refused(agui_server: str):
    url = f"{agui_server}/agent/agui"
    run_id = "owned-run"

    async with httpx.AsyncClient(timeout=60.0) as client:
        owned = await read_events(client, url, request_body(thread_id="owner", run_id=run_id))
        assert owned[-1]["type"] == "RUN_FINISHED"

        intruder = await read_events(
            client, url, request_body(thread_id="intruder", run_id=run_id, cursor=cursor_of(owned[2]))
        )

    # A lone RUN_ERROR: no RUN_STARTED, so no run began for the intruding
    # thread, and none of the owner's answer was handed over.
    assert [event["type"] for event in intruder] == ["RUN_ERROR"]
    assert intruder[0]["message"] == f"Run {run_id} not found in this session"


@pytest.mark.asyncio
async def test_resuming_a_run_the_server_never_saw_is_refused(agui_server: str):
    url = f"{agui_server}/agent/agui"
    run_id = "never-started-run"

    async with httpx.AsyncClient(timeout=60.0) as client:
        refused = await read_events(client, url, request_body(thread_id="ghost", run_id=run_id, cursor=(4, 0)))
        assert [event["type"] for event in refused] == ["RUN_ERROR"]
        assert refused[0]["message"] == f"Run {run_id} not found in this session"

        # The refusal ran nothing, so the same id is still free to start fresh.
        fresh = await read_events(client, url, request_body(thread_id="ghost", run_id=run_id))

    assert fresh[0]["type"] == "RUN_STARTED"
    assert cursor_of(fresh[0]) == (-1, 0)
    assert content_of(fresh) == CHUNKS
    assert fresh[-1]["type"] == "RUN_FINISHED"


@pytest.mark.asyncio
async def test_foreground_run_carries_no_background_marker(agui_server: str):
    url = f"{agui_server}/agent/agui"
    body = request_body(thread_id="foreground", run_id="foreground-run")
    body["forwardedProps"] = {}
    async with httpx.AsyncClient(timeout=60.0) as client:
        events = await read_events(client, url, body)

    assert events[0]["type"] == "RUN_STARTED"
    assert content_of(events) == CHUNKS
    assert events[-1]["type"] == "RUN_FINISHED"
    assert all("agnoBackground" not in (event.get("metadata") or {}) for event in events)
