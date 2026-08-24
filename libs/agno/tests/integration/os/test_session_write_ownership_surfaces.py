"""Session-write ownership on the run surfaces that do not go through the REST run routes.

``POST /agents|teams|workflows/{id}/runs`` is not the only way to create a run
against a caller-supplied ``session_id``. The workflow WebSocket, the A2A
interface, the AG-UI interface and the MCP run tools all pin the caller's
identity server-side and then take the session id straight from the request —
the same shape, and the same bleed, as the REST routes.

These are regressions for session-cross-user-history-bleed: a fix that only
guards the REST routes leaves every surface below open.
"""

import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

JWT_SECRET = "test-secret-for-write-ownership"
TEST_OS_ID = "test-write-ownership-os"
SECRET_TEXT = "wire-transfer PIN GRIMSBY-8807"


class ScriptedModel(Model):
    """A model that answers without a provider call."""

    def __init__(self, model_id: str, reply: str):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._reply = reply

    def _resp(self) -> ModelResponse:
        return ModelResponse(content=self._reply, role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs):
        return self._resp()

    async def ainvoke(self, *args, **kwargs):
        return self._resp()

    def invoke_stream(self, *args, **kwargs):
        yield self._resp()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._resp()

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return self._resp()

    def _parse_provider_response_delta(self, response):
        return self._resp()


def create_token(user_id: str, scopes: list[str] | None = None) -> str:
    payload = {
        "sub": user_id,
        "aud": TEST_OS_ID,
        "scopes": scopes
        or [
            "agents:read",
            "agents:run",
            "teams:read",
            "teams:run",
            "workflows:read",
            "workflows:run",
            "sessions:read",
            "sessions:write",
        ],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def history_agent(shared_db):
    return Agent(
        id="history-agent",
        name="history-agent",
        db=shared_db,
        model=ScriptedModel("scripted-1", "ok"),
        add_history_to_context=True,
        num_history_runs=5,
    )


@pytest.fixture
def history_workflow(shared_db, history_agent):
    return Workflow(
        id="history-workflow",
        name="history-workflow",
        db=shared_db,
        steps=[Step(name="step1", description="noop", agent=history_agent)],
    )


def _auth_config(user_isolation: bool) -> AuthorizationConfig:
    return AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256", user_isolation=user_isolation)


def _run_user_ids(db, session_id: str) -> set:
    return {r["user_id"] for r in db.get_runs(session_id=session_id, deserialize=False)[0]}


def _ws_start_workflow(client: TestClient, user: str, session_id: str, message: str) -> list:
    """Authenticate on the workflow socket, submit a run, and collect the frames."""
    frames: list = []
    with client.websocket_connect("/workflows/ws") as ws:
        ws.send_text(json.dumps({"action": "authenticate", "token": create_token(user)}))
        ws.send_text(
            json.dumps(
                {
                    "action": "start-workflow",
                    "workflow_id": "history-workflow",
                    "session_id": session_id,
                    "message": message,
                }
            )
        )
        for _ in range(8):
            try:
                frames.append(json.loads(ws.receive_text()))
            except Exception:
                break
            if frames[-1].get("event") == "error":
                break
    return frames


# ---------------------------------------------------------------------------
# Workflow WebSocket — mounted on every AgentOS, no feature flag
# ---------------------------------------------------------------------------


class TestWorkflowWebSocketOwnership:
    @pytest.mark.parametrize("isolation", [True, False])
    def test_start_workflow_refuses_a_foreign_session(self, history_workflow, isolation):
        agent_os = AgentOS(
            id=TEST_OS_ID,
            workflows=[history_workflow],
            db=history_workflow.db,
            telemetry=False,
            authorization=True,
            authorization_config=_auth_config(isolation),
        )
        client = TestClient(agent_os.get_app())
        sid = "ws-owned-by-c"

        assert (
            client.post(
                "/workflows/history-workflow/runs",
                data={"message": "opened by C", "stream": "false", "session_id": sid},
                headers=auth_header(create_token("user-c")),
            ).status_code
            == 200
        )

        frames = _ws_start_workflow(client, "user-d", sid, f"My private {SECRET_TEXT}")

        assert any(f.get("error") == "Session not found" for f in frames), frames
        assert _run_user_ids(history_workflow.db, sid) == {"user-c"}

    def test_owner_may_start_a_workflow_over_the_socket(self, history_workflow):
        """No-regression guard: the socket must still work for the session's owner."""
        agent_os = AgentOS(
            id=TEST_OS_ID,
            workflows=[history_workflow],
            db=history_workflow.db,
            telemetry=False,
            authorization=True,
            authorization_config=_auth_config(True),
        )
        client = TestClient(agent_os.get_app())
        sid = "ws-owned-by-c-2"
        client.post(
            "/workflows/history-workflow/runs",
            data={"message": "opened by C", "stream": "false", "session_id": sid},
            headers=auth_header(create_token("user-c")),
        )

        frames = _ws_start_workflow(client, "user-c", sid, "second turn")

        assert not any(f.get("error") == "Session not found" for f in frames), frames


# ---------------------------------------------------------------------------
# A2A — client-supplied contextId becomes the session id
# ---------------------------------------------------------------------------


def _a2a_send(client: TestClient, user: str, context_id: str, text: str):
    return client.post(
        "/a2a/agents/history-agent/v1/message:send",
        headers=auth_header(create_token(user)),
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": text}],
                    "messageId": "m1",
                    "contextId": context_id,
                }
            },
        },
    )


