import copy
import json
import logging
import sys
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import EventType
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.agent._response import REFUSED_TOOL_CALL_ERROR
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.os.app import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.agui import handlers as agui_handlers
from agno.os.interfaces.agui import state as agui_state
from agno.os.interfaces.agui.handlers import _normalize_event, process_completion, process_event
from agno.os.interfaces.agui.state import StateDeltaUnavailable, StreamState, client_state
from agno.run import RunContext
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunEvent,
    RunOutputEvent,
    RunPausedEvent,
    ToolCallArgsDeltaEvent,
    ToolCallCompletedEvent,
    ToolCallErrorEvent,
    ToolCallStartedEvent,
)
from agno.run.team import TeamRunEvent
from agno.run.team import ToolCallErrorEvent as TeamToolCallErrorEvent
from agno.team import Team
from agno.tools import tool
from agno.utils import log as agno_log


def parse_sse_events(content: str) -> List[Dict[str, Any]]:
    """The events one SSE response carried, refusing any line that is not one.

    A data line that does not decode is a defect these tests exist to catch,
    not noise to skip: read as no event at all it satisfies every assertion
    below about something being absent, so a stream that broke half way
    through would pass a test asking for no RUN_ERROR and no second call.
    """
    events = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        try:
            events.append(json.loads(data_str))
        except json.JSONDecodeError as e:
            raise AssertionError(f"the stream carried a data line that is no event: {data_str!r} ({e})") from None
    return events


def get_event_types(events: List[Dict[str, Any]]) -> List[str]:
    return [e.get("type") for e in events]


