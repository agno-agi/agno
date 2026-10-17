"""AG-UI resume honours the admin-approval gate, on every channel that resumes.

A trailing ToolMessage on POST /agui continues a paused run with caller-supplied answers,
which is a /continue. So does an entry in the request's resume array, which names an
interrupt the paused run reported. REST, MCP and the WebSocket refuse to continue a run
paused on an admin-required approval; without the same gate here, the run's initiator
could confirm the approval themselves by replaying the tool call over AG-UI, or by
answering the same pause through the array.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, NamedTuple, Optional
from unittest.mock import AsyncMock

import jwt
import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core.types import ResumeEntry, ToolMessage
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.agui.resume import answers_in_this_request_address, find_resume_target_run_id

JWT_SECRET = "agui-approval-gate-secret-32-bytes-long!"
OS_ID = "agui-approval-os"
THREAD = "thread-gate"


def _sse_events(text: str) -> List[Dict[str, Any]]:
    return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]


def _interrupt_ids(response: Any) -> List[str]:
    """The ids a client is handed to answer this pause's interrupts under."""
    terminal = next(e for e in _sse_events(response.text) if e["type"] == "RUN_FINISHED")
    return [interrupt["id"] for interrupt in terminal["outcome"]["interrupts"]]


def _runs_continued(response: Any) -> set:
    """The runs the events of this response were produced by, as the client reads them."""
    return {
        event["event"]["run_id"]
        for event in _sse_events(response.text)
        if event["type"] == "RAW" and "run_id" in event.get("event", {})
    }


def _resolved(interrupt_id: str, payload: str = "blue is set") -> Dict[str, Any]:
    return {"interruptId": interrupt_id, "status": "resolved", "payload": payload}


def _headers(scopes: List[str], user_id: str = "initiator") -> dict:
    payload = {
        "sub": user_id,
        "aud": OS_ID,
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, JWT_SECRET, algorithm='HS256')}"}