class TestA2AOwnership:
    @pytest.mark.parametrize("isolation", [True, False])
    def test_a2a_refuses_a_foreign_context_id(self, history_agent, isolation):
        pytest.importorskip("a2a")
        from agno.os.interfaces.a2a import A2A

        agent_os = AgentOS(
            id=TEST_OS_ID,
            agents=[history_agent],
            db=history_agent.db,
            telemetry=False,
            interfaces=[A2A(agents=[history_agent])],
            authorization=True,
            authorization_config=_auth_config(isolation),
        )
        client = TestClient(agent_os.get_app())
        sid = "a2a-owned-by-c"

        assert _a2a_send(client, "user-c", sid, "opened by C").status_code == 200
        resp = _a2a_send(client, "user-d", sid, f"My private {SECRET_TEXT}")

        # A real 404, not a 200 carrying a failed Task: the guard must sit
        # outside the handler's blanket ``except Exception``.
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "Session not found"
        assert _run_user_ids(history_agent.db, sid) == {"user-c"}

    def test_a2a_owner_may_continue(self, history_agent):
        pytest.importorskip("a2a")
        from agno.os.interfaces.a2a import A2A

        agent_os = AgentOS(
            id=TEST_OS_ID,
            agents=[history_agent],
            db=history_agent.db,
            telemetry=False,
            interfaces=[A2A(agents=[history_agent])],
            authorization=True,
            authorization_config=_auth_config(True),
        )
        client = TestClient(agent_os.get_app())
        sid = "a2a-owned-by-c-2"
        assert _a2a_send(client, "user-c", sid, "one").status_code == 200
        assert _a2a_send(client, "user-c", sid, "two").status_code == 200


# ---------------------------------------------------------------------------
# AG-UI — client-supplied threadId becomes the session id
# ---------------------------------------------------------------------------


def _agui_send(client: TestClient, user: str, thread_id: str, text: str):
    return client.post(
        "/agui",
        headers=auth_header(create_token(user)),
        json={
            "threadId": thread_id,
            "runId": f"run-{user}",
            "messages": [{"id": "1", "role": "user", "content": text}],
            "tools": [],
            "context": [],
            "state": {},
            "forwardedProps": {},
        },
    )