def make_request_body(message: str, state: Any = None, thread_id: str = "test-thread") -> Dict[str, Any]:
    return {
        "threadId": thread_id,
        "runId": "test-run",
        "state": state,
        "messages": [{"id": "msg-1", "role": "user", "content": message}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


# =============================================================================
# Agent State Events
# =============================================================================


@pytest.fixture
def test_agent():
    return Agent(name="test-state-agent", instructions="You are a test agent.")


@pytest.fixture
def agent_client(test_agent: Agent):
    agent_os = AgentOS(agents=[test_agent], interfaces=[AGUI(agent=test_agent)])
    app = agent_os.get_app()
    return TestClient(app), test_agent


class TestAgentStateSnapshot:
    def test_initial_snapshot_emitted_when_state_provided(self, agent_client):
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Hello")
            yield RunCompletedEvent(content="", session_state={"counter": 0})

        with patch.object(
            agent,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Hi", state={"counter": 0}))

        assert response.status_code == 200
        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "RUN_STARTED" in types
        assert "STATE_SNAPSHOT" in types

        # Initial snapshot immediately after RUN_STARTED
        run_started_idx = types.index("RUN_STARTED")
        first_snapshot_idx = types.index("STATE_SNAPSHOT")
        assert first_snapshot_idx == run_started_idx + 1

        # Verify snapshot content
        snapshot_event = events[first_snapshot_idx]
        assert _same_state_value(snapshot_event["snapshot"], {"counter": 0}), snapshot_event["snapshot"]

    def test_final_snapshot_emitted_before_run_finished(self, agent_client):
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Done")
            yield RunCompletedEvent(content="", session_state={"counter": 5})

        with patch.object(
            agent,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Test", state={"counter": 0}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # Final snapshot right before RUN_FINISHED
        run_finished_idx = types.index("RUN_FINISHED")
        last_snapshot_idx = len(types) - 1 - types[::-1].index("STATE_SNAPSHOT")
        assert last_snapshot_idx == run_finished_idx - 1

        # Verify final snapshot has updated state
        final_snapshot = events[last_snapshot_idx]
        assert _same_state_value(final_snapshot["snapshot"], {"counter": 5}), final_snapshot["snapshot"]

    def test_no_state_events_when_state_is_none(self, agent_client):
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Hello")
            yield RunCompletedEvent(content="")

        with patch.object(
            agent,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Hi", state=None))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "STATE_SNAPSHOT" not in types
        assert "STATE_DELTA" not in types
        assert "RUN_FINISHED" in types

    def test_no_state_events_when_state_omitted(self, agent_client):
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Hello")
            yield RunCompletedEvent(content="")

        with patch.object(
            agent,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            # No state field at all
            body = {
                "threadId": "test-thread",
                "runId": "test-run",
                "messages": [{"id": "msg-1", "role": "user", "content": "Hi"}],
                "tools": [],
                "context": [],
                "forwardedProps": {},
            }
            response = client.post("/agui", json=body)

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # The run really answered, so what is absent is state and not the run.
        assert "RUN_FINISHED" in types, types
        assert [e["delta"] for e in events if e.get("type") == "TEXT_MESSAGE_CONTENT"] == ["Hello"], types
        assert "STATE_SNAPSHOT" not in types
        assert "STATE_DELTA" not in types

    def test_session_state_passed_to_agent_arun(self, agent_client):
        client, agent = agent_client
        initial_state = {"counter": 10, "items": ["a", "b"]}

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Done")
            yield RunCompletedEvent(content="", session_state=initial_state)

        with patch.object(
            agent,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            client.post("/agui", json=make_request_body("Test", state=initial_state))

        # Verify agent.arun received session_state via run_context
        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        passed = call_kwargs["run_context"].session_state
        assert _same_state_value(passed, initial_state), passed


class TestAgentStateDelta:
    def test_delta_emitted_after_tool_mutation(self, agent_client):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client, agent = agent_client

        # Mutable state that will be modified during stream
        mutable_state = {"counter": 0}

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Calling tool")

            tool_mock = MagicMock()
            tool_mock.tool_call_id = "tc_1"
            tool_mock.tool_name = "increment"
            tool_mock.tool_args = {"amount": 5}

            yield ToolCallStartedEvent(content="", tool=tool_mock)

            # Simulate tool mutating state
            mutable_state["counter"] = 5

            tool_mock.result = "Incremented"
            yield ToolCallCompletedEvent(content="", tool=tool_mock)

            yield RunCompletedEvent(content="", session_state={"counter": 5})

        def mock_validate(state, thread_id):
            if state is not None:
                mutable_state["counter"] = 0
                return mutable_state
            return None

        with (
            patch.object(
                agent,
                "arun",
            ) as mock_arun,
            patch("agno.os.interfaces.agui.router.validate_state", side_effect=mock_validate),
        ):
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Increment", state={"counter": 0}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "STATE_DELTA" in types

        # Delta after TOOL_CALL_RESULT
        delta_idx = types.index("STATE_DELTA")
        result_idx = types.index("TOOL_CALL_RESULT")
        assert delta_idx > result_idx

        # Verify delta content
        delta_event = events[delta_idx]
        paths = [op["path"] for op in delta_event["delta"]]
        assert "/counter" in paths

    def test_no_delta_when_state_unchanged(self, agent_client):
        client, agent = agent_client

        # State that won't change
        stable_state = {"counter": 0}

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Calling tool")

            tool_mock = MagicMock()
            tool_mock.tool_call_id = "tc_1"
            tool_mock.tool_name = "noop"
            tool_mock.tool_args = {}

            yield ToolCallStartedEvent(content="", tool=tool_mock)
            # No state mutation here
            tool_mock.result = "No change"
            yield ToolCallCompletedEvent(content="", tool=tool_mock)

            yield RunCompletedEvent(content="", session_state={"counter": 0})

        def mock_validate(state, thread_id):
            if state is not None:
                return stable_state
            return None

        with (
            patch.object(
                agent,
                "arun",
            ) as mock_arun,
            patch("agno.os.interfaces.agui.router.validate_state", side_effect=mock_validate),
        ):
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Noop", state={"counter": 0}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # No delta because state didn't change
        assert "STATE_DELTA" not in types
        # But still have snapshots
        assert "STATE_SNAPSHOT" in types


class TestAgentStateEdgeCases:
    def test_empty_dict_state(self, agent_client):
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Done")
            yield RunCompletedEvent(content="", session_state={})

        with patch.object(
            agent,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Test", state={}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # Empty dict is still valid state
        assert "STATE_SNAPSHOT" in types
        snapshot = next(e for e in events if e.get("type") == "STATE_SNAPSHOT")
        assert _same_state_value(snapshot["snapshot"], {}), snapshot["snapshot"]

    def test_nested_state_changes(self, agent_client):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client, agent = agent_client

        mutable_state = {"recipe": {"title": "", "ingredients": []}}

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Updating recipe")

            tool_mock = MagicMock()
            tool_mock.tool_call_id = "tc_1"
            tool_mock.tool_name = "update_recipe"
            tool_mock.tool_args = {}

            yield ToolCallStartedEvent(content="", tool=tool_mock)

            # Nested mutation
            mutable_state["recipe"]["title"] = "Pasta"
            mutable_state["recipe"]["ingredients"].append("noodles")

            tool_mock.result = "Updated"
            yield ToolCallCompletedEvent(content="", tool=tool_mock)

            yield RunCompletedEvent(content="", session_state=mutable_state)

        def mock_validate(state, thread_id):
            if state is not None:
                mutable_state["recipe"] = {"title": "", "ingredients": []}
                return mutable_state
            return None

        with (
            patch.object(
                agent,
                "arun",
            ) as mock_arun,
            patch("agno.os.interfaces.agui.router.validate_state", side_effect=mock_validate),
        ):
            mock_arun.return_value = mock_stream()
            response = client.post(
                "/agui", json=make_request_body("Update", state={"recipe": {"title": "", "ingredients": []}})
            )

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "STATE_DELTA" in types
        delta_event = next(e for e in events if e.get("type") == "STATE_DELTA")
        paths = [op["path"] for op in delta_event["delta"]]
        # Should have paths for nested changes
        assert any("/recipe" in p for p in paths)


# =============================================================================
# Team State Events
# =============================================================================


@pytest.fixture
def test_team():
    member = Agent(name="team-member", instructions="You help the team.")
    return Team(name="test-state-team", members=[member])


@pytest.fixture
def team_client(test_team: Team):
    agent_os = AgentOS(teams=[test_team], interfaces=[AGUI(team=test_team)])
    app = agent_os.get_app()
    return TestClient(app), test_team


class TestTeamStateSnapshot:
    def test_team_initial_snapshot(self, team_client):
        client, team = team_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Team response")
            yield RunCompletedEvent(content="", session_state={"task": "done"})

        with patch.object(
            team,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Test", state={"task": "pending"}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "RUN_STARTED" in types
        assert "STATE_SNAPSHOT" in types

        # Initial snapshot after RUN_STARTED
        run_started_idx = types.index("RUN_STARTED")
        first_snapshot_idx = types.index("STATE_SNAPSHOT")
        assert first_snapshot_idx == run_started_idx + 1

    def test_team_final_snapshot(self, team_client):
        client, team = team_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Team done")
            yield RunCompletedEvent(content="", session_state={"task": "completed"})

        with patch.object(
            team,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Finish", state={"task": "pending"}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # Final snapshot before RUN_FINISHED
        run_finished_idx = types.index("RUN_FINISHED")
        last_snapshot_idx = len(types) - 1 - types[::-1].index("STATE_SNAPSHOT")
        assert last_snapshot_idx == run_finished_idx - 1

        final_snapshot = events[last_snapshot_idx]
        assert _same_state_value(final_snapshot["snapshot"], {"task": "completed"}), final_snapshot["snapshot"]

    def test_team_no_state_events_without_state(self, team_client):
        client, team = team_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Team response")
            yield RunCompletedEvent(content="")

        with patch.object(
            team,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Test", state=None))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # The run really answered, so what is absent is state and not the run.
        assert "RUN_FINISHED" in types, types
        assert [e["delta"] for e in events if e.get("type") == "TEXT_MESSAGE_CONTENT"] == ["Team response"], types
        assert "STATE_SNAPSHOT" not in types
        assert "STATE_DELTA" not in types


# =============================================================================
# State payloads a client actually receives
#
# The tests above drive a mocked ``arun``, so Agno's run loop never runs and
# never touches session state. These drive a real run over a scripted model so
# the asserted snapshots and deltas are the payloads a client would decode.
# =============================================================================


class _ScriptedModel(Model):
    """Emits scripted turns offline: ('tool', name, args, id) or ('content', text)."""

    def __init__(self, script: List[tuple]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self._script = list(script)
        self._index = 0

    def _next(self) -> ModelResponse:
        from agno.metrics import MessageMetrics

        # Repeating the last turn once the script runs out would let a run that
        # takes more model turns than its script describes carry on quietly.
        assert self._index < len(self._script), (
            f"the run asked for model turn {self._index + 1} of a {len(self._script)}-turn script, "
            f"whose last turn was {self._script[-1]!r}"
        )
        turn = self._script[self._index]
        self._index += 1
        if turn[0] == "tool":
            _, name, args, tool_call_id = turn
            response = ModelResponse(role="assistant")
            response.tool_calls = [
                {"id": tool_call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            ]
        else:
            response = ModelResponse(content=turn[1], role="assistant")
            response.event = ModelResponseEvent.assistant_response.value
        response.response_usage = MessageMetrics(input_tokens=1, output_tokens=1, total_tokens=2)
        return response

    def invoke(self, *args, **kwargs):
        return self._next()

    async def ainvoke(self, *args, **kwargs):
        return self._next()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


@tool
def bump_counter(run_context: Optional[RunContext] = None) -> str:
    """Increment the shared counter by one."""
    session_state = run_context.session_state  # type: ignore[union-attr]
    session_state["counter"] = session_state.get("counter", 0) + 1
    return f"counter is now {session_state['counter']}"


@tool
def read_counter(run_context: Optional[RunContext] = None) -> str:
    """Report the shared counter without changing it."""
    return f"counter is {run_context.session_state.get('counter', 0)}"  # type: ignore[union-attr]


def _client_running_tool(tool_fn, calls: int = 1):
    """An AgentOS whose agent really runs, calling ``tool_fn`` then answering."""
    script = [("tool", tool_fn.name, {}, f"tc_{index}") for index in range(1, calls + 1)]
    agent = Agent(
        name="state-payload-agent",
        model=_ScriptedModel(script + [("content", "done")]),
        tools=[tool_fn],
    )
    agent_os = AgentOS(agents=[agent], interfaces=[AGUI(agent=agent)])
    return TestClient(agent_os.get_app())


def _real_run_client(mutates: bool = True):
    return _client_running_tool(bump_counter if mutates else read_counter)


def _state_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [e for e in events if e.get("type") in ("STATE_SNAPSHOT", "STATE_DELTA")]


def _same_state_value(left: Any, right: Any) -> bool:
    """Whether two decoded state payloads match with no type coercion at all.

    Deliberately a check of its own rather than a call into the comparison the
    delta is computed behind, which answers the same question by encoding both
    sides and comparing the JSON text: a test that reused that comparison would
    agree with it wherever it is wrong, and what these tests exist to catch is
    the client being sent 0 where False was expected, or 1 where 1.0 was.
    """
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return len(left) == len(right) and all(
            key in right and _same_state_value(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_state_value(a, b) for a, b in zip(left, right))
    return bool(left == right)


def _pointed_at(document: Any, pointer: str, op: Dict[str, Any]) -> Tuple[Any, str]:
    """The (container, token) pair a JSON Pointer's last segment names.

    Deliberately a walk of its own rather than a call into ``jsonpatch``:
    resolving a pointer with the library that wrote it lets a pointer built by
    the wrong rule be read back by the same wrong rule and agree with itself,
    which is the defect these deltas exist to be checked against. Every
    segment is read by the same rule as the last one, so a pointer naming an
    array by something that is no index is refused wherever it does it.
    """
    tokens = [token.replace("~1", "/").replace("~0", "~") for token in pointer.split("/")[1:]]
    if not tokens:
        raise AssertionError(f"the delta op reads or writes {pointer!r}, the whole document, which names no key of it")
    container = document
    for depth, token in enumerate(tokens[:-1]):
        key = _child_key(container, token, op)
        if not _holds(container, key):
            raise AssertionError(
                f"the delta points at {pointer}, whose {'/'.join(tokens[: depth + 1])} the client does not hold"
            )
        container = container[key]
    return container, tokens[-1]


def _child_key(container: Any, token: str, op: Dict[str, Any]) -> Any:
    """The key ``token`` names inside ``container``, as a client reads it.

    An array index is digits and nothing else: a token a JSON Patch
    implementation refuses to read as an index is refused here too, rather
    than reaching ``int`` and leaving a bare ValueError to be read.
    """
    if not isinstance(container, list) or token == "-":
        return token
    assert token.isascii() and token.isdigit() and (token == "0" or not token.startswith("0")), (
        f"the delta op {op} names {token!r} where the client holds an array, which is no array index"
    )
    return int(token)


def _holds(container: Any, key: Any) -> bool:
    if isinstance(container, list):
        return isinstance(key, int) and 0 <= key < len(container)
    return isinstance(container, dict) and key in container


def _client_document_after(document: Any, ops: List[Dict[str, Any]]) -> Any:
    """``document`` with a delta's ops applied the way a client applies them.

    A client hands the delta to a JSON Patch implementation, which refuses an
    operation the specification does not allow rather than making sense of
    it, so this refuses the same. ``list.insert`` in particular reads an index
    past the end of a list as an append and a negative one as a position
    counted back from the end: an ``add`` at index 9 of a two-element list,
    which a conformant client rejects outright, would otherwise replay
    cleanly here and be taken for a delta that carried the run to its closing
    snapshot.
    """
    document = copy.deepcopy(document)
    for op in ops:
        if op["op"] in ("move", "copy"):
            source, source_token = _pointed_at(document, op["from"], op)
            source_key = _child_key(source, source_token, op)
            assert _holds(source, source_key), f"the delta op {op} reads a location the client does not hold"
            value = copy.deepcopy(source[source_key])
            if op["op"] == "move":
                del source[source_key]
        else:
            value = op.get("value")

        if op["path"] == "":
            document = value
            continue

        container, token = _pointed_at(document, op["path"], op)
        key = _child_key(container, token, op)
        if op["op"] in ("remove", "replace"):
            assert _holds(container, key), f"the delta op {op} names a location the client does not hold"
            if op["op"] == "remove":
                del container[key]
            else:
                container[key] = value
        elif isinstance(container, list):
            index = len(container) if token == "-" else key
            assert index <= len(container), (
                f"the delta op {op} adds at index {index} of an array the client holds {len(container)} elements in"
            )
            container.insert(index, value)
        else:
            assert isinstance(container, dict), (
                f"the delta op {op} adds under {container!r}, which is neither an object nor an array"
            )
            container[token] = value
    return document


def _assert_the_deltas_carry_the_run_to_its_closing_snapshot(events: List[Dict[str, Any]]) -> None:
    """A client replaying the stream ends up holding the state the run ended with.

    That is the whole promise of a delta stream, and the only check that reads
    the ops as a client reads them: an op naming a key the client never held,
    or a change the ops describe only half of, leaves the replay somewhere the
    closing snapshot is not. Everything before the closing snapshot is
    replayed, so the closing snapshot is the answer rather than the last step.
    """
    closing = max((index for index, e in enumerate(events) if e.get("type") == "STATE_SNAPSHOT"), default=None)
    assert closing is not None and closing > 0, f"the run sent no state for a client to replay: {_state_events(events)}"

    held: Any = None
    for event in events[:closing]:
        if event.get("type") == "STATE_SNAPSHOT":
            held = copy.deepcopy(event["snapshot"])
        elif event.get("type") == "STATE_DELTA":
            held = _client_document_after(held, event["delta"])

    assert _same_state_value(held, events[closing]["snapshot"]), (
        f"replaying the stream leaves a client holding {held!r}, "
        f"not the {events[closing]['snapshot']!r} the run closed with"
    )


def _client_document_when(events: List[Dict[str, Any]], state_event: Dict[str, Any]) -> Any:
    """What a client holds once it has applied ``state_event`` and all before it.

    Several patches describe one change, and which of them ``jsonpatch``
    emits is its own business: a rekeyed map it spells as a single move,
    another implementation spells as a remove beside an add. What the client
    is owed is the document, so a test reading the document back holds for
    whichever spelling arrives, and still catches a move whose destination
    reads correctly while the key it moved from is left behind.
    """
    held: Any = None
    for event in events:
        if event.get("type") == "STATE_SNAPSHOT":
            held = copy.deepcopy(event["snapshot"])
        elif event.get("type") == "STATE_DELTA":
            held = _client_document_after(held, event["delta"])
        if event is state_event:
            return held
    raise AssertionError(f"{state_event} is not one of the events it was to be replayed through")


def _state_event_per_tool_call(events: List[Dict[str, Any]]) -> List[Optional[Dict[str, Any]]]:
    """The state event each tool call sent the client, ``None`` where it sent none.

    A run opens with a snapshot of the request state and closes with one of the
    final state whatever its tool calls did, so neither says anything about a
    change reaching the client while the run was still going: a guard that took
    everything but the last state event would be satisfied by the opening
    snapshot alone, and the closing snapshot is left out here even where a
    tool call's end is the last thing before it.

    A tool call's own state event follows the end of the call, and the anchor
    is that end rather than the result event between them: a tool that returns
    nothing sends no result while the state event goes out all the same, so
    anchoring on the result would move the positions a test asserts on out
    from under it.

    Keeping the calls that sent nothing, rather than dropping them, is what
    lets a test say which call was told about and which was left alone.
    """
    closing = max((index for index, e in enumerate(events) if e.get("type") == "STATE_SNAPSHOT"), default=-1)
    per_call: List[Optional[Dict[str, Any]]] = []
    for index, event in enumerate(events):
        if event.get("type") != "TOOL_CALL_END":
            continue
        following = index + 1
        if following < len(events) and events[following].get("type") == "TOOL_CALL_RESULT":
            following += 1
        sent = events[following] if following < len(events) else None
        if sent is None or following == closing or sent.get("type") not in ("STATE_SNAPSHOT", "STATE_DELTA"):
            per_call.append(None)
        else:
            per_call.append(sent)
    return per_call


def _snapshots_emitted_for_tool_calls(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The snapshots the router sent because a tool call changed state."""
    return [
        event for event in _state_event_per_tool_call(events) if event is not None and event["type"] == "STATE_SNAPSHOT"
    ]


def _events_of_completed_run(
    response,
    *,
    ran: List[str],
    reported: Optional[str] = None,
    left_state: Any,
) -> List[Dict[str, Any]]:
    """Assert what the run did, then hand back its events for the rest of a test.

    A check that holds on an absent event type, on an event count or on a
    substring is satisfied just as well by a run whose model answered with
    content and never called the tool, or by one that died before finishing, so
    every test below says here what the run was supposed to do: the tools it
    called in order, optionally what the last one reported, and the state the
    client was left holding once the run finished.

    The state is compared without type coercion, because ``==`` alone calls 0
    and False equal and 1 and 1.0 equal, which is exactly the distinction some
    of the tests below exist to prove reaches the client.
    """
    assert response.status_code == 200, response.text
    events = parse_sse_events(response.text)
    types = get_event_types(events)

    called = [e["toolCallName"] for e in events if e.get("type") == "TOOL_CALL_START"]
    assert called == ran, f"the run called {called}, not {ran}: {types}"
    results = [e for e in events if e.get("type") == "TOOL_CALL_RESULT"]
    assert len(results) == len(ran), f"{len(ran)} tool calls returned {len(results)} results: {types}"
    if reported is not None:
        assert reported in results[-1]["content"], results[-1]["content"]

    assert "RUN_FINISHED" in types, types
    assert "RUN_ERROR" not in types, [e for e in events if e.get("type") == "RUN_ERROR"]

    snapshots = [e for e in events if e.get("type") == "STATE_SNAPSHOT"]
    assert snapshots, f"the client was left holding no state at all: {types}"
    assert _same_state_value(snapshots[-1]["snapshot"], left_state), (
        f"the client was left holding {snapshots[-1]['snapshot']!r}, not {left_state!r}"
    )
    _assert_the_deltas_carry_the_run_to_its_closing_snapshot(events)
    _assert_the_client_accepts_the_tool_call_spans(events)

    return events


@pytest.fixture
def warnings_logged() -> Iterator[List[logging.LogRecord]]:
    """Every warning Agno logs while a test runs, whichever logger carried it.

    ``log_warning`` writes to a process-global logger that a team run rebinds
    to the team logger and never rebinds back, so the same AG-UI state warning
    is carried by one logger or another depending on what else ran earlier in
    the process. What these tests assert is that the state path warned and what
    it said, so they read every logger the helper can be bound to and stay out
    of that. The loggers are read off the module rather than named, so one
    added to it later is covered too.
    """
    records: List[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collector(logging.WARNING)
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


@tool
def add_ingredient(run_context: Optional[RunContext] = None) -> str:
    """Append an ingredient to the shared recipe, leaving the recipe in place."""
    run_context.session_state["recipe"]["ingredients"].append("noodles")  # type: ignore[union-attr,index]
    return "the recipe lists noodles"


class TestAMutationInsideAContainerReachesTheClient:
    """A tool that appends to a list already in session_state never rebinds the
    key holding it, which is the ordinary shape of a tool that edits a document
    or a cart. The snapshot the comparison is measured against has to be a copy
    taken deep enough that the append cannot reach it: sharing the containers
    leaves the mutation on both sides of the comparison, so the run reads as
    unchanged and the client hears about the ingredient only once it is over."""

    def test_a_delta_reports_a_list_appended_to_in_place(self):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tool(add_ingredient)
        response = client.post(
            "/agui", json=make_request_body("add", state={"recipe": {"title": "", "ingredients": []}})
        )

        events = _events_of_completed_run(
            response,
            ran=[add_ingredient.name],
            reported="the recipe lists noodles",
            left_state={"recipe": {"title": "", "ingredients": ["noodles"]}},
        )
        told = _state_event_per_tool_call(events)
        assert told[0] is not None, f"the append never reached the client: {_state_events(events)}"
        assert told[0]["type"] == "STATE_DELTA", told[0]
        assert [op["path"] for op in told[0]["delta"]] == ["/recipe/ingredients/0"], told[0]["delta"]

    def test_a_snapshot_reports_a_list_appended_to_in_place_without_jsonpatch(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "jsonpatch", None)
        client = _client_running_tool(add_ingredient)
        response = client.post(
            "/agui", json=make_request_body("add", state={"recipe": {"title": "", "ingredients": []}})
        )

        events = _events_of_completed_run(
            response,
            ran=[add_ingredient.name],
            reported="the recipe lists noodles",
            left_state={"recipe": {"title": "", "ingredients": ["noodles"]}},
        )
        mid_stream = _snapshots_emitted_for_tool_calls(events)
        assert mid_stream, f"the append never reached the client: {_state_events(events)}"
        snapshot = mid_stream[-1]["snapshot"]
        assert _same_state_value(snapshot["recipe"]["ingredients"], ["noodles"]), snapshot


class TestClientStateExcludesAgnoBookkeeping:
    """Agno injects current_user_id/current_session_id/current_run_id into
    session_state at runtime and strips them again before persisting the
    session row. They are Agno's record keeping, so a client must never see
    them appear in state it did not write."""

    def test_final_snapshot_carries_only_application_state(self):
        client = _real_run_client()
        response = client.post("/agui", json=make_request_body("bump", state={"counter": 0}))

        _events_of_completed_run(
            response,
            ran=[bump_counter.name],
            reported="counter is now 1",
            left_state={"counter": 1},
        )

    def test_delta_ops_never_reference_bookkeeping_keys(self):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _real_run_client()
        response = client.post("/agui", json=make_request_body("bump", state={"counter": 0}))

        events = _events_of_completed_run(
            response,
            ran=[bump_counter.name],
            reported="counter is now 1",
            left_state={"counter": 1},
        )
        deltas = [e for e in events if e.get("type") == "STATE_DELTA"]
        assert deltas, "expected a state delta for the counter mutation"
        assert [op["path"] for delta in deltas for op in delta["delta"]] == ["/counter"]

    def test_initial_snapshot_drops_bookkeeping_keys_sent_by_the_client(self):
        client = _real_run_client()
        response = client.post(
            "/agui",
            json=make_request_body("bump", state={"counter": 0, "current_run_id": "stale", "current_user_id": "stale"}),
        )

        events = _events_of_completed_run(
            response,
            ran=[bump_counter.name],
            reported="counter is now 1",
            left_state={"counter": 1},
        )
        first_snapshot = next(e for e in events if e.get("type") == "STATE_SNAPSHOT")
        assert _same_state_value(first_snapshot["snapshot"], {"counter": 0}), first_snapshot["snapshot"]


class TestStateStreamingWithoutJsonpatch:
    """Agno's ``agui`` extra installs ``jsonpatch`` together with
    ``ag-ui-protocol``, and the ``os`` extra ships neither, so the install these
    tests stand in for is one that added ``ag-ui-protocol`` by hand on top of
    ``os``. Without ``jsonpatch`` the delta cannot be computed, and dropping the
    update would hide the mutation from the client entirely."""

    def test_state_change_stays_visible_as_a_snapshot(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "jsonpatch", None)
        client = _real_run_client()
        response = client.post("/agui", json=make_request_body("bump", state={"counter": 0}))

        events = _events_of_completed_run(
            response,
            ran=[bump_counter.name],
            reported="counter is now 1",
            left_state={"counter": 1},
        )
        assert "STATE_DELTA" not in get_event_types(events)

        mid_stream = [
            e for e in _snapshots_emitted_for_tool_calls(events) if _same_state_value(e["snapshot"], {"counter": 1})
        ]
        assert mid_stream, f"the counter mutation never reached the client: {_state_events(events)}"

    def test_warning_names_the_missing_dependency_and_how_to_install_it(self, monkeypatch, warnings_logged):
        monkeypatch.setitem(sys.modules, "jsonpatch", None)
        client = _real_run_client()

        response = client.post("/agui", json=make_request_body("bump", state={"counter": 0}))

        events = _events_of_completed_run(
            response,
            ran=[bump_counter.name],
            reported="counter is now 1",
            left_state={"counter": 1},
        )
        types = get_event_types(events)
        assert "STATE_DELTA" not in types, types
        assert [
            e for e in _snapshots_emitted_for_tool_calls(events) if _same_state_value(e["snapshot"], {"counter": 1})
        ], f"the snapshot fallback never fired: {_state_events(events)}"

        # The fallback warns once per run, so the run's only warning is that
        # warning and the wording checks cannot land on an unrelated line.
        warnings = [record for record in warnings_logged if record.levelno >= logging.WARNING]
        assert len(warnings) == 1, [record.getMessage() for record in warnings]
        fallback_warning = warnings[0].getMessage()
        assert "jsonpatch" in fallback_warning
        assert "pip install" in fallback_warning
        assert "STATE_SNAPSHOT" in fallback_warning

    def test_no_extra_snapshot_when_state_did_not_change(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "jsonpatch", None)
        client = _real_run_client(mutates=False)
        response = client.post("/agui", json=make_request_body("read", state={"counter": 0}))

        events = _events_of_completed_run(
            response,
            ran=[read_counter.name],
            reported="counter is 0",
            left_state={"counter": 0},
        )
        assert get_event_types(events).count("STATE_SNAPSHOT") == 2


@tool
def disable_flag(run_context: Optional[RunContext] = None) -> str:
    """Replace the shared flag's zero with the boolean False."""
    run_context.session_state["flag"] = False  # type: ignore[union-attr,index]
    return "flag is now False"


@tool
def widen_counter(run_context: Optional[RunContext] = None) -> str:
    """Store the shared counter as a float of the same numeric value."""
    run_context.session_state["counter"] = 1.0  # type: ignore[union-attr,index]
    return "counter is now a float"


@tool
def disable_nested_flag(run_context: Optional[RunContext] = None) -> str:
    """Replace the nested flag's zero with the boolean False."""
    run_context.session_state["nested"] = {"flag": False}  # type: ignore[union-attr,index]
    return "the nested flag is now False"


@tool
def disable_listed_flag(run_context: Optional[RunContext] = None) -> str:
    """Replace the zero inside the shared list with the boolean False."""
    run_context.session_state["flags"] = [False]  # type: ignore[union-attr,index]
    return "the listed flag is now False"


class TestStateValueTypeChangesReachTheClient:
    """``0 == False`` and ``1 == 1.0`` in Python, so a value whose type flips
    without its numeric value changing is easy to mistake for no change at
    all. A client that renders a checkbox off a flag has to learn about it."""

    def test_delta_reports_an_int_becoming_a_bool(self):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tool(disable_flag)
        response = client.post("/agui", json=make_request_body("disable", state={"flag": 0}))

        events = _events_of_completed_run(
            response,
            ran=[disable_flag.name],
            reported="flag is now False",
            left_state={"flag": False},
        )
        ops = [op for e in events if e.get("type") == "STATE_DELTA" for op in e["delta"]]
        assert ops, f"the flag change never reached the client: {_state_events(events)}"
        assert ops[-1]["path"] == "/flag"
        assert ops[-1]["value"] is False

    def test_delta_reports_an_int_becoming_a_float(self):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tool(widen_counter)
        response = client.post("/agui", json=make_request_body("widen", state={"counter": 1}))

        events = _events_of_completed_run(
            response,
            ran=[widen_counter.name],
            reported="counter is now a float",
            left_state={"counter": 1.0},
        )
        ops = [op for e in events if e.get("type") == "STATE_DELTA" for op in e["delta"]]
        assert ops, f"the counter change never reached the client: {_state_events(events)}"
        assert ops[-1]["path"] == "/counter"
        assert isinstance(ops[-1]["value"], float)

    def test_delta_reports_a_nested_int_becoming_a_bool(self):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tool(disable_nested_flag)
        response = client.post("/agui", json=make_request_body("disable", state={"nested": {"flag": 0}}))

        events = _events_of_completed_run(
            response,
            ran=[disable_nested_flag.name],
            reported="the nested flag is now False",
            left_state={"nested": {"flag": False}},
        )
        ops = [op for e in events if e.get("type") == "STATE_DELTA" for op in e["delta"]]
        assert ops, f"the nested flag change never reached the client: {_state_events(events)}"
        assert ops[-1]["path"] == "/nested/flag"
        assert ops[-1]["value"] is False

    def test_snapshot_reports_an_int_becoming_a_bool_without_jsonpatch(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "jsonpatch", None)
        client = _client_running_tool(disable_flag)
        response = client.post("/agui", json=make_request_body("disable", state={"flag": 0}))

        events = _events_of_completed_run(
            response,
            ran=[disable_flag.name],
            reported="flag is now False",
            left_state={"flag": False},
        )
        mid_stream = _snapshots_emitted_for_tool_calls(events)
        assert mid_stream, f"the flag change never reached the client: {_state_events(events)}"
        assert mid_stream[-1]["snapshot"]["flag"] is False

    def test_snapshot_reports_an_int_becoming_a_float_without_jsonpatch(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "jsonpatch", None)
        client = _client_running_tool(widen_counter)
        response = client.post("/agui", json=make_request_body("widen", state={"counter": 1}))

        events = _events_of_completed_run(
            response,
            ran=[widen_counter.name],
            reported="counter is now a float",
            left_state={"counter": 1.0},
        )
        mid_stream = _snapshots_emitted_for_tool_calls(events)
        assert mid_stream, f"the counter change never reached the client: {_state_events(events)}"
        assert isinstance(mid_stream[-1]["snapshot"]["counter"], float)

    def test_snapshot_reports_a_listed_int_becoming_a_bool_without_jsonpatch(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "jsonpatch", None)
        client = _client_running_tool(disable_listed_flag)
        response = client.post("/agui", json=make_request_body("disable", state={"flags": [0]}))

        events = _events_of_completed_run(
            response,
            ran=[disable_listed_flag.name],
            reported="the listed flag is now False",
            left_state={"flags": [False]},
        )
        mid_stream = _snapshots_emitted_for_tool_calls(events)
        assert mid_stream, f"the listed flag change never reached the client: {_state_events(events)}"
        flags = mid_stream[-1]["snapshot"]["flags"]
        assert _same_state_value(flags, [False]), f"the client was sent {flags!r}"
        assert flags[0] is False


# =============================================================================
# Changes only the encoded state shows
# =============================================================================


@tool
def key_the_map_by_one(run_context: Optional[RunContext] = None) -> str:
    """Key the shared map by the integer 1."""
    run_context.session_state["by_flag"] = {1: "on"}  # type: ignore[union-attr,index]
    return "the map is keyed by 1"


@tool
def key_the_map_by_true(run_context: Optional[RunContext] = None) -> str:
    """Key the shared map by the boolean True."""
    run_context.session_state["by_flag"] = {True: "on"}  # type: ignore[union-attr,index]
    return "the map is keyed by True"


@tool
def hold_zero_in_a_set(run_context: Optional[RunContext] = None) -> str:
    """Hold the integer 0 in the shared set."""
    run_context.session_state["seen"] = {0}  # type: ignore[union-attr,index]
    return "the set holds 0"


@tool
def hold_false_in_a_set(run_context: Optional[RunContext] = None) -> str:
    """Hold the boolean False in the shared set."""
    run_context.session_state["seen"] = {False}  # type: ignore[union-attr,index]
    return "the set holds False"


@tool
def key_the_map_by_nothing(run_context: Optional[RunContext] = None) -> str:
    """Key the shared map by None, holding off."""
    run_context.session_state["by_nothing"] = {None: "off"}  # type: ignore[union-attr,index]
    return "the map is keyed by None, off"


@tool
def flip_the_map_keyed_by_nothing(run_context: Optional[RunContext] = None) -> str:
    """Key the shared map by None again, holding on."""
    run_context.session_state["by_nothing"] = {None: "on"}  # type: ignore[union-attr,index]
    return "the map is keyed by None, on"


@tool
def key_the_labels_by_one_and_count(run_context: Optional[RunContext] = None) -> str:
    """Key the shared labels by the integer 1, and count one."""
    run_context.session_state["labels"] = {1: "x"}  # type: ignore[union-attr,index]
    run_context.session_state["counted"] = 1  # type: ignore[union-attr,index]
    return "keyed by 1, counted 1"


@tool
def key_the_labels_by_true_and_count(run_context: Optional[RunContext] = None) -> str:
    """Key the shared labels by the boolean True, and count two."""
    run_context.session_state["labels"] = {True: "x"}  # type: ignore[union-attr,index]
    run_context.session_state["counted"] = 2  # type: ignore[union-attr,index]
    return "keyed by True, counted 2"


class AliasedProfile(BaseModel):
    """A state value whose JSON key is not its field name, the way a model
    carrying an API's own spelling of a field is."""

    user_name: str = Field(alias="user-name")


@tool
def store_the_aliased_profile(run_context: Optional[RunContext] = None) -> str:
    """Store a model the encoder renders under a key that is not its field name."""
    run_context.session_state["profile"] = AliasedProfile(**{"user-name": "ran"})  # type: ignore[union-attr,index]
    return "the profile names ran"


@tool
def disable_the_listed_flag_and_count(run_context: Optional[RunContext] = None) -> str:
    """Replace the zero inside the shared list with False, and bump the counter."""
    run_context.session_state["flags"] = [False]  # type: ignore[union-attr,index]
    run_context.session_state["counter"] = 2  # type: ignore[union-attr,index]
    return "the listed flag is False, counted 2"


@tool
def rebuild_the_recipe_in_another_key_order(run_context: Optional[RunContext] = None) -> str:
    """Rebuild the shared recipe dict holding the same entries, keyed in reverse."""
    recipe = run_context.session_state["recipe"]  # type: ignore[union-attr,index]
    run_context.session_state["recipe"] = {key: recipe[key] for key in reversed(list(recipe))}  # type: ignore[union-attr,index]
    return "the recipe is rebuilt in another key order"


@tool
def hold_the_pair_as_a_tuple(run_context: Optional[RunContext] = None) -> str:
    """Hold the shared pair as a tuple rather than a list."""
    run_context.session_state["pair"] = (1, 2)  # type: ignore[union-attr,index]
    return "the pair is a tuple"


def _client_running_tools(tool_fns: List[Any]):
    """An AgentOS whose agent calls each of ``tool_fns`` in order, then answers."""
    script = [("tool", tool_fn.name, {}, f"tc_{index}") for index, tool_fn in enumerate(tool_fns, start=1)]
    agent = Agent(
        name="state-payload-agent",
        model=_ScriptedModel(script + [("content", "done")]),
        tools=list(tool_fns),
    )
    return TestClient(AgentOS(agents=[agent], interfaces=[AGUI(agent=agent)]).get_app())


class TestChangesOnlyTheEncodedStateShowsReachTheClient:
    """A client never holds the Python objects in session_state, only the JSON
    the event encoder makes of them. Two states Python calls equal can encode
    to different JSON: a dict looks its keys up by hash, so 1 and True are one
    key to it and ``"1"`` and ``"true"`` to a client, and a set compares by
    membership, so ``{0}`` and ``{False}`` are one value to it and ``[0]`` and
    ``[false]`` to a client. Judging the objects leaves the client rendering
    state the run has already moved on from."""

    def test_a_map_rekeyed_from_one_to_true_reaches_the_client(self):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tools([key_the_map_by_one, key_the_map_by_true])
        response = client.post("/agui", json=make_request_body("rekey", state={"by_flag": {}}))

        events = _events_of_completed_run(
            response,
            ran=[key_the_map_by_one.name, key_the_map_by_true.name],
            reported="the map is keyed by True",
            left_state={"by_flag": {"true": "on"}},
        )
        told = _state_event_per_tool_call(events)
        assert told[1] is not None, f"the rekey never reached the client: {_state_events(events)}"
        assert told[1]["type"] == "STATE_DELTA", told[1]
        # The client is left holding the key it can see, "true", and neither
        # the "True" Python spells the same key nor the "1" the map was keyed
        # by before: a rekey that adds the new key and leaves the old one
        # behind is a map the client renders with two entries.
        assert _same_state_value(_client_document_when(events, told[1]), {"by_flag": {"true": "on"}}), told[1]

    def test_a_set_holding_zero_becoming_one_holding_false_reaches_the_client(self, warnings_logged):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tools([hold_zero_in_a_set, hold_false_in_a_set])
        response = client.post("/agui", json=make_request_body("swap", state={"seen": []}))

        events = _events_of_completed_run(
            response,
            ran=[hold_zero_in_a_set.name, hold_false_in_a_set.name],
            reported="the set holds False",
            left_state={"seen": [False]},
        )
        told = _state_event_per_tool_call(events)
        # ``jsonpatch`` reads a list element by element with ``==``, so it calls
        # 0 and False the same element and has no op to offer for [0] becoming
        # [false]. The client is told with the whole state instead, and never
        # told nothing.
        assert told[1] is not None, f"the set change never reached the client: {_state_events(events)}"
        assert told[1]["type"] == "STATE_SNAPSHOT", told[1]
        # The fallback warns once per run, so the run's only warning is that
        # warning and the wording checks cannot land on an unrelated line. What
        # an operator reads has to say the change still went out whole, without
        # reading as a defect in a library that behaved as documented.
        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        assert len(warnings) == 1, warnings
        assert "no operation to describe" in warnings[0], warnings[0]
        assert "STATE_SNAPSHOT" in warnings[0], warnings[0]

    def test_a_key_json_renames_is_pointed_at_by_the_name_the_client_holds(self):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tools([key_the_map_by_nothing, flip_the_map_keyed_by_nothing])
        response = client.post("/agui", json=make_request_body("flip", state={"by_nothing": {}}))

        events = _events_of_completed_run(
            response,
            ran=[key_the_map_by_nothing.name, flip_the_map_keyed_by_nothing.name],
            reported="the map is keyed by None, on",
            left_state={"by_nothing": {"None": "on"}},
        )
        told = _state_event_per_tool_call(events)
        assert told[1] is not None, f"the flip never reached the client: {_state_events(events)}"
        assert told[1]["type"] == "STATE_DELTA", told[1]
        # Pointed at the value under the key, never at the map holding it: a
        # pointer built one level too shallow replaces the whole map with the
        # scalar and leaves the client rendering a string where an object was.
        assert [op["path"] for op in told[1]["delta"]] == ["/by_nothing/None"], told[1]["delta"]

    def test_a_change_the_client_sees_only_half_of_is_not_reported_as_the_whole(self):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tools([key_the_labels_by_one_and_count, key_the_labels_by_true_and_count])
        response = client.post("/agui", json=make_request_body("rekey", state={}))

        events = _events_of_completed_run(
            response,
            ran=[key_the_labels_by_one_and_count.name, key_the_labels_by_true_and_count.name],
            reported="keyed by True, counted 2",
            left_state={"labels": {"true": "x"}, "counted": 2},
        )
        told = _state_event_per_tool_call(events)
        assert told[1] is not None, f"the rekey never reached the client: {_state_events(events)}"
        # Both halves or neither, and the rekeyed map left holding one entry
        # rather than two. A delta carrying the counter alone is not empty, so
        # no snapshot fallback fires behind it and the rekey is lost.
        left_holding = {"labels": {"true": "x"}, "counted": 2}
        assert _same_state_value(_client_document_when(events, told[1]), left_holding), told[1]

    def test_a_type_flip_inside_a_list_is_not_dropped_behind_a_change_beside_it(self, warnings_logged):
        """The same demand as the test above, for the half ``jsonpatch`` cannot
        see at all. It reads a list element by element with ``==``, so [0]
        becoming [false] is no change to it and the ops it offers describe the
        counter alone. Those ops are not empty, so nothing behind them fires on
        their own: they go out, the baseline advances past the flag, and the
        client renders a checkbox the run turned off for the rest of the run."""
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tools([disable_the_listed_flag_and_count])
        response = client.post("/agui", json=make_request_body("disable", state={"flags": [0], "counter": 1}))

        events = _events_of_completed_run(
            response,
            ran=[disable_the_listed_flag_and_count.name],
            reported="the listed flag is False, counted 2",
            left_state={"flags": [False], "counter": 2},
        )
        told = _state_event_per_tool_call(events)
        assert told[0] is not None, f"the change never reached the client: {_state_events(events)}"
        assert told[0]["type"] == "STATE_SNAPSHOT", told[0]
        assert told[0]["snapshot"]["flags"][0] is False, told[0]["snapshot"]
        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        assert len(warnings) == 1, warnings
        assert "does not reproduce the state it was computed for" in warnings[0], warnings[0]
        assert "STATE_SNAPSHOT" in warnings[0], warnings[0]

    def test_an_aliased_field_is_pointed_at_by_the_alias_the_client_holds(self):
        """The encoder renders a model by alias, so the client holds
        ``user-name``, and a pointer naming ``user_name`` names nothing it can
        find: the op adds a second key beside the one it was meant for, and the
        field the client renders keeps the value it already held."""
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tools([store_the_aliased_profile])
        response = client.post("/agui", json=make_request_body("store", state={"profile": {}}))

        events = _events_of_completed_run(
            response,
            ran=[store_the_aliased_profile.name],
            reported="the profile names ran",
            left_state={"profile": {"user-name": "ran"}},
        )
        told = _state_event_per_tool_call(events)
        assert told[0] is not None, f"the profile never reached the client: {_state_events(events)}"
        assert told[0]["type"] == "STATE_DELTA", told[0]
        assert [op["path"] for op in told[0]["delta"]] == ["/profile/user-name"], told[0]["delta"]


class TestStateThatEncodesTheSameIsNotAChange:
    """The mirror of the class above: two states Python calls different can
    encode to the same JSON, and a list swapped for a tuple is the ordinary
    case. Judging the objects ships the client a full snapshot it already
    holds, and on an install without ``jsonpatch`` a warning telling the reader
    to install a package that would have changed nothing."""

    def test_a_list_becoming_a_tuple_ships_nothing(self):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tools([hold_the_pair_as_a_tuple])
        response = client.post("/agui", json=make_request_body("retype", state={"pair": [1, 2]}))

        events = _events_of_completed_run(
            response,
            ran=[hold_the_pair_as_a_tuple.name],
            reported="the pair is a tuple",
            left_state={"pair": [1, 2]},
        )
        assert _state_event_per_tool_call(events) == [None], _state_events(events)
        # Only the run's opening and closing snapshots.
        assert get_event_types(events).count("STATE_SNAPSHOT") == 2, _state_events(events)

    def test_a_dict_rebuilt_in_another_key_order_ships_nothing(self, warnings_logged):
        """A JSON object is its entries, not the order they were written in, so
        a client reading the parsed payload cannot see a rebuild. The
        comparison reads a serialization, which can see one unless its keys are
        sorted, and jsonpatch has no op to offer for a difference that is not
        there: the run would fall back to a snapshot of state already held, and
        warn about it."""
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_running_tools([rebuild_the_recipe_in_another_key_order])
        response = client.post(
            "/agui", json=make_request_body("rebuild", state={"recipe": {"title": "soup", "servings": 2}})
        )

        events = _events_of_completed_run(
            response,
            ran=[rebuild_the_recipe_in_another_key_order.name],
            reported="the recipe is rebuilt in another key order",
            left_state={"recipe": {"title": "soup", "servings": 2}},
        )
        assert _state_event_per_tool_call(events) == [None], _state_events(events)
        assert get_event_types(events).count("STATE_SNAPSHOT") == 2, _state_events(events)
        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        assert warnings == [], warnings

    def test_a_list_becoming_a_tuple_ships_nothing_and_warns_nothing_without_jsonpatch(
        self, monkeypatch, warnings_logged
    ):
        monkeypatch.setitem(sys.modules, "jsonpatch", None)
        client = _client_running_tools([hold_the_pair_as_a_tuple])

        response = client.post("/agui", json=make_request_body("retype", state={"pair": [1, 2]}))

        events = _events_of_completed_run(
            response,
            ran=[hold_the_pair_as_a_tuple.name],
            reported="the pair is a tuple",
            left_state={"pair": [1, 2]},
        )
        assert _state_event_per_tool_call(events) == [None], _state_events(events)
        assert get_event_types(events).count("STATE_SNAPSHOT") == 2, _state_events(events)
        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        assert warnings == [], warnings


# =============================================================================
# Every reason the delta fallback fires
# =============================================================================


class _BrokenJsonpatch:
    """Stands in for ``jsonpatch`` when the patch computation itself fails."""

    @staticmethod
    def make_patch(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("value is not diffable")


class _SilentJsonpatch:
    """Stands in for ``jsonpatch`` when it describes a change with no ops."""

    class _Empty:
        patch: List[Dict[str, Any]] = []

    @staticmethod
    def make_patch(*args: Any, **kwargs: Any) -> Any:
        return _SilentJsonpatch._Empty()


class _UnfaithfulJsonpatch:
    """Stands in for ``jsonpatch`` when it answers a change with ops that do
    not reproduce it: neither empty, nor the change the client is owed."""

    class _Patch:
        patch: List[Dict[str, Any]] = [{"op": "add", "path": "/unrelated", "value": "noise"}]

    @staticmethod
    def make_patch(*args: Any, **kwargs: Any) -> Any:
        return _UnfaithfulJsonpatch._Patch()

    @staticmethod
    def apply_patch(document: Any, ops: List[Dict[str, Any]]) -> Any:
        replayed = copy.deepcopy(document)
        for operation in ops:
            replayed[operation["path"].lstrip("/")] = operation["value"]
        return replayed


class _UnreplayableJsonpatch:
    """Stands in for ``jsonpatch`` when the replay that checks the ops raises
    rather than answering: ops that cannot be applied at all are a different
    failure from ops that apply and land somewhere else."""

    @staticmethod
    def make_patch(*args: Any, **kwargs: Any) -> Any:
        return _UnfaithfulJsonpatch.make_patch()

    @staticmethod
    def apply_patch(document: Any, ops: List[Dict[str, Any]]) -> Any:
        raise ValueError("the ops name a path this document has no place for")


class _UnreplayableThenUnfaithfulJsonpatch:
    """Stands in for ``jsonpatch`` when the replay check fails one way and then
    the other, so a single run reaches both arms of it.

    An instance rather than a class, because ``sys.modules`` entries are read
    by attribute and an instance keeps its call count to the one test holding
    it, where a class attribute would carry it across the suite.
    """

    def __init__(self) -> None:
        self.replays = 0

    def make_patch(self, *args: Any, **kwargs: Any) -> Any:
        return _UnfaithfulJsonpatch.make_patch()

    def apply_patch(self, document: Any, ops: List[Dict[str, Any]]) -> Any:
        self.replays += 1
        if self.replays == 1:
            return _UnreplayableJsonpatch.apply_patch(document, ops)
        return _UnfaithfulJsonpatch.apply_patch(document, ops)


# Set by the ``breaking_jsonpatch_mid_run`` fixture for as long as a test that
# asked for it is running, and cleared again afterwards.
_break_jsonpatch_mid_run: Optional[Callable[[], None]] = None


@pytest.fixture
def breaking_jsonpatch_mid_run(monkeypatch):
    """Owns ``sys.modules["jsonpatch"]`` for a test whose tool breaks it mid-run.

    Reaching the patch computation failing after the missing dependency inside
    a single run means changing the entry while the run is going, which only a
    tool body can do. Both changes are made through ``monkeypatch`` here, so
    pytest restores the entry when the test ends however the run went, rather
    than the tool leaving the process holding a broken ``jsonpatch``.
    """
    global _break_jsonpatch_mid_run

    monkeypatch.setitem(sys.modules, "jsonpatch", None)

    def swap() -> None:
        monkeypatch.setitem(sys.modules, "jsonpatch", _BrokenJsonpatch)

    _break_jsonpatch_mid_run = swap
    yield swap
    _break_jsonpatch_mid_run = None


@tool
def bump_counter_and_break_jsonpatch(run_context: Optional[RunContext] = None) -> str:
    """Increment the shared counter, leaving jsonpatch importable but failing."""
    assert _break_jsonpatch_mid_run is not None, (
        "this tool changes sys.modules['jsonpatch'], so the test calling it has to take the "
        "breaking_jsonpatch_mid_run fixture and let pytest restore the entry"
    )
    _break_jsonpatch_mid_run()
    assert sys.modules["jsonpatch"] is _BrokenJsonpatch
    session_state = run_context.session_state  # type: ignore[union-attr]
    session_state["counter"] = session_state.get("counter", 0) + 1
    return f"counter is now {session_state['counter']}"


class TestEveryDeltaFallbackReasonIsReported:
    """The fallback to a full snapshot has several distinct causes, and each is
    actionable in a different way: ``jsonpatch`` not being importable is fixed
    by installing it, while the patch computation failing is not. Reporting
    only whichever came first leaves an operator with no sign of the other."""

    def test_both_reasons_are_reported_once_each_in_one_run(self, breaking_jsonpatch_mid_run, warnings_logged):
        agent = Agent(
            name="state-payload-agent",
            model=_ScriptedModel(
                [
                    ("tool", bump_counter.name, {}, "tc_1"),
                    ("tool", bump_counter.name, {}, "tc_2"),
                    ("tool", bump_counter_and_break_jsonpatch.name, {}, "tc_3"),
                    ("tool", bump_counter.name, {}, "tc_4"),
                    ("content", "done"),
                ]
            ),
            tools=[bump_counter, bump_counter_and_break_jsonpatch],
        )
        client = TestClient(AgentOS(agents=[agent], interfaces=[AGUI(agent=agent)]).get_app())

        response = client.post("/agui", json=make_request_body("bump", state={"counter": 0}))

        _events_of_completed_run(
            response,
            ran=[
                bump_counter.name,
                bump_counter.name,
                bump_counter_and_break_jsonpatch.name,
                bump_counter.name,
            ],
            reported="counter is now 4",
            left_state={"counter": 4},
        )

        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        missing_dependency = [warning for warning in warnings if "not importable" in warning]
        computation_failed = [warning for warning in warnings if "could not be computed" in warning]
        assert len(missing_dependency) == 1, warnings
        assert len(computation_failed) == 1, warnings

    def test_a_replay_that_raises_and_one_that_lands_elsewhere_are_both_reported(self, monkeypatch, warnings_logged):
        """The check that the ops reproduce the change fails for two distinct
        reasons, and sharing one reason between them makes whichever fires
        first silence the other for the rest of the run."""
        monkeypatch.setitem(sys.modules, "jsonpatch", _UnreplayableThenUnfaithfulJsonpatch())
        client = _client_running_tool(bump_counter, calls=2)

        response = client.post("/agui", json=make_request_body("bump", state={"counter": 0}))

        _events_of_completed_run(
            response,
            ran=[bump_counter.name, bump_counter.name],
            reported="counter is now 2",
            left_state={"counter": 2},
        )

        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        not_replayable = [warning for warning in warnings if "could not be replayed" in warning]
        not_faithful = [warning for warning in warnings if "does not reproduce the state" in warning]
        assert len(not_replayable) == 1, warnings
        assert len(not_faithful) == 1, warnings

    def test_the_warning_names_the_thread_and_the_run(self, monkeypatch, warnings_logged):
        """A server carries many conversations at once, so a warning that says
        only that some run degraded cannot be traced back to one."""
        monkeypatch.setitem(sys.modules, "jsonpatch", _BrokenJsonpatch)
        client = _client_running_tool(bump_counter)

        response = client.post(
            "/agui", json=make_request_body("bump", state={"counter": 0}, thread_id="thread-among-many")
        )

        _events_of_completed_run(
            response,
            ran=[bump_counter.name],
            reported="counter is now 1",
            left_state={"counter": 1},
        )

        computation_failed = [
            record.getMessage()
            for record in warnings_logged
            if record.levelno >= logging.WARNING and "could not be computed" in record.getMessage()
        ]
        assert len(computation_failed) == 1, [record.getMessage() for record in warnings_logged]
        assert "thread-among-many" in computation_failed[0], computation_failed[0]
        assert "test-run" in computation_failed[0], computation_failed[0]


# =============================================================================
# The contract both fallback reasons owe the client
# =============================================================================

# A stand-in for the ``jsonpatch`` module that provokes each reason: absent for
# the missing dependency, failing for the computation itself, and answering a
# change with no ops for the empty patch.
_JSONPATCH_STAND_IN: Dict[str, Any] = {
    StateDeltaUnavailable.NO_JSONPATCH: None,
    StateDeltaUnavailable.PATCH_FAILED: _BrokenJsonpatch,
    StateDeltaUnavailable.EMPTY_PATCH: _SilentJsonpatch,
    StateDeltaUnavailable.PATCH_NOT_REPLAYABLE: _UnreplayableJsonpatch,
    StateDeltaUnavailable.PATCH_NOT_FAITHFUL: _UnfaithfulJsonpatch,
}

# The reasons a ``jsonpatch`` stand-in can provoke, which are the reasons whose
# contract is the fallback to a full snapshot.
_FALLBACK_REASONS = sorted(_JSONPATCH_STAND_IN)

_DECLARED_REASONS = sorted(
    value for name, value in vars(StateDeltaUnavailable).items() if name.isupper() and isinstance(value, str)
)

# Every reason the once-per-stream warning registry can be handed. The
# exception carries most of them, but state with no JSON form is reported
# without one to name the cause, so reading the exception alone drops a reason
# out of any coverage check silently. Every string the state module declares
# is read, rather than the ones named a particular way, because a reason added
# under a name no rule here predicted is exactly what would be dropped.
_REGISTRY_REASONS = sorted(
    set(_DECLARED_REASONS)
    | {value for name, value in vars(agui_state).items() if isinstance(value, str) and not name.startswith("__")}
)


class TestEveryDeltaFallbackReasonHonoursTheSameContract:
    """``compute_state_delta`` owes the caller two answers, and every reason it
    can fail for owes both: ``None`` when no event is needed, and the raise
    only when state changed and no patch could be built for it. A reason that
    answered the second where the first was due would ship a full snapshot on
    every later tool call of a run that never touched state."""

    def test_every_reason_the_registry_can_hold_is_covered(self):
        assert sorted({*_JSONPATCH_STAND_IN, *_REASONS_COVERED_BY_ANOTHER_CLASS}) == _REGISTRY_REASONS
        for reason, covering in _REASONS_COVERED_BY_ANOTHER_CLASS.items():
            assert [name for name in vars(covering) if name.startswith("test_")], (
                f"{covering.__name__} is named as covering {reason} and holds no test"
            )

    @pytest.mark.parametrize("reason", _FALLBACK_REASONS)
    def test_unchanged_state_over_several_tool_calls_ships_nothing_extra(self, monkeypatch, reason):
        monkeypatch.setitem(sys.modules, "jsonpatch", _JSONPATCH_STAND_IN[reason])
        client = _client_running_tool(read_counter, calls=3)
        response = client.post("/agui", json=make_request_body("read", state={"counter": 0}))

        events = _events_of_completed_run(
            response,
            ran=[read_counter.name] * 3,
            reported="counter is 0",
            left_state={"counter": 0},
        )
        types = get_event_types(events)
        assert "STATE_DELTA" not in types, types
        # Only the run's opening and closing snapshots, never one per tool call.
        assert types.count("STATE_SNAPSHOT") == 2, _state_events(events)

    @pytest.mark.parametrize("reason", _FALLBACK_REASONS)
    def test_changed_state_reaches_the_client_as_a_snapshot(self, monkeypatch, reason):
        monkeypatch.setitem(sys.modules, "jsonpatch", _JSONPATCH_STAND_IN[reason])
        client = _client_running_tool(bump_counter)
        response = client.post("/agui", json=make_request_body("bump", state={"counter": 0}))

        events = _events_of_completed_run(
            response,
            ran=[bump_counter.name],
            reported="counter is now 1",
            left_state={"counter": 1},
        )
        assert "STATE_DELTA" not in get_event_types(events)
        mid_stream = _snapshots_emitted_for_tool_calls(events)
        assert mid_stream, f"the counter mutation never reached the client: {_state_events(events)}"
        assert _same_state_value(mid_stream[-1]["snapshot"], {"counter": 1}), mid_stream[-1]["snapshot"]


class TestTheTwoArmsOfTheReplayCheckAreTwoReasons:
    """Ops that cannot be applied at all and ops that apply and land somewhere
    else are two failures with two fixes, and a shared reason would leave an
    operator reading about the one that did not happen."""

    @pytest.mark.parametrize(
        ("stand_in", "reason"),
        [
            (_UnreplayableJsonpatch, StateDeltaUnavailable.PATCH_NOT_REPLAYABLE),
            (_UnfaithfulJsonpatch, StateDeltaUnavailable.PATCH_NOT_FAITHFUL),
        ],
        ids=["the replay raises", "the replay lands elsewhere"],
    )
    def test_each_arm_carries_its_own_reason(self, monkeypatch, stand_in, reason):
        monkeypatch.setitem(sys.modules, "jsonpatch", stand_in)
        state = StreamState()
        state.set_state_snapshot({"counter": 0})

        with pytest.raises(StateDeltaUnavailable) as raised:
            state.compute_state_delta({"counter": 1})

        assert raised.value.reason == reason


# =============================================================================
# State values the comparison cannot judge
# =============================================================================


class _RefusesToCompare(str):
    """A state value whose ``==`` raises instead of answering, the way a numpy
    array's does. Subclasses ``str`` so a client can still be sent it."""

    def __eq__(self, other: object) -> bool:
        raise ValueError("truth value of an array is ambiguous")

    def __ne__(self, other: object) -> bool:
        raise ValueError("truth value of an array is ambiguous")

    __hash__ = str.__hash__


class _NeverReachesTheBottom(str):
    """A state value whose ``==`` exhausts the recursion limit, the way a
    structure containing itself does. Subclasses ``str`` so a client can still
    be sent it, which a structure containing itself cannot be.

    ``__ne__`` is spelled out alongside it because ``str`` already defines one:
    left to inherit, ``!=`` would answer with plain string inequality and a
    comparison reaching for it would pass this value untouched.
    """

    def __eq__(self, other: object) -> bool:
        return self == other

    def __ne__(self, other: object) -> bool:
        return self != other

    __hash__ = str.__hash__


# Each builds a value that has a JSON form and so reaches a client intact, but
# that no comparison reading it through ``==`` can survive.
_VALUES_THAT_REFUSE_TO_BE_COMPARED: Dict[str, Callable[[], str]] = {
    "raises instead of comparing": lambda: _RefusesToCompare("ambiguous"),
    "never finishes comparing": lambda: _NeverReachesTheBottom("endless"),
}


class _HasNoJsonForm:
    """A state value the event encoder cannot render at all, the way an open
    file handle or a live database connection left in session_state cannot be."""


@tool
def store_uncomparable_value(kind: str, run_context: Optional[RunContext] = None) -> str:
    """Store the named uncomparable value in the shared state."""
    run_context.session_state["value"] = _VALUES_THAT_REFUSE_TO_BE_COMPARED[kind]()  # type: ignore[union-attr,index]
    return f"stored a value that {kind}"


def _client_storing_then_reading(kind: str, reads: int = 2):
    """An AgentOS whose agent stores ``kind`` then reads state ``reads`` times.

    The reads matter: they ask the comparison about the stored value again on
    every later tool call of the run, which is where a value it judges wrongly
    costs the client an event each time.
    """
    script: List[tuple] = [("tool", store_uncomparable_value.name, {"kind": kind}, "tc_1")]
    script += [("tool", read_counter.name, {}, f"tc_{index + 2}") for index in range(reads)]
    agent = Agent(
        name="state-payload-agent",
        model=_ScriptedModel(script + [("content", "done")]),
        tools=[store_uncomparable_value, read_counter],
    )
    return TestClient(AgentOS(agents=[agent], interfaces=[AGUI(agent=agent)]).get_app())


class TestAValueThatRefusesToBeComparedIsStillJudgedByItsJsonForm:
    """Application tool code owns what lands in session state, so a value there
    can carry an ``__eq__`` that raises or one that never terminates. Asking
    such a value nothing, and reading its encoded form instead, is what makes
    it ordinary: it is judged as exactly as any other value, and the run pays
    nothing for holding it."""

    @pytest.mark.parametrize("kind", sorted(_VALUES_THAT_REFUSE_TO_BE_COMPARED))
    def test_two_of_them_encoding_alike_are_not_a_change(self, kind):
        """Nothing here catches an exception, so a comparison that reached for
        ``==`` could not return at all, and one that caught the exception and
        called the pair changed would answer with ops rather than ``None``."""
        state = StreamState()
        state.set_state_snapshot({"value": _VALUES_THAT_REFUSE_TO_BE_COMPARED[kind]()})

        assert state.compute_state_delta({"value": _VALUES_THAT_REFUSE_TO_BE_COMPARED[kind]()}) is None

    @pytest.mark.parametrize("kind", sorted(_VALUES_THAT_REFUSE_TO_BE_COMPARED))
    @pytest.mark.parametrize("has_jsonpatch", [True, False], ids=["with jsonpatch", "without jsonpatch"])
    def test_the_run_finishes_and_the_later_reads_ship_nothing(self, monkeypatch, kind, has_jsonpatch):
        """An escaping comparison error would reach the client as a RUN_ERROR
        with no RUN_FINISHED and a tool span left open. Judging the value
        changed on every later read would ship the client, on each of them,
        state it was already holding."""
        if has_jsonpatch:
            pytest.importorskip("jsonpatch", reason="jsonpatch not installed")
        else:
            monkeypatch.setitem(sys.modules, "jsonpatch", None)

        client = _client_storing_then_reading(kind)
        response = client.post("/agui", json=make_request_body("store", state={"counter": 0}))

        events = _events_of_completed_run(
            response,
            ran=[store_uncomparable_value.name, read_counter.name, read_counter.name],
            reported="counter is 0",
            left_state={"counter": 0, "value": str(_VALUES_THAT_REFUSE_TO_BE_COMPARED[kind]())},
        )
        told = _state_event_per_tool_call(events)
        assert told[0] is not None, f"the stored value never reached the client: {_state_events(events)}"
        assert told[1:] == [None, None], f"a read that changed nothing still shipped state: {_state_events(events)}"


class TestStateWithNoJsonFormCountsAsChangedAndIsReported:
    """A value the encoder cannot render leaves the comparison with nothing to
    read, and the answer it owes then is ``changed``: a client can discard an
    update it already held, but it cannot recover one that was never sent. An
    unreadable state is not an ordinary change though, so it is also said out
    loud, once, or a defect in the comparison degrades in silence."""

    def _stream_state_handed(self, before: Any, after: Any):
        state = StreamState()
        state.set_state_snapshot({"value": before})
        return state, {"value": after}

    def test_the_caller_is_left_the_exception_it_handles_and_one_warning(self, warnings_logged):
        state, current = self._stream_state_handed("plain", _HasNoJsonForm())

        with pytest.raises(StateDeltaUnavailable) as raised:
            state.compute_state_delta(current)

        assert raised.value.reason in _DECLARED_REASONS
        unreadable = [
            record.getMessage()
            for record in warnings_logged
            if record.levelno >= logging.WARNING and "no JSON form" in record.getMessage()
        ]
        assert len(unreadable) == 1, [record.getMessage() for record in warnings_logged]
        assert "Treating it as changed" in unreadable[0]

    def test_the_same_unreadable_state_is_reported_once_however_many_times_it_is_asked_about(self, warnings_logged):
        state, current = self._stream_state_handed("plain", _HasNoJsonForm())

        for _ in range(3):
            with pytest.raises(StateDeltaUnavailable):
                state.compute_state_delta(current)

        unreadable = [record.getMessage() for record in warnings_logged if "no JSON form" in record.getMessage()]
        assert len(unreadable) == 1, unreadable

    def test_a_self_referential_structure_leaves_only_the_dedicated_exception(self, warnings_logged):
        """A structure that contains itself cannot be JSON-encoded to a client
        at all, and Agno's run loop fails on one before AG-UI state handling is
        reached, so it cannot be driven through a completed run. What the
        comparison owes is asserted here directly: whatever it is handed, the
        only thing leaving ``compute_state_delta`` is the exception the caller
        already handles by sending a full snapshot."""
        snapshot_cycle: Dict[str, Any] = {}
        snapshot_cycle["self"] = snapshot_cycle
        current_cycle: Dict[str, Any] = {}
        current_cycle["self"] = current_cycle
        state, current = self._stream_state_handed(snapshot_cycle, current_cycle)

        with pytest.raises(StateDeltaUnavailable) as raised:
            state.compute_state_delta(current)

        assert raised.value.reason in _DECLARED_REASONS
        assert [record for record in warnings_logged if "no JSON form" in record.getMessage()]


class TestWhatTheDeltaIsMeasuredAgainstIsAnsweredForToo:
    """The baseline a change is described against can be missing and can be
    unrenderable, and neither is the same answer as an unrenderable change: a
    run that has published no state owes the client nothing, and a baseline
    with no JSON form leaves a change that cannot be described rather than one
    that cannot be sent."""

    def test_a_run_that_has_published_no_state_has_no_change_to_describe(self):
        assert StreamState(thread_id="t", run_id="r").compute_state_delta({"counter": 1}) is None

    def test_a_baseline_with_no_json_form_is_a_patch_that_could_not_be_built(self, warnings_logged):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")
        state = StreamState(thread_id="typed-thread", run_id="typed-run")
        state.set_state_snapshot({"value": _HasNoJsonForm()})

        with pytest.raises(StateDeltaUnavailable) as raised:
            state.compute_state_delta({"value": "a value with a JSON form"})

        # Not STATE_NOT_SENDABLE: what the run holds now can be sent, as the
        # full snapshot the caller falls back to.
        assert raised.value.reason == StateDeltaUnavailable.PATCH_FAILED
        unreadable = [record.getMessage() for record in warnings_logged if "no JSON form" in record.getMessage()]
        assert len(unreadable) == 1, [record.getMessage() for record in warnings_logged]
        assert "typed-thread" in unreadable[0] and "typed-run" in unreadable[0], unreadable[0]


@tool
def store_a_value_with_no_json_form(run_context: Optional[RunContext] = None) -> str:
    """Leave a value the event encoder cannot render in the shared state."""
    run_context.session_state["handle"] = _HasNoJsonForm()  # type: ignore[union-attr,index]
    return "stored a live handle"


@tool
def close_the_value_with_no_json_form(run_context: Optional[RunContext] = None) -> str:
    """Replace the unrenderable value with one the encoder can render."""
    run_context.session_state["handle"] = "closed"  # type: ignore[union-attr,index]
    return "the handle is closed"


def _client_storing_then_closing_an_unrenderable_value(reads: int = 2):
    """An AgentOS whose agent stores an unrenderable value, reads state
    ``reads`` times, then replaces the value with a renderable one.

    The reads ask the state path about the unrenderable value again on every
    later tool call, and the close is what a run holding a live handle in
    session state does before it ends: it is also the point where the client is
    owed the change it can be sent, computed against the state it really holds.
    """
    script: List[tuple] = [("tool", store_a_value_with_no_json_form.name, {}, "tc_1")]
    script += [("tool", read_counter.name, {}, f"tc_{index + 2}") for index in range(reads)]
    script.append(("tool", close_the_value_with_no_json_form.name, {}, f"tc_{reads + 2}"))
    agent = Agent(
        name="state-payload-agent",
        model=_ScriptedModel(script + [("content", "done")]),
        tools=[store_a_value_with_no_json_form, read_counter, close_the_value_with_no_json_form],
    )
    return TestClient(AgentOS(agents=[agent], interfaces=[AGUI(agent=agent)]).get_app())


class TestStateWithNoJsonFormIsWithheldRatherThanSent:
    """State the encoder cannot render cannot be sent by any event, a full
    snapshot included, and the encoder runs on the way to the socket, after the
    state path has handed the event over: an event carrying such state takes
    the rest of the response with it, terminal event and all. So the client is
    owed no state event here. It keeps the state it was last sent, the run goes
    on to finish, and the log says what was withheld and for which run.
    """

    def test_the_run_finishes_with_no_unsendable_event_on_the_wire(self):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")
        client = _client_storing_then_closing_an_unrenderable_value()

        response = client.post("/agui", json=make_request_body("store", state={"counter": 0}))

        events = _events_of_completed_run(
            response,
            ran=[
                store_a_value_with_no_json_form.name,
                read_counter.name,
                read_counter.name,
                close_the_value_with_no_json_form.name,
            ],
            reported="the handle is closed",
            left_state={"counter": 0, "handle": "closed"},
        )
        told = _state_event_per_tool_call(events)
        assert told[:3] == [None, None, None], f"state that cannot be encoded still went out: {_state_events(events)}"
        # A delta rather than a snapshot: the baseline stayed where the client
        # is, so the close is describable as a change against what it holds.
        assert told[3] is not None and told[3]["type"] == "STATE_DELTA", _state_events(events)

    def test_both_causes_are_reported_once_each_and_name_the_run(self, warnings_logged):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")
        client = _client_storing_then_closing_an_unrenderable_value()

        response = client.post(
            "/agui", json=make_request_body("store", state={"counter": 0}, thread_id="thread-among-many")
        )
        assert response.status_code == 200, response.text

        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        unreadable = [warning for warning in warnings if "to compare against the last snapshot" in warning]
        withheld = [warning for warning in warnings if "no state event carrying it can be sent" in warning]
        assert len(unreadable) == 1, warnings
        assert len(withheld) == 1, warnings
        for warning in unreadable + withheld:
            assert "thread-among-many" in warning, warning
            assert "test-run" in warning, warning


# The reasons no ``jsonpatch`` stand-in can provoke, because nothing about
# ``jsonpatch`` causes them, against the class that covers each instead. The
# classes themselves rather than their names, and so defined below both of
# them: a name is a string nothing resolves, so renaming or deleting the class
# it spells would leave the coverage guard passing and pointing at nothing.
_REASONS_COVERED_BY_ANOTHER_CLASS = {
    agui_state._STATE_NOT_ENCODABLE: TestStateWithNoJsonFormCountsAsChangedAndIsReported,
    StateDeltaUnavailable.STATE_NOT_SENDABLE: TestStateWithNoJsonFormIsWithheldRatherThanSent,
}


class TestANonDictFinalStateStillFinishesTheRun:
    """The terminal handler hands the run's own ``session_state`` to
    ``client_state``, and nothing constrains it to a dict. A run whose state
    ended up as anything else still owes the client its RUN_FINISHED, so
    ``client_state`` copies what it cannot strip keys from rather than
    raising and taking the whole terminal handler with it."""

    @pytest.mark.parametrize(
        "final_state",
        ["the run left a bare string here", ["a", "list"], 7],
        ids=["string", "list", "int"],
    )
    def test_the_terminal_handler_still_emits_run_finished(self, final_state):
        state = StreamState(thread_id="t", run_id="r", run_state={"counter": 0})
        state.set_state_snapshot(state.run_state)
        chunk = RunCompletedEvent()
        chunk.session_state = final_state

        events = process_completion(chunk, state)

        assert [event.type for event in events][-1] == EventType.RUN_FINISHED, events

    def test_a_non_dict_is_copied_rather_than_shared(self):
        original = ["a", ["nested"]]

        copied = client_state(original)

        assert copied == original
        original[1].append("added")  # type: ignore[union-attr]
        assert copied == ["a", ["nested"]]


# =============================================================================
# A value that is not equal to itself
# =============================================================================


@tool
def set_ratio_to_nan(run_context: Optional[RunContext] = None) -> str:
    """Store a float NaN as the shared ratio."""
    run_context.session_state["ratio"] = float("nan")  # type: ignore[union-attr,index]
    return "ratio is now NaN"


def _client_storing_nan_then_reading(reads: int = 2):
    script: List[tuple] = [("tool", set_ratio_to_nan.name, {}, "tc_1")]
    script += [("tool", read_counter.name, {}, f"tc_{index + 2}") for index in range(reads)]
    agent = Agent(
        name="state-payload-agent",
        model=_ScriptedModel(script + [("content", "done")]),
        tools=[set_ratio_to_nan, read_counter],
    )
    return TestClient(AgentOS(agents=[agent], interfaces=[AGUI(agent=agent)]).get_app())


class TestAValueNotEqualToItselfIsNotAChange:
    """A float NaN is not equal to itself, so a state holding one reads as
    changed on every comparison however long the run goes on. That is the same
    wrong outcome as asking the no-change question too late: the client is sent
    state it already holds after every tool call, forever."""

    def test_a_nan_ships_one_snapshot_not_one_per_tool_call(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "jsonpatch", None)
        client = _client_storing_nan_then_reading()
        response = client.post("/agui", json=make_request_body("set", state={"counter": 0}))

        events = _events_of_completed_run(
            response,
            ran=[set_ratio_to_nan.name, read_counter.name, read_counter.name],
            reported="counter is 0",
            left_state={"counter": 0, "ratio": None},
        )
        # The run's opening snapshot, the one carrying the NaN, and the closing
        # one, never a further snapshot for each read that changed nothing.
        assert get_event_types(events).count("STATE_SNAPSHOT") == 3, _state_events(events)

    def test_a_nan_ships_one_delta_not_one_per_tool_call(self, monkeypatch):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _client_storing_nan_then_reading()
        response = client.post("/agui", json=make_request_body("set", state={"counter": 0}))

        events = _events_of_completed_run(
            response,
            ran=[set_ratio_to_nan.name, read_counter.name, read_counter.name],
            reported="counter is 0",
            left_state={"counter": 0, "ratio": None},
        )
        deltas = [e for e in events if e.get("type") == "STATE_DELTA"]
        assert len(deltas) == 1, _state_events(events)
        assert [op["path"] for op in deltas[0]["delta"]] == ["/ratio"]


# =============================================================================
# The transcript the cookbook README describes
# =============================================================================

AGENT_DEFAULT_RECIPE = {"title": "Untitled recipe", "ingredients": []}


def _cookbook_shaped_client(tmp_path, tool_fn):
    """An AgentOS in the shape ``shared_state.py`` has: a db and a session_state."""
    agent = Agent(
        name="state-payload-agent",
        model=_ScriptedModel([("tool", tool_fn.name, {}, "tc_1"), ("content", "done")]),
        db=SqliteDb(id="agui-state-transcript-db", db_file=str(tmp_path / "agui_state.db")),
        session_state={"recipe": dict(AGENT_DEFAULT_RECIPE)},
        tools=[tool_fn],
    )
    return TestClient(AgentOS(agents=[agent], interfaces=[AGUI(agent=agent)]).get_app())


def _ops_by_path(delta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The delta's ops in path order.

    ``jsonpatch`` walks the changed keys as a set, so their order varies from
    one process to the next. Sorting pins which ops a delta carries and what
    each one says, without pinning an order the library never promised.
    """
    return sorted(delta["delta"], key=lambda op: op["path"])


def _first_snapshot(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    snapshots = [e for e in events if e.get("type") == "STATE_SNAPSHOT"]
    assert snapshots, f"the run sent no snapshot for a client to open on: {get_event_types(events)}"
    return snapshots[0]["snapshot"]


def _only_delta(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    deltas = [e for e in events if e.get("type") == "STATE_DELTA"]
    assert len(deltas) == 1, _state_events(events)
    return deltas[0]


class TestTheFirstDeltaCarriesTheStateTheRunBeganWith:
    """Pins the transcript the ``16_agui`` cookbook README documents, so an
    edit to either the wire behaviour or the prose shows up against the other.
    The README says of an agent with its own ``session_state``:

        "The agent's own `session_state` seeds the session row when that row
        is created, and each run merges the row in under the request's own
        state, which wins; the row is created once per `threadId`, so an edit
        to the example's initial recipe shows up in a new conversation and
        never in one already under way. Each delta is measured against the
        previous payload, so unless the request already sent all of it, the
        first delta adds what the merge brought in and reports more than the
        tool call itself touched."

    The opening snapshot is the request state, while the run starts from that
    merged with the session row, and the request's own state wins over what
    the row holds. So the merge lands in the first delta alongside whatever
    the tool did: the first test below creates the row, which is where the
    agent's own state seeds it, and the second reads that same row back.
    """

    def test_the_first_delta_also_adds_the_agent_default_state(self, tmp_path):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        client = _cookbook_shaped_client(tmp_path, bump_counter)
        response = client.post("/agui", json=make_request_body("bump", state={"counter": 7}, thread_id="recipe-thread"))

        events = _events_of_completed_run(
            response,
            ran=[bump_counter.name],
            reported="counter is now 8",
            left_state={"recipe": AGENT_DEFAULT_RECIPE, "counter": 8},
        )
        opened_on = _first_snapshot(events)
        assert _same_state_value(opened_on, {"counter": 7}), opened_on
        # The tool touched /counter only; /recipe is the agent default arriving
        # with it because the delta's baseline is what the client sent.
        ops = _ops_by_path(_only_delta(events))
        assert _same_state_value(
            ops,
            [
                {"op": "replace", "path": "/counter", "value": 8},
                {"op": "add", "path": "/recipe", "value": AGENT_DEFAULT_RECIPE},
            ],
        ), ops

    def test_the_first_delta_also_adds_the_stored_session_row(self, tmp_path):
        pytest.importorskip("jsonpatch", reason="jsonpatch not installed")

        _events_of_completed_run(
            _cookbook_shaped_client(tmp_path, bump_counter).post(
                "/agui", json=make_request_body("bump", state={"counter": 7}, thread_id="recipe-thread")
            ),
            ran=[bump_counter.name],
            reported="counter is now 8",
            left_state={"recipe": AGENT_DEFAULT_RECIPE, "counter": 8},
        )

        response = _cookbook_shaped_client(tmp_path, read_counter).post(
            "/agui", json=make_request_body("read", state={"client_only": "kept"}, thread_id="recipe-thread")
        )

        events = _events_of_completed_run(
            response,
            ran=[read_counter.name],
            reported="counter is 8",
            left_state={"recipe": AGENT_DEFAULT_RECIPE, "counter": 8, "client_only": "kept"},
        )
        opened_on = _first_snapshot(events)
        assert _same_state_value(opened_on, {"client_only": "kept"}), opened_on
        # read_counter changes nothing, so every op here is the merge: /counter
        # off the session row the first run persisted, /recipe the agent
        # default. A delta still fires, reporting keys no tool call touched.
        ops = _ops_by_path(_only_delta(events))
        assert _same_state_value(
            ops,
            [
                {"op": "add", "path": "/counter", "value": 8},
                {"op": "add", "path": "/recipe", "value": AGENT_DEFAULT_RECIPE},
            ],
        ), ops


# =============================================================================
# Tool call arguments streamed to the client as they are produced
#
# Providers hand the run loop one delta per fragment of a tool call's argument
# string, and Agno now emits a run event for each. Those fragments arrive
# before Agno announces the finished call, so the wire has to open the call
# from the first fragment and add arguments from each one after it. These drive
# a real run over a fragmenting offline model so what is asserted is the
# sequence a client decodes.
# =============================================================================


class _FragmentingModel(Model):
    """Streams a turn's tool calls in fragments, the way a provider does.

    Each turn is ``("content", text)`` or ``("tools", [(name, args, id), ...],
    chunk_size, preamble)``. A tool turn puts a call's id and function name on
    its own first fragment, which carries no arguments at all, then interleaves
    the calls' argument chunks so several calls in one turn arrive at once. A
    preamble streams that text ahead of the fragments, the way a model that
    talks before it calls does.
    """

    def __init__(self, script: List[tuple]):
        super().__init__(id="fragmenting", name="fragmenting", provider="test")
        self._script = list(script)
        self._index = 0

    def _next_turn(self) -> List[ModelResponse]:
        assert self._index < len(self._script), (
            f"the run asked for model turn {self._index + 1} of a {len(self._script)}-turn script"
        )
        turn = self._script[self._index]
        self._index += 1
        if turn[0] == "content":
            reply = ModelResponse(content=turn[1], role="assistant")
            reply.event = ModelResponseEvent.assistant_response.value
            return [reply]

        _, calls, chunk_size = turn[:3]
        preamble = turn[3] if len(turn) > 3 else ""
        deltas: List[ModelResponse] = []
        if preamble:
            deltas.append(ModelResponse(content=preamble, role="assistant"))
        for position, (name, args, tool_call_id) in enumerate(calls):
            deltas.append(_arg_fragment(position, "", tool_call_id=tool_call_id, tool_name=name))
        chunked = [_chunked(json.dumps(args), chunk_size) for _, args, _ in calls]
        for step in range(max(len(chunks) for chunks in chunked)):
            for position, chunks in enumerate(chunked):
                if step < len(chunks):
                    deltas.append(_arg_fragment(position, chunks[step]))
        return deltas

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield from self._next_turn()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        for delta in self._next_turn():
            yield delta

    def invoke(self, *args, **kwargs) -> ModelResponse:
        raise AssertionError("this model exists to be streamed")

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        raise AssertionError("this model exists to be streamed")

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
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


def _arg_fragment(
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


def _chunked(text: str, size: int) -> List[str]:
    return [text[position : position + size] for position in range(0, len(text), size)]


@tool
def save_line(line: str, run_context: Optional[RunContext] = None) -> str:
    """Store one line of a document.

    Args:
        line: the line to store
    """
    session_state = run_context.session_state  # type: ignore[union-attr]
    session_state["lines"] = session_state.get("lines", []) + [line]
    return f"stored {len(session_state['lines'])} line(s)"


@tool
def save_title(title: str, run_context: Optional[RunContext] = None) -> str:
    """Store the document title.

    Args:
        title: the title to store
    """
    run_context.session_state["title"] = title  # type: ignore[union-attr]
    return f"titled {title}"


def _fragmenting_client(script: List[tuple], tools: List[Any], tool_call_limit: Optional[int] = None):
    agent = Agent(
        name="fragmenting-agent",
        model=_FragmentingModel(script),
        tools=tools,
        tool_call_limit=tool_call_limit,
    )
    agent_os = AgentOS(agents=[agent], interfaces=[AGUI(agent=agent)])
    return TestClient(agent_os.get_app())


def _tool_call_wire(events: List[Dict[str, Any]], tool_call_id: str) -> List[Dict[str, Any]]:
    """Every event on the wire that names one tool call, in order."""
    return [event for event in events if event.get("toolCallId") == tool_call_id]


def _raw_passthroughs_of(events: List[Dict[str, Any]], agno_event: str) -> List[Dict[str, Any]]:
    """Every RAW event carrying one Agno event straight through to the client.

    A RAW event is what an Agno event with no handler becomes: the whole event
    dict, for the client to make what it can of.
    """
    return [
        event
        for event in events
        if event.get("type") == "RAW"
        and isinstance(event.get("event"), dict)
        and event["event"].get("event") == agno_event
    ]


def _results_for(events: List[Dict[str, Any]], tool_call_id: str) -> List[Any]:
    """What the client was told each of one call's results was, decoded."""
    return [
        json.loads(event["content"])
        for event in events
        if event.get("type") == "TOOL_CALL_RESULT" and event.get("toolCallId") == tool_call_id
    ]


def _args_deltas(events: List[Dict[str, Any]], tool_call_id: str) -> List[str]:
    return [
        event["delta"]
        for event in events
        if event.get("type") == "TOOL_CALL_ARGS" and event.get("toolCallId") == tool_call_id
    ]


def _assert_the_client_accepts_the_tool_call_spans(events: List[Dict[str, Any]]) -> None:
    """Replay the wire under the rules the AG-UI client's own verifier applies.

    The client keeps one entry per tool call id, added by TOOL_CALL_START and
    deleted by TOOL_CALL_END, and it throws rather than renders when a start
    names an id that already has an entry, when arguments or an end name an id
    that has none, or when a run finishes with an entry left. Deletion on end
    is why the same id may open again afterwards: it is a second call, not a
    second start of the one that closed.

    A run that ends in error is a run that ended, so an entry left open at
    RUN_ERROR is the same unclosed span as one left open at RUN_FINISHED: the
    client throws for either.
    """
    open_calls: List[str] = []
    for event in events:
        kind = event.get("type")
        tool_call_id = event.get("toolCallId")
        if kind == "TOOL_CALL_START":
            assert tool_call_id not in open_calls, f"a second TOOL_CALL_START for the open call {tool_call_id!r}"
            open_calls.append(tool_call_id)
        elif kind == "TOOL_CALL_ARGS":
            assert tool_call_id in open_calls, f"TOOL_CALL_ARGS for {tool_call_id!r}, which is not open"
        elif kind == "TOOL_CALL_END":
            assert tool_call_id in open_calls, f"TOOL_CALL_END for {tool_call_id!r}, which is not open"
            open_calls.remove(tool_call_id)
        elif kind in ("RUN_FINISHED", "RUN_ERROR"):
            assert not open_calls, f"{kind} left the calls {open_calls} open"


class TestToolCallArgumentsReachTheClientAsTheyAreProduced:
    """A client rendering a tool call while it is still running needs the
    arguments in pieces, so one TOOL_CALL_ARGS per fragment is the point: a
    single event carrying the finished blob is what the client used to get and
    is what these tests exist to rule out.
    """

    def test_each_fragment_becomes_its_own_args_event_under_one_start(self):
        line = "the sea is wide and the boat is small"
        args = json.dumps({"line": line})
        client = _fragmenting_client(
            [("tools", [(save_line.name, {"line": line}, "call_line")], 5), ("content", "done")],
            [save_line],
        )

        response = client.post("/agui", json=make_request_body("write", state={"lines": []}))
        events = _events_of_completed_run(
            response, ran=[save_line.name], reported="stored 1 line(s)", left_state={"lines": [line]}
        )

        deltas = _args_deltas(events, "call_line")
        assert len(deltas) == len(_chunked(args, 5))
        assert len(deltas) > 1, "the client got the arguments in one piece, so nothing was streamed"
        assert "".join(deltas) == args
        assert json.loads("".join(deltas)) == {"line": line}

    def test_the_announcement_after_the_fragments_repeats_nothing(self):
        line = "a second look at the same call"
        args = json.dumps({"line": line})
        client = _fragmenting_client(
            [("tools", [(save_line.name, {"line": line}, "call_line")], 5), ("content", "done")],
            [save_line],
        )

        response = client.post("/agui", json=make_request_body("write", state={"lines": []}))
        events = _events_of_completed_run(
            response, ran=[save_line.name], reported="stored 1 line(s)", left_state={"lines": [line]}
        )

        wire = [event["type"] for event in _tool_call_wire(events, "call_line")]
        assert wire.count("TOOL_CALL_START") == 1, wire
        assert wire.count("TOOL_CALL_END") == 1, wire
        # Agno announces the finished call after the fragments; the whole
        # argument string must not arrive again alongside them.
        deltas = _args_deltas(events, "call_line")
        assert len(deltas) > 1, "the arguments arrived in one piece, so the announcement carried them"
        assert "".join(deltas) == args
        assert args not in deltas, "the announcement resent the whole argument string"
        # And the wire stays in protocol order: start, arguments, end.
        assert wire[0] == "TOOL_CALL_START"
        assert wire.index("TOOL_CALL_END") > max(
            position for position, kind in enumerate(wire) if kind == "TOOL_CALL_ARGS"
        )

    def test_the_call_opens_from_its_first_fragment_not_from_the_announcement(self):
        line = "opened early"
        client = _fragmenting_client(
            [("tools", [(save_line.name, {"line": line}, "call_line")], 4), ("content", "done")],
            [save_line],
        )

        response = client.post("/agui", json=make_request_body("write", state={"lines": []}))
        events = _events_of_completed_run(
            response, ran=[save_line.name], reported="stored 1 line(s)", left_state={"lines": [line]}
        )

        start = next(event for event in events if event.get("type") == "TOOL_CALL_START")
        assert start["toolCallName"] == save_line.name
        # A start with no parent is a protocol violation, and the parent has to
        # be a message the client has already been told about.
        parent = start["parentMessageId"]
        assert parent
        # Unmapped, every fragment reached the client as a raw event it has no
        # way to render, one per fragment.
        raw = [event.get("event", {}).get("event") for event in events if event.get("type") == "RAW"]
        assert "ToolCallArgsDelta" not in raw, raw
        assert len(_args_deltas(events, "call_line")) > 1
        opened = [
            position
            for position, event in enumerate(events)
            if event.get("type") == "TEXT_MESSAGE_START" and event.get("messageId") == parent
        ]
        assert opened and opened[0] < events.index(start)

    def test_two_calls_in_one_turn_stay_apart_on_the_wire(self):
        line = "the first of two"
        title = "a longer title than the line, so it keeps streaming after the line runs out"
        client = _fragmenting_client(
            [
                (
                    "tools",
                    [(save_line.name, {"line": line}, "call_line"), (save_title.name, {"title": title}, "call_title")],
                    6,
                ),
                ("content", "done"),
            ],
            [save_line, save_title],
        )

        response = client.post("/agui", json=make_request_body("write", state={"lines": []}))
        events = _events_of_completed_run(
            response,
            ran=[save_line.name, save_title.name],
            left_state={"lines": [line], "title": title},
        )

        assert json.loads("".join(_args_deltas(events, "call_line"))) == {"line": line}
        assert json.loads("".join(_args_deltas(events, "call_title"))) == {"title": title}
        starts = {
            event["toolCallId"]: event["toolCallName"] for event in events if event.get("type") == "TOOL_CALL_START"
        }
        assert starts == {"call_line": save_line.name, "call_title": save_title.name}
        # Each call opens before any of its own arguments and closes after the
        # last of them, whatever the other call was doing in between.
        for tool_call_id in ("call_line", "call_title"):
            wire = [event["type"] for event in _tool_call_wire(events, tool_call_id)]
            assert wire[0] == "TOOL_CALL_START", wire
            assert wire.count("TOOL_CALL_START") == 1, wire
            assert wire.count("TOOL_CALL_ARGS") > 1, wire
            assert wire.index("TOOL_CALL_END") > max(
                position for position, kind in enumerate(wire) if kind == "TOOL_CALL_ARGS"
            ), wire

    def test_a_call_whose_arguments_never_streamed_still_carries_them_whole(self, agent_client):
        """A provider that hands the run loop no argument text leaves the
        announcement as the only thing that can carry the arguments, and it
        still carries all of them in one event, exactly as before."""
        client, agent = agent_client
        tool_mock = MagicMock()
        tool_mock.tool_call_id = "call_unstreamed"
        tool_mock.tool_name = "save_line"
        tool_mock.tool_args = {"line": "never fragmented"}
        tool_mock.result = "stored"

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallStartedEvent(content="", tool=tool_mock)
            yield ToolCallCompletedEvent(content="", tool=tool_mock)
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        wire = [event["type"] for event in _tool_call_wire(events, "call_unstreamed")]
        assert wire.count("TOOL_CALL_START") == 1, wire
        assert _args_deltas(events, "call_unstreamed") == [json.dumps({"line": "never fragmented"})]

    def test_a_provider_that_does_not_fragment_sends_the_arguments_once(self):
        """A provider that hands over a finished call rather than fragments of
        one leaves a single fragment carrying the whole argument string, and
        the client gets a single TOOL_CALL_ARGS, exactly as before."""
        client = _real_run_client(mutates=True)

        response = client.post("/agui", json=make_request_body("bump", state={"counter": 0}))
        events = _events_of_completed_run(
            response, ran=[bump_counter.name], reported="counter is now 1", left_state={"counter": 1}
        )

        wire = [event["type"] for event in _tool_call_wire(events, "tc_1")]
        assert wire.count("TOOL_CALL_START") == 1, wire
        assert _args_deltas(events, "tc_1") == ["{}"]

    def test_fragments_arriving_under_an_open_message_parent_to_it(self):
        """The fragments arrive earlier than the announcement used to, so what
        they close and parent to is whatever text message is open at that
        moment, not a fresh empty one."""
        line = "after a word of warning"
        client = _fragmenting_client(
            [
                ("tools", [(save_line.name, {"line": line}, "call_line")], 5, "Let me write that down. "),
                ("content", "done"),
            ],
            [save_line],
        )

        response = client.post("/agui", json=make_request_body("write", state={"lines": []}))
        events = _events_of_completed_run(
            response, ran=[save_line.name], reported="stored 1 line(s)", left_state={"lines": [line]}
        )

        types = get_event_types(events)
        start = next(event for event in events if event.get("type") == "TOOL_CALL_START")
        spoken = next(
            event
            for event in events
            if event.get("type") == "TEXT_MESSAGE_CONTENT" and "Let me write that down." in event["delta"]
        )
        assert start["parentMessageId"] == spoken["messageId"], (
            "the call was parented to a message the preamble was not spoken in"
        )
        # That message is closed before the call opens, and no empty stand-in
        # was minted alongside it.
        ended = [
            position
            for position, event in enumerate(events)
            if event.get("type") == "TEXT_MESSAGE_END" and event.get("messageId") == spoken["messageId"]
        ]
        assert ended and ended[0] < events.index(start), types
        opened = [event for event in events if event.get("type") == "TEXT_MESSAGE_START"]
        assert [event["messageId"] for event in opened].count(spoken["messageId"]) == 1
        assert len(opened) == 2, [event["messageId"] for event in opened]
        assert len(_args_deltas(events, "call_line")) > 1

    def test_a_paused_call_whose_arguments_streamed_is_not_rendered_twice(self, agent_client):
        """A client tool pauses the run, and the terminal handler renders the
        paused calls for the frontend to execute. A call the fragments already
        opened, carried and closed must not be rendered again there."""
        client, agent = agent_client
        paused_tool = ToolExecution(
            tool_call_id="call_client",
            tool_name="generate_haiku",
            tool_args={"line": "streamed"},
            external_execution_required=True,
        )

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallArgsDeltaEvent(
                tool_call_id="call_client", tool_name="generate_haiku", tool_args_delta='{"line":'
            )
            yield ToolCallArgsDeltaEvent(
                tool_call_id="call_client", tool_name="generate_haiku", tool_args_delta='"streamed"}'
            )
            yield RunPausedEvent(tools=[paused_tool])

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        wire = [event["type"] for event in _tool_call_wire(events, "call_client")]
        assert wire.count("TOOL_CALL_START") == 1, wire
        assert wire.count("TOOL_CALL_END") == 1, wire
        assert _args_deltas(events, "call_client") == ['{"line":', '"streamed"}']
        # And no stand-in parent message was minted for a call that never
        # needed rendering.
        assert [event["type"] for event in events].count("TEXT_MESSAGE_START") == 1

    def test_a_paused_call_that_never_streamed_is_still_rendered(self, agent_client):
        """The same terminal handler, for a call with no fragments: it opens
        the call, carries the whole argument string and closes it, as before."""
        client, agent = agent_client
        paused_tool = ToolExecution(
            tool_call_id="call_client",
            tool_name="generate_haiku",
            tool_args={"line": "unstreamed"},
            external_execution_required=True,
        )

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunPausedEvent(tools=[paused_tool])

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        wire = [event["type"] for event in _tool_call_wire(events, "call_client")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END"], wire
        assert _args_deltas(events, "call_client") == [json.dumps({"line": "unstreamed"})]


# =============================================================================
# One call id, one call on the wire
#
# Three things can be the first sight of a tool call: an argument fragment,
# Agno's announcement of the finished call, and the terminal handler rendering
# a paused run's pending calls. Whichever sees a call first is the one that
# opens it, and the others have to recognise it as open, or already closed, and
# stay quiet. A client cannot repair any of this: a second start for an open
# call, or arguments for one that has ended, is where its verifier throws and
# takes the rest of the run with it.
# =============================================================================


def _announced(tool_call_id: str, tool_name: str, tool_args: Dict[str, Any], result: str = "stored") -> Any:
    """Agno's record of a finished call, as its announcement carries it."""
    tool = MagicMock()
    tool.tool_call_id = tool_call_id
    tool.tool_name = tool_name
    tool.tool_args = tool_args
    tool.result = result
    return tool


class TestOneCallIdOpensOneCallWhicheverOpenerSeesItFirst:
    def test_a_fragment_after_the_announcement_opens_no_second_call(self, agent_client):
        """The announcement got there first and carried the whole argument
        string, so a fragment behind it has nothing to add: opening the call
        again would give the client two calls under one id, and passing the
        fragment on would append to arguments that are already complete."""
        client, agent = agent_client
        args = {"line": "announced first"}
        tool = _announced("call_late_fragment", "save_line", args)

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallStartedEvent(content="", tool=tool)
            yield ToolCallArgsDeltaEvent(
                tool_call_id="call_late_fragment", tool_name="save_line", tool_args_delta='{"line":'
            )
            yield ToolCallCompletedEvent(content="", tool=tool)
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        wire = [event["type"] for event in _tool_call_wire(events, "call_late_fragment")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"], wire
        assert _args_deltas(events, "call_late_fragment") == [json.dumps(args)]

    def test_an_announcement_behind_an_open_call_leaves_dropped_fragments_dropped(self, agent_client):
        """A call some of whose fragments never went out, which is the case the
        run warns about when it can place no call for a fragment or the
        provider wrote the arguments as a structure. TOOL_CALL_ARGS only ever
        appends, so the announcement behind an open call cannot carry the whole
        string without doubling what the client already holds. What the client
        is left with is the fragments that did go out, and nothing more."""
        client, agent = agent_client
        streamed = 'piece never went out"}'
        tool = _announced("call_short", "save_line", {"line": "the opening piece never went out"})

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            # The opening fragment is the one that never reached the client.
            yield ToolCallArgsDeltaEvent(tool_call_id="call_short", tool_name="save_line", tool_args_delta=streamed)
            yield ToolCallStartedEvent(content="", tool=tool)
            yield ToolCallCompletedEvent(content="", tool=tool)
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        wire = [event["type"] for event in _tool_call_wire(events, "call_short")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"], wire
        assert "".join(_args_deltas(events, "call_short")) == streamed
        with pytest.raises(json.JSONDecodeError):
            json.loads(streamed)

    def test_an_id_reused_after_its_call_ended_opens_a_new_call(self, agent_client):
        """A provider is free to hand the same call id to a later call in the
        same run, and by then the first call has ended. The fragments of the
        second one open a call of their own: adding them to the one that closed
        is arguments after an end, which the client refuses."""
        client, agent = agent_client
        first = _announced("call_reused", "save_line", {"line": "one"}, result="stored 1")
        second = _announced("call_reused", "save_line", {"line": "two"}, result="stored 2")

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallArgsDeltaEvent(tool_call_id="call_reused", tool_name="save_line", tool_args_delta='{"line":')
            yield ToolCallArgsDeltaEvent(tool_call_id="call_reused", tool_name="save_line", tool_args_delta='"one"}')
            yield ToolCallCompletedEvent(content="", tool=first)
            yield ToolCallArgsDeltaEvent(tool_call_id="call_reused", tool_name="save_line", tool_args_delta='{"line":')
            yield ToolCallArgsDeltaEvent(tool_call_id="call_reused", tool_name="save_line", tool_args_delta='"two"}')
            yield ToolCallCompletedEvent(content="", tool=second)
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        wire = [event["type"] for event in _tool_call_wire(events, "call_reused")]
        assert wire == [
            "TOOL_CALL_START",
            "TOOL_CALL_ARGS",
            "TOOL_CALL_ARGS",
            "TOOL_CALL_END",
            "TOOL_CALL_RESULT",
            "TOOL_CALL_START",
            "TOOL_CALL_ARGS",
            "TOOL_CALL_ARGS",
            "TOOL_CALL_END",
            "TOOL_CALL_RESULT",
        ], wire
        assert _args_deltas(events, "call_reused") == ['{"line":', '"one"}', '{"line":', '"two"}']
        results = [json.loads(event["content"]) for event in events if event.get("type") == "TOOL_CALL_RESULT"]
        assert results == ["stored 1", "stored 2"], results

    def test_a_first_fragment_carrying_no_arguments_opens_nothing(self, agent_client):
        """A provider names a call on a fragment that carries no argument text
        at all. There is nothing to say about the call yet, so nothing goes out
        for it, and the announcement behind it is still the opener that carries
        the arguments. Opening on that empty fragment instead leaves the client
        a call that starts and ends with no arguments between."""
        client, agent = agent_client
        args = {"line": "arguments came later"}
        tool = _announced("call_empty_first", "save_line", args)

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallArgsDeltaEvent(tool_call_id="call_empty_first", tool_name="save_line", tool_args_delta="")
            yield ToolCallStartedEvent(content="", tool=tool)
            yield ToolCallCompletedEvent(content="", tool=tool)
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        wire = [event["type"] for event in _tool_call_wire(events, "call_empty_first")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"], wire
        assert _args_deltas(events, "call_empty_first") == [json.dumps(args)]

    def test_a_call_only_an_empty_fragment_ever_named_reaches_the_client_at_all(self, agent_client):
        """Nothing else ever mentions the call, so the run has said nothing
        about it and neither does the wire, rather than an empty pair of
        brackets around no arguments."""
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallArgsDeltaEvent(tool_call_id="call_named_only", tool_name="save_line", tool_args_delta="")
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        assert "RUN_FINISHED" in get_event_types(events), get_event_types(events)
        assert _tool_call_wire(events, "call_named_only") == []

    def test_a_call_only_the_announcement_ever_mentions_is_carried_as_before(self, agent_client):
        """The case with no fragments in it at all: the announcement opens the
        call and carries every argument in one event, and the completion closes
        it. None of the reconciling above shows up here."""
        client, agent = agent_client
        args = {"line": "no fragments anywhere"}
        tool = _announced("call_announced_only", "save_line", args)

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallStartedEvent(content="", tool=tool)
            yield ToolCallCompletedEvent(content="", tool=tool)
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        wire = [event["type"] for event in _tool_call_wire(events, "call_announced_only")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"], wire
        assert _args_deltas(events, "call_announced_only") == [json.dumps(args)]

    def test_a_completion_for_a_call_nothing_opened_ends_nothing(self, agent_client):
        """A run configured to skip the announcement leaves a completion as the
        only sight of a call whose arguments never streamed. There is no open
        call to close, and an end for one the client does not hold open is
        where its verifier stops reading, so the completion passes in silence
        and the rest of the run still reaches the client."""
        client, agent = agent_client
        tool = _announced("call_never_opened", "save_line", {"line": "unannounced"})

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallCompletedEvent(content="", tool=tool)
            yield RunContentEvent(content="answered anyway")
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        assert _tool_call_wire(events, "call_never_opened") == []
        spoken = [event["delta"] for event in events if event.get("type") == "TEXT_MESSAGE_CONTENT"]
        assert spoken == ["answered anyway"], spoken
        assert "RUN_FINISHED" in get_event_types(events)

    def test_a_paused_call_the_announcement_opened_is_not_rendered_twice(self, agent_client):
        """The terminal handler renders a paused run's pending calls so the
        frontend can execute them. A call already opened, carried and closed on
        the wire is not pending anything the client has not seen, whichever
        opener put it there."""
        client, agent = agent_client
        args = {"line": "announced then paused"}
        tool = _announced("call_paused", "generate_haiku", args)
        paused_tool = ToolExecution(
            tool_call_id="call_paused",
            tool_name="generate_haiku",
            tool_args=args,
            external_execution_required=True,
        )

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallStartedEvent(content="", tool=tool)
            yield RunPausedEvent(tools=[paused_tool])

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        wire = [event["type"] for event in _tool_call_wire(events, "call_paused")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END"], wire
        assert _args_deltas(events, "call_paused") == [json.dumps(args)]


class TestTheFragmentsAreTheClientsCopyOfTheArguments:
    """What the announcement of a finished call does about the fragments.

    Nothing. A client's copy of a call's arguments is the text the provider
    streamed, which is what a streaming client reads them out of, and the
    announcement neither repeats that text nor sits in judgement on it: the
    arguments the run ends up holding differ from the text a healthy provider
    sent in more ways than any comparison can allow for, from a parameter the
    run defaulted to a literal it read as a Python value, and a client told
    such a call failed cannot act on it at all. What a call did is what its
    result event says it did.
    """

    def _streamed_then_announced(self, agent_client, fragments: List[str], tool_args: Any):
        client, agent = agent_client
        tool = _announced("call_checked", "save_line", tool_args)

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            for fragment in fragments:
                yield ToolCallArgsDeltaEvent(
                    tool_call_id="call_checked", tool_name="save_line", tool_args_delta=fragment
                )
            yield ToolCallStartedEvent(content="", tool=tool)
            yield ToolCallCompletedEvent(content="", tool=tool)
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))
        return parse_sse_events(response.text)

    def test_arguments_the_provider_spelled_differently_are_left_alone(self, agent_client):
        """The check is on the JSON the client parses, not on its characters.

        A provider writes its argument JSON with whatever spacing it likes,
        none of which the client can see, so the fragments here spell the same
        object Agno's own encoder would spell with spaces after its colons.
        """
        args = {"line": "spelled tight"}
        fragments = ['{"line":', '"spelled tight"}']
        assert "".join(fragments) != json.dumps(args), "the fixture no longer differs from the canonical spelling"

        events = self._streamed_then_announced(agent_client, fragments, args)

        _assert_the_client_accepts_the_tool_call_spans(events)
        # Nothing was added: the fragments are all the arguments the client got,
        # and the call ran its ordinary course to a result.
        assert _args_deltas(events, "call_checked") == fragments
        wire = [event["type"] for event in _tool_call_wire(events, "call_checked")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"]
        assert _results_for(events, "call_checked") == ["stored"]

    def test_a_provider_that_offers_its_arguments_twice_still_carries_the_calls_result(
        self, agent_client, warnings_logged
    ):
        """A provider stream that restarts offers argument text a second time.

        TOOL_CALL_ARGS appends and no AG-UI event replaces, so the client's
        copy is the text twice over and nothing can put it right. What the call
        did is still reported: the result is the run's own, and a client told
        the truth about the result can act on it, which one told the call
        failed cannot.
        """
        args = {"line": "written once"}
        whole = json.dumps(args)
        events = self._streamed_then_announced(agent_client, [whole, whole], args)

        _assert_the_client_accepts_the_tool_call_spans(events)
        assert _args_deltas(events, "call_checked") == [whole, whole]
        wire = [event["type"] for event in _tool_call_wire(events, "call_checked")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"]
        assert _results_for(events, "call_checked") == ["stored"]
        assert wire.count("TOOL_CALL_END") == 1, wire
        warnings = [record.getMessage() for record in warnings_logged if record.levelno >= logging.WARNING]
        assert warnings == [], warnings

    @pytest.mark.parametrize(
        ("fragment", "tool_args"),
        [
            ('{"line": "hello"}', {"line": "hello"}),
            ('{"flag": "true"}', {"flag": True}),
            ('{"flag": " FALSE "}', {"flag": False}),
            ('{"flag": "none"}', {"flag": None}),
            ('{"flag": "yes"}', {"flag": True}),
            ('{"count": 1}', {"count": True}),
            ("[]", None),
            ('{"line": "hello"}', {"line": "hello", "run_context": "<injected>"}),
        ],
        ids=[
            "arguments the run holds as they were sent",
            "a literal the run read as a Python value",
            "the same literal in another casing",
            "a literal the run read as nothing at all",
            "a string the run coerced to something else",
            "a whole number where the run holds a boolean",
            "a call with no parameters the provider sent as an empty list",
            "a parameter the run filled in for itself",
        ],
    )
    def test_arguments_the_run_holds_differently_still_reach_the_client_as_the_calls_own(
        self, agent_client, fragment, tool_args
    ):
        """Every one of these is a healthy call, and each leaves the run
        holding arguments the fragments never spelled: Agno reads the strings
        "true", "false" and "none" out of a provider's top-level arguments as
        Python values, a provider names a no-parameter call with whatever it
        likes, and the run fills parameters in for itself. The client is left
        the text it was streamed and the call runs its ordinary course to its
        own result.
        """
        events = self._streamed_then_announced(agent_client, [fragment], tool_args)

        _assert_the_client_accepts_the_tool_call_spans(events)
        assert _args_deltas(events, "call_checked") == [fragment]
        wire = [event["type"] for event in _tool_call_wire(events, "call_checked")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"], wire
        assert _results_for(events, "call_checked") == ["stored"]

    def test_a_paused_call_whose_fragments_left_a_prefix_is_still_closed_once(self, agent_client):
        """A paused call is never started and never completed, and the terminal
        handler renders only the calls the stream never carried, so closing the
        spans is all that is left to do for one the fragments opened. The
        client is left holding the prefix that was streamed, which is as much
        of the arguments as the provider ever sent, under a call it holds
        closed rather than pending."""
        client, agent = agent_client
        paused_tool = ToolExecution(
            tool_call_id="call_flight",
            tool_name="book_flight",
            tool_args={"dest": "Oslo"},
            requires_confirmation=True,
        )

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallArgsDeltaEvent(
                tool_call_id="call_flight", tool_name="book_flight", tool_args_delta='{"dest": "Osl'
            )
            yield RunPausedEvent(tools=[paused_tool])

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("fly"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        wire = [event["type"] for event in _tool_call_wire(events, "call_flight")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END"], wire
        assert _args_deltas(events, "call_flight") == ['{"dest": "Osl']
        # And it is not rendered a second time: a second call under the same id
        # is where a client's verifier stops reading the run.
        assert wire.count("TOOL_CALL_START") == 1, wire

    def test_a_paused_call_whose_fragments_carried_its_arguments_is_left_alone(self, agent_client):
        """The same path for a call whose fragments did reassemble: nothing to
        report, nothing to close early, and no second render."""
        paused_tool = ToolExecution(
            tool_call_id="call_flight",
            tool_name="book_flight",
            tool_args={"dest": "Oslo"},
            requires_confirmation=True,
        )
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallArgsDeltaEvent(
                tool_call_id="call_flight", tool_name="book_flight", tool_args_delta='{"dest": '
            )
            yield ToolCallArgsDeltaEvent(tool_call_id="call_flight", tool_args_delta='"Oslo"}')
            yield RunPausedEvent(tools=[paused_tool])

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("fly"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        wire = [event["type"] for event in _tool_call_wire(events, "call_flight")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_ARGS", "TOOL_CALL_END"], wire
        assert json.loads("".join(_args_deltas(events, "call_flight"))) == {"dest": "Oslo"}

    def test_a_fragment_naming_no_tool_leaves_the_call_to_the_announcement(self):
        """A call is opened once and under one name, and the name is what a
        client renders it as and what says whether the arguments are the state
        tool's: a call opened without one is nameless for the rest of the
        stream and its state updates are never read. Waiting costs nothing,
        because the announcement carries the whole argument string and
        appending to nothing leaves the client holding exactly it."""
        state = StreamState(thread_id="thread", run_id="run")
        args = {"line": "never named"}

        streamed = agui_handlers.on_tool_call_args_delta(
            ToolCallArgsDeltaEvent(tool_call_id="call_unnamed", tool_args_delta='{"line": '), state
        )

        assert streamed == [], streamed
        assert not state.tool_call_open("call_unnamed")

        announced = agui_handlers.on_tool_call_started(
            ToolCallStartedEvent(content="", tool=_announced("call_unnamed", "save_line", args)), state
        )

        started = [event for event in announced if event.type == EventType.TOOL_CALL_START]
        assert [event.tool_call_name for event in started] == ["save_line"], announced
        assert announced[-1].type == EventType.TOOL_CALL_ARGS, announced
        assert announced[-1].delta == json.dumps(args), announced[-1]  # type: ignore[attr-defined]
        assert state.tool_call_open("call_unnamed")


class TestACallThatFailedIsClosedRatherThanLeftPending:
    """A tool call the run refuses, or one that fails, is reported by an event
    of its own, and a client holds the call open until something ends it. Left
    unhandled that event reaches the client as an opaque passthrough carrying
    no result, and the call renders as pending until the run ends.
    """

    def test_a_call_refused_after_its_arguments_streamed_closes_with_what_agno_said(self):
        """A run declining a call it has already shown the client, here by the
        tool call limit, never starts or completes it, so the failure is the
        only event that can close it."""
        line = "the first of two"
        refused = "the second of two"
        client = _fragmenting_client(
            [
                (
                    "tools",
                    [(save_line.name, {"line": line}, "call_a"), (save_line.name, {"line": refused}, "call_b")],
                    5,
                ),
                ("content", "done"),
            ],
            [save_line],
            tool_call_limit=1,
        )

        response = client.post("/agui", json=make_request_body("write", state={"lines": []}))
        events = _events_of_completed_run(
            response,
            ran=[save_line.name, save_line.name],
            left_state={"lines": [line]},
        )
        _assert_the_client_accepts_the_tool_call_spans(events)

        # The whole argument string the client was shown, then a close of its
        # own carrying Agno's own account of the refusal.
        assert json.loads("".join(_args_deltas(events, "call_b"))) == {"line": refused}
        wire = [event["type"] for event in _tool_call_wire(events, "call_b")]
        assert wire[-2:] == ["TOOL_CALL_END", "TOOL_CALL_RESULT"], wire
        assert wire.count("TOOL_CALL_END") == 1, wire
        assert _results_for(events, "call_b") == [REFUSED_TOOL_CALL_ERROR]
        assert _raw_passthroughs_of(events, RunEvent.tool_call_error.value) == []

        # Closed where it was refused rather than at the end of the run, so
        # nothing the run says afterwards renders under a pending call.
        closed = next(
            position
            for position, event in enumerate(events)
            if event.get("type") == "TOOL_CALL_END" and event.get("toolCallId") == "call_b"
        )
        spoke_again = next(
            position for position, event in enumerate(events) if event.get("type") == "TEXT_MESSAGE_CONTENT"
        )
        assert events[spoke_again]["delta"] == "done"
        assert closed < spoke_again, get_event_types(events)

    def test_an_error_on_an_open_call_closes_it_with_what_went_wrong(self, agent_client):
        """A call still open when its failure arrives is closed by it, and the
        client is told what the failure said."""
        client, agent = agent_client
        tool = ToolExecution(tool_call_id="call_open", tool_name="save_line", tool_args={"line": "written"})

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallStartedEvent(content="", tool=tool)
            yield ToolCallErrorEvent(tool=tool, error="the tool broke")
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        wire = [event["type"] for event in _tool_call_wire(events, "call_open")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"], wire
        assert _results_for(events, "call_open") == ["the tool broke"]
        assert _raw_passthroughs_of(events, RunEvent.tool_call_error.value) == []

    def test_an_error_for_a_call_that_was_never_opened_says_nothing(self, agent_client):
        """Nothing is open to close, and an end for a call the client does not
        hold open is where its verifier stops reading the run."""
        client, agent = agent_client
        tool = ToolExecution(tool_call_id="call_ghost", tool_name="save_line", tool_args={"line": "never shown"})

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallErrorEvent(tool=tool, error="the tool broke")
            yield RunContentEvent(content="answered anyway")
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        assert _tool_call_wire(events, "call_ghost") == []
        assert _raw_passthroughs_of(events, RunEvent.tool_call_error.value) == []
        spoken = [event["delta"] for event in events if event.get("type") == "TEXT_MESSAGE_CONTENT"]
        assert spoken == ["answered anyway"], spoken
        assert "RUN_FINISHED" in get_event_types(events)

    def test_a_failure_the_completion_already_closed_is_carried_once(self, agent_client):
        """An ordinary tool failure is announced as a completion first, which
        closes the call and carries the same text as its result, so the failure
        behind it has nothing left to add."""
        client, agent = agent_client
        tool = ToolExecution(
            tool_call_id="call_broke",
            tool_name="save_line",
            tool_args={"line": "written"},
            result="the tool broke",
            tool_call_error=True,
        )

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallStartedEvent(content="", tool=tool)
            yield ToolCallCompletedEvent(content="", tool=tool)
            yield ToolCallErrorEvent(tool=tool, error="the tool broke")
            yield RunCompletedEvent(content="")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        _assert_the_client_accepts_the_tool_call_spans(events)
        wire = [event["type"] for event in _tool_call_wire(events, "call_broke")]
        assert wire == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"], wire
        assert _results_for(events, "call_broke") == ["the tool broke"]
        assert _raw_passthroughs_of(events, RunEvent.tool_call_error.value) == []

    def test_a_run_that_fails_mid_call_leaves_no_call_open_at_the_error(self, agent_client):
        """A client keeps one entry per open call and throws when a run ends
        with one left, whichever terminal event ended it. A run that fails
        while a call's arguments are still streaming is such a run."""
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield ToolCallArgsDeltaEvent(
                tool_call_id="call_cut", tool_name="save_line", tool_args_delta='{"line": "half'
            )
            yield RunErrorEvent(content="the model went away")

        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("write"))

        events = parse_sse_events(response.text)
        types = get_event_types(events)
        assert types[-1] == "RUN_ERROR", types
        _assert_the_client_accepts_the_tool_call_spans(events)

    def test_a_teams_failed_call_is_closed_by_the_same_handler(self):
        """A team's events are dispatched under the same names an agent's are,
        so the one handler entry serves both."""
        assert _normalize_event(TeamRunEvent.tool_call_error.value) == RunEvent.tool_call_error.value

        state = StreamState(thread_id="thread", run_id="run")
        state.start_tool_call("call_member")
        tool = ToolExecution(tool_call_id="call_member", tool_name="save_line", tool_args={"line": "written"})

        events = process_event(TeamToolCallErrorEvent(tool=tool, error="the tool broke"), state)

        assert [event.type for event in events] == [EventType.TOOL_CALL_END, EventType.TOOL_CALL_RESULT]
        assert json.loads(events[1].content) == "the tool broke"
        assert not state.tool_call_open("call_member")


class TestTheHelpersTheseTestsReadTheWireWith:
    """The helpers above read the wire the way a client reads it, deliberately
    not by calling the code they check, so a rule applied wrongly on both
    sides cannot agree with itself. What they refuse matters as much as what
    they accept: a helper that reads a frame it cannot parse as no frame at
    all satisfies every assertion here about something being absent, and one
    that reaches a library error says nothing about what the wire was
    missing."""

    def test_a_data_line_that_is_not_an_event_is_refused_rather_than_skipped(self):
        with pytest.raises(AssertionError, match="no event"):
            parse_sse_events('data: {"type": "RUN_STARTED"}\ndata: {oops\n')

    def test_a_pointer_naming_an_array_by_something_that_is_no_index_is_refused(self):
        """An array index is digits and nothing else, at every segment of a
        pointer and not only at its last: a token a client refuses outright is
        refused here rather than read as an index it never named."""
        with pytest.raises(AssertionError, match="no array index"):
            _client_document_after({"rows": [{"a": 1}]}, [{"op": "replace", "path": "/rows/01/a", "value": 2}])
        with pytest.raises(AssertionError, match="does not hold"):
            _client_document_after({"rows": [{"a": 1}]}, [{"op": "replace", "path": "/rows/-/a", "value": 2}])

    def test_an_addition_under_a_scalar_says_what_the_wire_was_missing(self):
        with pytest.raises(AssertionError, match="neither an object nor an array"):
            _client_document_after({"title": "Soup"}, [{"op": "add", "path": "/title/deeper", "value": 1}])
