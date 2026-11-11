"""AG-UI resume honours the admin-approval gate.

A trailing ToolMessage on POST /agui continues a paused run with caller-supplied answers,
which is a /continue. REST, MCP and the WebSocket refuse to continue a run paused on an
admin-required approval; without the same gate here, the run's initiator could confirm the
approval themselves by replaying the tool call over AG-UI.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncIterator, Dict, Iterator, List
from unittest.mock import AsyncMock

import jwt
import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.interfaces.agui import AGUI

JWT_SECRET = "agui-approval-gate-secret-32-bytes-long!"
OS_ID = "agui-approval-os"


def _sse_events(text: str) -> List[Dict[str, Any]]:
    return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]


def _headers(scopes: List[str], user_id: str = "initiator") -> dict:
    payload = {
        "sub": user_id,
        "aud": OS_ID,
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, JWT_SECRET, algorithm='HS256')}"}


class _ScriptedModel(Model):
    """Calls the client tool on its first turn and answers in text afterwards."""

    def __init__(self):
        super().__init__(id="scripted", name="scripted", provider="test")
        self.turns = 0

    def _next(self, messages: List[Any]) -> ModelResponse:
        self.turns += 1
        if self.turns == 1:
            function = {"name": "change_background", "arguments": json.dumps({"color": "blue"})}
            return ModelResponse(
                role="assistant", tool_calls=[{"id": "call_1", "type": "function", "function": function}]
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


@pytest.fixture
def harness(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agui.db"))
    agent = Agent(id="gate-agent", model=_ScriptedModel(), db=db, telemetry=False)
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        interfaces=[AGUI(agent=agent)],
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

    def post(run_id: str, messages: list, headers: dict):
        body = {"threadId": "thread-gate", "runId": run_id, "state": {}, "messages": messages}
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
    return db, post, resume_messages


def test_resume_is_refused_while_an_admin_approval_is_pending(harness):
    db, post, resume_messages = harness
    db.get_approvals = AsyncMock(return_value=([{"id": "a1", "status": "pending"}], 1))

    resp = post("run-2", resume_messages, _headers(["agents:run"]))

    assert resp.status_code == 403
    assert "admin approval" in resp.json()["detail"]
    kwargs = db.get_approvals.await_args.kwargs
    assert kwargs["status"] == "pending" and kwargs["approval_type"] == "required"
    assert kwargs["run_id"]  # the paused run was resolved from the session before the gate decided


def test_approval_admin_may_still_resume(harness):
    db, post, resume_messages = harness
    db.get_approvals = AsyncMock(return_value=([{"id": "a1", "status": "pending"}], 1))

    resp = post("run-2", resume_messages, _headers(["agents:run", "approvals:write"]))

    assert resp.status_code == 200, resp.text
    assert [e["type"] for e in _sse_events(resp.text)][-1] == "RUN_FINISHED"
    db.get_approvals.assert_not_awaited()


def test_resume_proceeds_when_nothing_is_pending(harness):
    db, post, resume_messages = harness
    db.get_approvals = AsyncMock(return_value=([], 0))

    resp = post("run-2", resume_messages, _headers(["agents:run"]))

    assert resp.status_code == 200, resp.text
    assert [e["type"] for e in _sse_events(resp.text)][-1] == "RUN_FINISHED"