class TestAGUIOwnership:
    @pytest.mark.parametrize("isolation", [True, False])
    def test_agui_refuses_a_foreign_thread_id(self, history_agent, isolation):
        pytest.importorskip("ag_ui")
        from agno.os.interfaces.agui import AGUI

        agent_os = AgentOS(
            id=TEST_OS_ID,
            agents=[history_agent],
            db=history_agent.db,
            telemetry=False,
            interfaces=[AGUI(agent=history_agent)],
            authorization=True,
            authorization_config=_auth_config(isolation),
        )
        client = TestClient(agent_os.get_app())
        sid = "agui-owned-by-c"

        assert _agui_send(client, "user-c", sid, "opened by C").status_code == 200
        resp = _agui_send(client, "user-d", sid, f"My private {SECRET_TEXT}")

        # A real 404, not a RunErrorEvent inside a 200 SSE stream: the guard must
        # sit in the route handler, not inside ``run_entity``.
        assert resp.status_code == 404, resp.text
        assert _run_user_ids(history_agent.db, sid) == {"user-c"}

    def test_agui_owner_may_continue(self, history_agent):
        pytest.importorskip("ag_ui")
        from agno.os.interfaces.agui import AGUI

        agent_os = AgentOS(
            id=TEST_OS_ID,
            agents=[history_agent],
            db=history_agent.db,
            telemetry=False,
            interfaces=[AGUI(agent=history_agent)],
            authorization=True,
            authorization_config=_auth_config(True),
        )
        client = TestClient(agent_os.get_app())
        sid = "agui-owned-by-c-2"
        assert _agui_send(client, "user-c", sid, "one").status_code == 200
        assert _agui_send(client, "user-c", sid, "two").status_code == 200


# ---------------------------------------------------------------------------
# MCP run tools
# ---------------------------------------------------------------------------


class TestMCPRunToolOwnership:
    """The MCP run tools do not go through the REST run routes; a router-only
    fix leaves ``/mcp`` bleeding."""

    @pytest.mark.asyncio
    async def test_run_agent_refuses_a_foreign_session(self, history_agent):
        pytest.importorskip("fastmcp")
        from fastmcp import Client

        from agno.os import MCPServerConfig
        from agno.os.mcp import build_mcp_server

        agent_os = AgentOS(
            id=TEST_OS_ID,
            agents=[history_agent],
            db=history_agent.db,
            telemetry=False,
            mcp_server=MCPServerConfig(),
        )
        sid = "mcp-owned-by-c"

        async with Client(build_mcp_server(agent_os)) as client:
            await client.call_tool(
                "run_agent",
                {"agent_id": "history-agent", "message": "opened by C", "user_id": "user-c", "session_id": sid},
            )
            with pytest.raises(Exception, match="Session not found"):
                await client.call_tool(
                    "run_agent",
                    {
                        "agent_id": "history-agent",
                        "message": f"My private {SECRET_TEXT}",
                        "user_id": "user-d",
                        "session_id": sid,
                    },
                )

        assert _run_user_ids(history_agent.db, sid) == {"user-c"}

    @pytest.mark.asyncio
    async def test_run_agent_allows_the_owner_and_a_new_session(self, history_agent):
        pytest.importorskip("fastmcp")
        from fastmcp import Client

        from agno.os import MCPServerConfig
        from agno.os.mcp import build_mcp_server

        agent_os = AgentOS(
            id=TEST_OS_ID,
            agents=[history_agent],
            db=history_agent.db,
            telemetry=False,
            mcp_server=MCPServerConfig(),
        )
        sid = "mcp-owned-by-c-2"

        async with Client(build_mcp_server(agent_os)) as client:
            await client.call_tool(
                "run_agent",
                {"agent_id": "history-agent", "message": "one", "user_id": "user-c", "session_id": sid},
            )
            # The owner continues...
            await client.call_tool(
                "run_agent",
                {"agent_id": "history-agent", "message": "two", "user_id": "user-c", "session_id": sid},
            )
            # ...and omitting session_id still mints a fresh one.
            await client.call_tool("run_agent", {"agent_id": "history-agent", "message": "three", "user_id": "user-d"})

        assert _run_user_ids(history_agent.db, sid) == {"user-c"}