class _ScriptedModel(Model):
    """Calls the client tool on its first ``pause_turns`` turns, then answers in text.

    Raising ``pause_turns`` parks a second paused run in the same session, which is what
    a request answering one run while naming another needs to exist at all.
    """

    def __init__(self):
        super().__init__(id="scripted", name="scripted", provider="test")
        self.turns = 0
        self.pause_turns = 1

    def _next(self, messages: List[Any]) -> ModelResponse:
        self.turns += 1
        if self.turns <= self.pause_turns:
            function = {"name": "change_background", "arguments": json.dumps({"color": "blue"})}
            return ModelResponse(
                role="assistant", tool_calls=[{"id": f"call_{self.turns}", "type": "function", "function": function}]
            )
        return ModelResponse(role="assistant", content="all done", event=ModelResponseEvent.assistant_response.value)

    def invoke(self, messages=None, *args, **kwargs) -> ModelResponse:
        return self._next(messages or [])

    async def ainvoke(self, messages=None, *args, **kwargs) -> ModelResponse:
        return self._next(messages or [])

    def invoke_stream(self, messages=None, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._next(messages or [])

    async def ainvoke_stream(self, messages=None, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._next(messages or [])

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class _Harness(NamedTuple):
    db: Any
    post: Callable[..., Any]
    resume_messages: List[Dict[str, Any]]
    agent: Agent
    model: _ScriptedModel
    user: Dict[str, Any]
    tool_call_id: str
    interrupt_id: str


@pytest.fixture
def harness(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agui.db"))
    model = _ScriptedModel()
    agent = Agent(id="gate-agent", model=model, db=db, telemetry=False)
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        # The pause's terminal is what hands a client the interrupt ids its resume array
        # answers under, so the array channel cannot be exercised without it.
        interfaces=[AGUI(agent=agent, emit_interrupt_outcome=True)],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
        telemetry=False,
    )
    client = TestClient(agent_os.get_app())
    frontend_tool = {
        "name": "change_background",
        "description": "Change the page background",
        "parameters": {"type": "object", "properties": {"color": {"type": "string"}}},
    }

    def post(run_id: str, messages: list, headers: dict, resume: Optional[list] = None):
        body: Dict[str, Any] = {"threadId": THREAD, "runId": run_id, "state": {}, "messages": messages}
        if resume is not None:
            body["resume"] = resume
        return client.post(
            "/agui", json={**body, "tools": [frontend_tool], "context": [], "forwardedProps": {}}, headers=headers
        )

    # Pause the run on the client tool, then build the resume payload.
    user = {"id": "u1", "role": "user", "content": "go"}
    paused = post("run-1", [user], _headers(["agents:run"]))
    assert paused.status_code == 200, paused.text
    call = next(e for e in _sse_events(paused.text) if e["type"] == "TOOL_CALL_START")
    function = {"name": "change_background", "arguments": json.dumps({"color": "blue"})}
    assistant = {
        "id": "a1",
        "role": "assistant",
        "toolCalls": [{"id": call["toolCallId"], "type": "function", "function": function}],
    }
    tool_message = {"id": "t1", "role": "tool", "toolCallId": call["toolCallId"], "content": "blue is set"}
    resume_messages = [user, assistant, tool_message]
    (interrupt_id,) = _interrupt_ids(paused)
    return _Harness(db, post, resume_messages, agent, model, user, call["toolCallId"], interrupt_id)


def test_resume_is_refused_while_an_admin_approval_is_pending(harness):
    db, post, resume_messages = harness.db, harness.post, harness.resume_messages
    db.get_approvals = AsyncMock(return_value=([{"id": "a1", "status": "pending"}], 1))

    resp = post("run-2", resume_messages, _headers(["agents:run"]))

    assert resp.status_code == 403
    assert "admin approval" in resp.json()["detail"]
    kwargs = db.get_approvals.await_args.kwargs
    assert kwargs["status"] == "pending" and kwargs["approval_type"] == "required"
    assert kwargs["run_id"] == "run-1"  # the paused run was resolved from the session before the gate decided


def test_approval_admin_may_still_resume(harness):
    db, post, resume_messages = harness.db, harness.post, harness.resume_messages
    db.get_approvals = AsyncMock(return_value=([{"id": "a1", "status": "pending"}], 1))

    resp = post("run-2", resume_messages, _headers(["agents:run", "approvals:write"]))

    assert resp.status_code == 200, resp.text
    assert [e["type"] for e in _sse_events(resp.text)][-1] == "RUN_FINISHED"
    db.get_approvals.assert_not_awaited()


def test_resume_proceeds_when_nothing_is_pending(harness):
    db, post, resume_messages = harness.db, harness.post, harness.resume_messages
    db.get_approvals = AsyncMock(return_value=([], 0))

    resp = post("run-2", resume_messages, _headers(["agents:run"]))

    assert resp.status_code == 200, resp.text
    assert [e["type"] for e in _sse_events(resp.text)][-1] == "RUN_FINISHED"


# --- The protocol's own resume channel ---------------------------------------


def test_the_resume_array_is_refused_while_an_admin_approval_is_pending(harness):
    """The array continues the same paused run, so it meets the same refusal.

    Asserted over what the client receives: a 403 whose body is the refusal, and not one
    stream event, because a gate that let the stream open could only report the refusal as
    an event inside a 200 the caller already succeeded on.
    """
    db, post = harness.db, harness.post
    db.get_approvals = AsyncMock(return_value=([{"id": "a1", "status": "pending"}], 1))

    resp = post("run-2", [harness.user], _headers(["agents:run"]), resume=[_resolved(harness.interrupt_id)])

    assert resp.status_code == 403
    assert "admin approval" in resp.json()["detail"]
    assert _sse_events(resp.text) == []
    assert db.get_approvals.await_args.kwargs["run_id"] == "run-1"


def test_both_resume_channels_refuse_one_paused_run_alike(harness):
    """Neither channel is the way around the other for the same pending approval."""
    db, post = harness.db, harness.post
    db.get_approvals = AsyncMock(return_value=([{"id": "a1", "status": "pending"}], 1))

    by_tool_message = post("run-2", harness.resume_messages, _headers(["agents:run"]))
    by_array = post("run-3", [harness.user], _headers(["agents:run"]), resume=[_resolved(harness.interrupt_id)])

    assert by_array.status_code == by_tool_message.status_code == 403
    assert by_array.json()["detail"] == by_tool_message.json()["detail"]
    assert _sse_events(by_array.text) == _sse_events(by_tool_message.text) == []


def test_the_resume_array_proceeds_when_nothing_is_pending(harness):
    """The gate refuses a pending approval rather than the channel itself."""
    db, post = harness.db, harness.post
    db.get_approvals = AsyncMock(return_value=([], 0))

    resp = post("run-2", [harness.user], _headers(["agents:run"]), resume=[_resolved(harness.interrupt_id)])

    assert resp.status_code == 200, resp.text
    assert [e["type"] for e in _sse_events(resp.text)][-1] == "RUN_FINISHED"
    assert _runs_continued(resp) == {"run-1"}


def test_the_gate_asks_about_the_run_a_two_channel_request_continues(harness):
    """A request carrying both channels has one answer to which run is continued.

    The run that continues is the first paused one in the session either key finds, so a
    gate reading the array alone would ask its question about the other paused run, and a
    pending approval on the run actually continued would go unseen. The run continued is
    read off the events the client receives, and the gate is held to that same run.
    """
    db, post = harness.db, harness.post
    harness.model.pause_turns = 2
    second = post("run-2", [harness.user], _headers(["agents:run"]))
    assert second.status_code == 200, second.text
    (second_interrupt,) = _interrupt_ids(second)
    assert second_interrupt != harness.interrupt_id
    db.get_approvals = AsyncMock(return_value=([], 0))

    resp = post("run-3", harness.resume_messages, _headers(["agents:run"]), resume=[_resolved(second_interrupt)])

    assert resp.status_code == 200, resp.text
    assert _runs_continued(resp) == {"run-1"}
    assert db.get_approvals.await_args.kwargs["run_id"] == "run-1"


# --- One lookup under the gate and the resume that follows it ----------------


async def test_the_admission_lookup_reads_a_paused_run_on_either_key(harness):
    """The gate's read-only lookup is callable, and finds the run both channels name.

    It and the resolvers that continue the run reach the paused run through one helper, so
    a signature change under either stops here rather than at the wire, where it reached
    the client as a 500 before the stream opened.
    """
    found_by_tool_message = await find_resume_target_run_id(
        harness.agent,
        THREAD,
        tool_messages=[ToolMessage(id="t1", role="tool", tool_call_id=harness.tool_call_id, content="blue is set")],
    )
    found_by_array = await find_resume_target_run_id(
        harness.agent,
        THREAD,
        resume_entries=[ResumeEntry(interrupt_id=harness.interrupt_id, status="resolved", payload="blue is set")],
    )

    assert found_by_tool_message == found_by_array == "run-1"


async def test_an_unanswered_session_has_no_admission_target(harness):
    """Nothing to gate when neither key names a paused run, so the request runs fresh."""
    assert await find_resume_target_run_id(harness.agent, THREAD) is None
    assert (
        await find_resume_target_run_id(
            harness.agent,
            THREAD,
            resume_entries=[ResumeEntry(interrupt_id="no-such-interrupt", status="resolved", payload="x")],
        )
        is None
    )


def test_one_predicate_matches_what_either_channel_names(harness):
    """Both callers build the predicate here, so neither can key a lookup its own way."""
    session = harness.agent.get_session(session_id=THREAD)
    (requirement,) = next(run for run in session.runs if run.run_id == "run-1").requirements

    assert answers_in_this_request_address(
        resume_entries=[ResumeEntry(interrupt_id=harness.interrupt_id, status="resolved")]
    )(requirement)
    assert answers_in_this_request_address(
        tool_messages=[ToolMessage(id="t1", role="tool", tool_call_id=harness.tool_call_id, content="blue is set")]
    )(requirement)
    assert not answers_in_this_request_address()(requirement)
