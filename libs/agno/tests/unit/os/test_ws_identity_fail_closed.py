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
