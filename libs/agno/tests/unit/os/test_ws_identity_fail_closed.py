"""Workflow WS handlers must fail closed for identity-less JWTs under isolation.

REST routes 403 an authenticated caller with no identity (``get_scoped_user_id``).
The WS helper used to return ``None`` for the same state, which every handler
read as "unscoped caller" — skipping the run-ownership gates, so a signed token
with no ``sub`` could stream or continue any user's runs. These tests pin the
fix: the helper raises, and each handler answers with an error event before
touching the event stream or resolving any workflow.
"""

import json
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock

import pytest

from agno.os.middleware.user_scope import MISSING_USER_IDENTITY, SESSION_ID_REQUIRED_RECONNECT
from agno.os.routers.workflows.router import (
    WebSocketAuthContext,
    handle_workflow_continue_via_websocket,
    handle_workflow_subscription,
    handle_workflow_via_websocket,
)


class FakeWebSocket:
    def __init__(self):
        self.sent: List[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


def _isolated_ws_auth() -> WebSocketAuthContext:
    return WebSocketAuthContext(jwt_enabled=True, is_admin=False, user_isolation_enabled=True)


def _os_stub() -> SimpleNamespace:
    return SimpleNamespace(workflows=[], db=None, registry=None)


@pytest.fixture
def untouched_event_stream(monkeypatch):
    """An event stream that must never be reached by a refused caller."""
    stream = MagicMock()
    monkeypatch.setattr("agno.os.routers.workflows.router.get_event_stream", lambda: stream)
    return stream


@pytest.mark.asyncio
class TestIdentitylessTokenIsRefused:
    """message['user_id'] is None: the dispatcher overwrote it because the JWT
    carried no sub. Under isolation every handler must refuse, not skip the gate."""

    async def test_reconnect_refuses_before_event_stream(self, untouched_event_stream):
        ws = FakeWebSocket()
        await handle_workflow_subscription(
            ws,
            {"run_id": "r-1", "workflow_id": "wf-1", "session_id": "s-1", "user_id": None},
            _os_stub(),
            ws_auth=_isolated_ws_auth(),
        )
        assert ws.sent == [{"event": "error", "error": MISSING_USER_IDENTITY}]
        untouched_event_stream.get_run_status.assert_not_called()

    async def test_continue_refuses_before_ownership_check(self):
        ws = FakeWebSocket()
        await handle_workflow_continue_via_websocket(
            ws,
            {"run_id": "r-1", "workflow_id": "wf-1", "session_id": "s-1", "user_id": None},
            _os_stub(),
            ws_auth=_isolated_ws_auth(),
        )
        assert ws.sent == [{"event": "error", "error": MISSING_USER_IDENTITY}]

    async def test_start_workflow_refuses(self):
        ws = FakeWebSocket()
        await handle_workflow_via_websocket(
            ws,
            {"workflow_id": "wf-1", "message": "hi", "user_id": None},
            _os_stub(),
            ws_auth=_isolated_ws_auth(),
        )
        assert ws.sent == [{"event": "error", "error": MISSING_USER_IDENTITY}]

    async def test_empty_string_sub_is_refused_too(self):
        ws = FakeWebSocket()
        await handle_workflow_subscription(
            ws,
            {"run_id": "r-1", "workflow_id": "wf-1", "session_id": "s-1", "user_id": ""},
            _os_stub(),
            ws_auth=_isolated_ws_auth(),
        )
        assert ws.sent == [{"event": "error", "error": MISSING_USER_IDENTITY}]


@pytest.mark.asyncio
class TestControls:
    """The refusal is specific to identity-less tokens under isolation."""

    async def test_identified_caller_reaches_the_ownership_gate(self):
        # With an identity, the reconnect proceeds to the next gate (session_id required).
        ws = FakeWebSocket()
        await handle_workflow_subscription(
            ws,
            {"run_id": "r-1", "workflow_id": "wf-1", "user_id": "alice"},
            _os_stub(),
            ws_auth=_isolated_ws_auth(),
        )
        assert ws.sent == [{"event": "error", "error": SESSION_ID_REQUIRED_RECONNECT}]

    async def test_isolation_off_keeps_legacy_unscoped_reconnect(self, untouched_event_stream):
        # No isolation: an identity-less caller is legitimately unscoped (RBAC still applies
        # upstream) and the flow proceeds to the event-stream probe.
        untouched_event_stream.get_run_status = MagicMock(side_effect=Exception("probe reached"))
        ws = FakeWebSocket()
        await handle_workflow_subscription(
            ws,
            {"run_id": "r-1", "user_id": None},
            _os_stub(),
            ws_auth=WebSocketAuthContext(jwt_enabled=True, is_admin=False, user_isolation_enabled=False),
        )
        assert ws.sent and ws.sent[0]["error"] != MISSING_USER_IDENTITY

    async def test_admin_without_sub_is_not_refused(self, untouched_event_stream):
        untouched_event_stream.get_run_status = MagicMock(side_effect=Exception("probe reached"))
        ws = FakeWebSocket()
        await handle_workflow_subscription(
            ws,
            {"run_id": "r-1", "user_id": None},
            _os_stub(),
            ws_auth=WebSocketAuthContext(jwt_enabled=True, is_admin=True, user_isolation_enabled=True),
        )
        assert ws.sent and ws.sent[0]["error"] != MISSING_USER_IDENTITY


@pytest.mark.asyncio
class TestStartWorkflowNeverAdoptsTheClientFrameIdentity:
    """B12: the WS start path derives identity from the token, never the client
    frame - matching the HTTP run route (request.state.user_id, i.e. the JWT
    sub). The gap: a sub-less token under isolation-OFF used to keep a
    client-chosen user_id, letting the client claim a draft owner's identity
    at the draft-preview gate, which the HTTP route denies (actor=None)."""

    @staticmethod
    def _draft_db(tmp_path, owner="victim"):
        from agno.db.base import ComponentType
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(id="ws-identity-db", db_file=str(tmp_path / "ws_identity.db"))
        db.create_component_with_config(
            component_id="wf-draft",
            component_type=ComponentType.WORKFLOW,
            name="wf-draft",
            config={"name": "wf-draft"},
            stage="draft",
            user_id=owner,
        )
        return db

    @staticmethod
    def _record_resolution(monkeypatch):
        calls: List[dict] = []

        def fake_get_workflow_by_id(**kwargs):
            calls.append(kwargs)
            return None

        monkeypatch.setattr("agno.os.routers.workflows.router.get_workflow_by_id", fake_get_workflow_by_id)
        return calls

    async def test_subless_token_isolation_off_does_not_adopt_the_client_user_id(self, tmp_path, monkeypatch):
        db = self._draft_db(tmp_path)
        resolutions = self._record_resolution(monkeypatch)
        ws = FakeWebSocket()
        await handle_workflow_via_websocket(
            ws,
            # The client frame claims the draft owner's identity.
            {"workflow_id": "wf-draft", "message": "hi", "user_id": "victim", "version": 1},
            SimpleNamespace(workflows=[], db=db, registry=None),
            # Authenticated via JWT whose sub is absent; isolation OFF.
            ws_user_context={"user_id": None, "scopes": ["workflows:run"], "payload": {}},
            ws_auth=WebSocketAuthContext(jwt_enabled=True, is_admin=False, user_isolation_enabled=False),
        )
        # Denied at the preview gate (actor is the token's None, not "victim"):
        # same not-found the HTTP route answers, and resolution is never reached.
        assert ws.sent == [{"event": "error", "error": "Workflow wf-draft not found"}]
        assert resolutions == []

    async def test_empty_string_sub_does_not_adopt_the_client_user_id(self, tmp_path, monkeypatch):
        db = self._draft_db(tmp_path)
        resolutions = self._record_resolution(monkeypatch)
        ws = FakeWebSocket()
        await handle_workflow_via_websocket(
            ws,
            {"workflow_id": "wf-draft", "message": "hi", "user_id": "victim", "version": 1},
            SimpleNamespace(workflows=[], db=db, registry=None),
            ws_user_context={"user_id": "", "scopes": ["workflows:run"], "payload": {}},
            ws_auth=WebSocketAuthContext(jwt_enabled=True, is_admin=False, user_isolation_enabled=False),
        )
        assert ws.sent == [{"event": "error", "error": "Workflow wf-draft not found"}]
        assert resolutions == []

    async def test_token_sub_still_previews_its_own_draft(self, tmp_path, monkeypatch):
        # Control: the owner's own token passes the gate - proving the pin uses
        # the token identity rather than blanket-denying drafts over WS.
        db = self._draft_db(tmp_path, owner="victim")
        resolutions = self._record_resolution(monkeypatch)
        ws = FakeWebSocket()
        await handle_workflow_via_websocket(
            ws,
            {"workflow_id": "wf-draft", "message": "hi", "version": 1},
            SimpleNamespace(workflows=[], db=db, registry=None),
            ws_user_context={"user_id": "victim", "scopes": ["workflows:run"], "payload": {}},
            ws_auth=WebSocketAuthContext(jwt_enabled=True, is_admin=False, user_isolation_enabled=False),
        )
        assert len(resolutions) == 1  # the gate passed; resolution ran

    async def test_client_frame_never_overrides_a_token_sub(self, tmp_path, monkeypatch):
        # A token WITH a sub is pinned to it even when the frame claims the owner.
        db = self._draft_db(tmp_path, owner="victim")
        resolutions = self._record_resolution(monkeypatch)
        ws = FakeWebSocket()
        await handle_workflow_via_websocket(
            ws,
            {"workflow_id": "wf-draft", "message": "hi", "user_id": "victim", "version": 1},
            SimpleNamespace(workflows=[], db=db, registry=None),
            ws_user_context={"user_id": "mallory", "scopes": ["workflows:run"], "payload": {}},
            ws_auth=WebSocketAuthContext(jwt_enabled=True, is_admin=False, user_isolation_enabled=False),
        )
        assert ws.sent == [{"event": "error", "error": "Workflow wf-draft not found"}]
        assert resolutions == []


@pytest.mark.asyncio
class TestContinueNeverAdoptsTheClientFrameIdentity:
    """The continue twin derives identity exactly like the start path. A run
    started against a pinned draft carries that version as a stamp, and continue
    re-runs the draft-preview gate before trusting it. Without the same pin, a
    sub-less token under isolation-OFF kept the client frame's user_id and the
    gate matched the draft OWNER's identity - so naming the owner in the frame
    resumed their unpublished draft."""

    @staticmethod
    def _draft_db(tmp_path, owner="victim"):
        from agno.db.base import ComponentType
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(id="ws-continue-db", db_file=str(tmp_path / "ws_continue.db"))
        db.create_component_with_config(
            component_id="wf-draft",
            component_type=ComponentType.WORKFLOW,
            name="wf-draft",
            config={"name": "wf-draft"},
            stage="draft",
            user_id=owner,
        )
        return db

    @staticmethod
    def _record_resolution(monkeypatch):
        """The unpinned call returns the paused-run handle; a version-pinned
        call means the stamped-draft re-gate PASSED."""
        from agno.db.schemas.scheduler import COMPONENT_VERSION_METADATA_KEY

        calls: List[dict] = []

        class PausedWorkflowStub:
            id = "wf-draft"

            async def aget_run_output(self, **kwargs):
                return SimpleNamespace(is_paused=True, status=None, metadata={COMPONENT_VERSION_METADATA_KEY: 1})

        def fake_get_workflow_by_id(**kwargs):
            calls.append(kwargs)
            if kwargs.get("version") is not None:
                return None
            return PausedWorkflowStub()

        monkeypatch.setattr("agno.os.routers.workflows.router.get_workflow_by_id", fake_get_workflow_by_id)
        return calls

    async def _continue(self, db, frame_user_id, token_user_id):
        """Continue a stamped paused run as a non-admin JWT caller, isolation OFF."""
        ws = FakeWebSocket()
        frame = {"workflow_id": "wf-draft", "run_id": "r-1", "session_id": "s-1"}
        if frame_user_id is not None:
            frame["user_id"] = frame_user_id
        await handle_workflow_continue_via_websocket(
            ws,
            frame,
            SimpleNamespace(workflows=[], db=db, registry=None),
            ws_user_context={"user_id": token_user_id, "scopes": ["workflows:run"], "payload": {}},
            ws_auth=WebSocketAuthContext(jwt_enabled=True, is_admin=False, user_isolation_enabled=False),
        )
        return ws

    async def test_subless_token_isolation_off_does_not_adopt_the_client_user_id(self, tmp_path, monkeypatch):
        db = self._draft_db(tmp_path)
        resolutions = self._record_resolution(monkeypatch)
        # The client frame claims the draft owner's identity; the token has no sub.
        ws = await self._continue(db, "victim", None)
        # Denied at the stamped-version preview gate (actor is the token's None,
        # not "victim"), and the stamped draft is never resolved.
        assert ws.sent == [{"event": "error", "error": "Workflow wf-draft not found"}]
        assert len(resolutions) == 1

    async def test_empty_string_sub_does_not_adopt_the_client_user_id(self, tmp_path, monkeypatch):
        db = self._draft_db(tmp_path)
        resolutions = self._record_resolution(monkeypatch)
        ws = await self._continue(db, "victim", "")
        assert ws.sent == [{"event": "error", "error": "Workflow wf-draft not found"}]
        assert len(resolutions) == 1

    async def test_client_frame_never_overrides_a_token_sub(self, tmp_path, monkeypatch):
        db = self._draft_db(tmp_path)
        resolutions = self._record_resolution(monkeypatch)
        ws = await self._continue(db, "victim", "mallory")
        assert ws.sent == [{"event": "error", "error": "Workflow wf-draft not found"}]
        assert len(resolutions) == 1

    async def test_token_sub_still_continues_its_own_draft(self, tmp_path, monkeypatch):
        # Control: the owner's own token clears the gate and reaches the
        # stamped-draft resolution (which the stub reports as gone) - proving
        # the pin uses the token identity rather than blanket-denying drafts.
        db = self._draft_db(tmp_path, owner="victim")
        resolutions = self._record_resolution(monkeypatch)
        ws = await self._continue(db, None, "victim")
        assert ws.sent and "no longer available" in ws.sent[0]["error"]
        assert len(resolutions) == 2


@pytest.mark.asyncio
class TestDispatcherPassesTheTokenContextToContinue:
    """The pin only fires when the dispatcher hands the token context down, so
    pin the wiring as well as the handler."""

    async def test_continue_branch_forwards_ws_user_context(self, tmp_path, monkeypatch):
        import agno.os.router as os_router
        from agno.db.sqlite import SqliteDb
        from agno.os import AgentOS
        from fastapi.testclient import TestClient

        captured: List[dict] = []

        async def fake_handler(websocket, message, os, **kwargs):
            captured.append(kwargs)
            await websocket.send_text(json.dumps({"event": "captured"}))

        monkeypatch.setattr(os_router, "handle_workflow_continue_via_websocket", fake_handler)

        app = AgentOS(
            db=SqliteDb(id="ws-dispatch-db", db_file=str(tmp_path / "ws_dispatch.db")), telemetry=False
        ).get_app()
        with TestClient(app).websocket_connect("/workflows/ws") as ws:
            ws.send_text(json.dumps({"action": "continue-workflow", "workflow_id": "wf-1", "run_id": "r-1"}))
            for _ in range(10):
                frame = json.loads(ws.receive_text())
                if frame.get("event") == "captured":
                    break
            else:
                raise AssertionError("handler was never reached")

        assert captured and "ws_user_context" in captured[0]
