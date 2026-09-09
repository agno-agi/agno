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
from agno.os.scopes import AgentOSScope


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
        from fastapi.testclient import TestClient

        import agno.os.router as os_router
        from agno.db.sqlite import SqliteDb
        from agno.os import AgentOS

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

        # Assert the VALUE, not the key: forwarding ws_user_context=None keeps
        # the key present while disabling the pin entirely, because the handler
        # only derives identity from the token when a context is supplied.
        assert captured
        assert captured[0].get("ws_user_context") is not None
        assert captured[0].get("ws_auth") is not None


# ---------------------------------------------------------------------------
# The configured admin scope is the only admin signal
# ---------------------------------------------------------------------------

WS_JWT_SECRET = "ws-identity-pin-secret"
WS_OS_ID = "ws-identity-pin-os"
CUSTOM_ADMIN_SCOPE = "custom:admin"


def _draft_component_db(tmp_path, db_id: str, owner: str = "victim"):
    """A db holding one draft-stage workflow component owned by ``owner``."""
    from agno.db.base import ComponentType
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(id=db_id, db_file=str(tmp_path / (db_id + ".db")))
    db.create_component_with_config(
        component_id="wf-draft",
        component_type=ComponentType.WORKFLOW,
        name="wf-draft",
        config={"name": "wf-draft"},
        stage="draft",
        user_id=owner,
    )
    return db


def _gate_spy(monkeypatch) -> List[dict]:
    """Record the actor every draft-preview gate decision runs as."""
    import agno.os.routers.workflows.router as wf_router

    real = wf_router.allow_draft_preview
    calls: List[dict] = []

    def spy(db, component_id, version, actor, privileged=False):
        result = real(db, component_id, version, actor, privileged=privileged)
        calls.append({"actor": actor, "privileged": privileged, "result": result})
        return result

    monkeypatch.setattr(wf_router, "allow_draft_preview", spy)
    return calls


def _record_start_resolution(monkeypatch) -> List[dict]:
    calls: List[dict] = []

    def fake_get_workflow_by_id(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr("agno.os.routers.workflows.router.get_workflow_by_id", fake_get_workflow_by_id)
    return calls


def _record_continue_resolution(monkeypatch) -> List[dict]:
    """Serve a paused run stamped with draft version 1, so continue reaches the
    stamped-version preview gate; a version-pinned call means the gate PASSED."""
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


@pytest.mark.asyncio
class TestAdminIsOnlyWhatTheDispatcherConfigured:
    """A deployment can configure its own admin scope, and the WS dispatcher
    evaluates THAT scope when deciding whether to overwrite the client frame's
    user_id. A handler that re-derives admin from the DEFAULT scope name
    disagrees with the dispatcher in every deployment that configures a custom
    one, and the disagreement is exploitable: a token carrying the default
    scope name as an ORDINARY scope is non-admin to the dispatcher (which then
    leaves the frame's user_id alone) and admin to the handler (which then
    keeps it), so the frame chooses the actor the draft-preview gate runs as.
    """

    @staticmethod
    def _forged_admin_context():
        # Ordinary run scope plus the literal default admin scope name, which
        # this deployment does not treat as admin.
        return {"user_id": None, "scopes": ["workflows:run", AgentOSScope.ADMIN.value], "payload": {}}

    @staticmethod
    def _non_admin_auth():
        return WebSocketAuthContext(jwt_enabled=True, is_admin=False, user_isolation_enabled=False)

    @staticmethod
    def _admin_auth():
        return WebSocketAuthContext(jwt_enabled=True, is_admin=True, user_isolation_enabled=False)

    async def test_start_ignores_the_default_scope_name(self, tmp_path, monkeypatch):
        db = _draft_component_db(tmp_path, "ws-custom-admin-start")
        gate = _gate_spy(monkeypatch)
        resolutions = _record_start_resolution(monkeypatch)
        ws = FakeWebSocket()
        await handle_workflow_via_websocket(
            ws,
            {"workflow_id": "wf-draft", "message": "hi", "user_id": "victim", "version": 1},
            SimpleNamespace(workflows=[], db=db, registry=None),
            ws_user_context=self._forged_admin_context(),
            ws_auth=self._non_admin_auth(),
        )
        # The gate runs as the token's (absent) identity, never as the frame's.
        assert [c["actor"] for c in gate] == [None]
        assert ws.sent == [{"event": "error", "error": "Workflow wf-draft not found"}]
        assert resolutions == []

    async def test_continue_ignores_the_default_scope_name(self, tmp_path, monkeypatch):
        db = _draft_component_db(tmp_path, "ws-custom-admin-continue")
        gate = _gate_spy(monkeypatch)
        resolutions = _record_continue_resolution(monkeypatch)
        ws = FakeWebSocket()
        await handle_workflow_continue_via_websocket(
            ws,
            {"workflow_id": "wf-draft", "run_id": "r-1", "session_id": "s-1", "user_id": "victim"},
            SimpleNamespace(workflows=[], db=db, registry=None),
            ws_user_context=self._forged_admin_context(),
            ws_auth=self._non_admin_auth(),
        )
        assert [c["actor"] for c in gate] == [None]
        assert ws.sent == [{"event": "error", "error": "Workflow wf-draft not found"}]
        # Only the working handle was resolved; the stamped draft never was.
        assert len(resolutions) == 1

    async def test_start_honest_owner_still_previews_its_own_draft(self, tmp_path, monkeypatch):
        # Control: dropping the hardcoded scope test must not deny the owner.
        db = _draft_component_db(tmp_path, "ws-custom-admin-owner-start")
        gate = _gate_spy(monkeypatch)
        resolutions = _record_start_resolution(monkeypatch)
        ws = FakeWebSocket()
        await handle_workflow_via_websocket(
            ws,
            {"workflow_id": "wf-draft", "message": "hi", "version": 1},
            SimpleNamespace(workflows=[], db=db, registry=None),
            ws_user_context={"user_id": "victim", "scopes": ["workflows:run"], "payload": {}},
            ws_auth=self._non_admin_auth(),
        )
        assert gate == [{"actor": "victim", "privileged": False, "result": True}]
        assert len(resolutions) == 1

    async def test_start_configured_admin_is_still_admin(self, tmp_path, monkeypatch):
        # Control: a caller the dispatcher DID rule admin keeps the admin
        # branch - the frame's user_id survives as the act-on-behalf actor.
        db = _draft_component_db(tmp_path, "ws-custom-admin-admin-start")
        gate = _gate_spy(monkeypatch)
        resolutions = _record_start_resolution(monkeypatch)
        ws = FakeWebSocket()
        await handle_workflow_via_websocket(
            ws,
            {"workflow_id": "wf-draft", "message": "hi", "user_id": "victim", "version": 1},
            SimpleNamespace(workflows=[], db=db, registry=None),
            ws_user_context={"user_id": "root", "scopes": [CUSTOM_ADMIN_SCOPE], "payload": {}},
            ws_auth=self._admin_auth(),
        )
        assert gate == [{"actor": "victim", "privileged": True, "result": True}]
        assert len(resolutions) == 1

    async def test_continue_configured_admin_is_still_admin(self, tmp_path, monkeypatch):
        db = _draft_component_db(tmp_path, "ws-custom-admin-admin-continue")
        gate = _gate_spy(monkeypatch)
        resolutions = _record_continue_resolution(monkeypatch)
        ws = FakeWebSocket()
        await handle_workflow_continue_via_websocket(
            ws,
            {"workflow_id": "wf-draft", "run_id": "r-1", "session_id": "s-1", "user_id": "victim"},
            SimpleNamespace(workflows=[], db=db, registry=None),
            ws_user_context={"user_id": "root", "scopes": [CUSTOM_ADMIN_SCOPE], "payload": {}},
            ws_auth=self._admin_auth(),
        )
        assert gate == [{"actor": "victim", "privileged": True, "result": True}]
        # The gate passed, so the stamped draft was resolved.
        assert len(resolutions) == 2


def _issue_ws_token(*, sub, scopes: List[str]) -> str:
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    payload = {
        "aud": WS_OS_ID,
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    if sub is not None:
        payload["sub"] = sub
    return pyjwt.encode(payload, WS_JWT_SECRET, algorithm="HS256")


def _custom_admin_scope_app(db):
    """An AgentOS whose admin scope is configured to a non-default value."""
    from agno.os import AgentOS
    from agno.os.config import AuthorizationConfig

    return AgentOS(
        id=WS_OS_ID,
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[WS_JWT_SECRET],
            algorithm="HS256",
            admin_scope=CUSTOM_ADMIN_SCOPE,
            user_isolation=False,
        ),
        telemetry=False,
    ).get_app()


def _authenticate_ws(ws, token: str) -> dict:
    ws.send_text(json.dumps({"action": "authenticate", "token": token}))
    for _ in range(10):
        frame = json.loads(ws.receive_text())
        if frame.get("event") == "authenticated":
            return frame
        assert frame.get("event") != "auth_error", frame
    raise AssertionError("socket never authenticated")


def _drain_until_error(ws) -> dict:
    for _ in range(10):
        frame = json.loads(ws.receive_text())
        if frame.get("event") == "error":
            return frame
    raise AssertionError("no error frame arrived")


class TestCustomAdminScopeOverTheRealSocket:
    """End-to-end over the dispatcher: with a custom admin scope configured, a
    sub-less token carrying the DEFAULT admin scope name as an ordinary scope
    is a plain caller, and the draft-preview gate must never run as the actor
    its frame names."""

    _FORGED_SCOPES = ["workflows:run", AgentOSScope.ADMIN.value]

    def test_start_gate_never_runs_as_the_frame_user(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        db = _draft_component_db(tmp_path, "ws-e2e-start")
        gate = _gate_spy(monkeypatch)
        resolutions = _record_start_resolution(monkeypatch)

        with TestClient(_custom_admin_scope_app(db)).websocket_connect("/workflows/ws") as ws:
            _authenticate_ws(ws, _issue_ws_token(sub=None, scopes=self._FORGED_SCOPES))
            ws.send_text(
                json.dumps(
                    {
                        "action": "start-workflow",
                        "workflow_id": "wf-draft",
                        "message": "hi",
                        "user_id": "victim",
                        "version": 1,
                    }
                )
            )
            assert _drain_until_error(ws) == {"event": "error", "error": "Workflow wf-draft not found"}

        assert [c["actor"] for c in gate] == [None]
        assert resolutions == []

    def test_continue_gate_never_runs_as_the_frame_user(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        db = _draft_component_db(tmp_path, "ws-e2e-continue")
        gate = _gate_spy(monkeypatch)
        resolutions = _record_continue_resolution(monkeypatch)

        with TestClient(_custom_admin_scope_app(db)).websocket_connect("/workflows/ws") as ws:
            _authenticate_ws(ws, _issue_ws_token(sub=None, scopes=self._FORGED_SCOPES))
            ws.send_text(
                json.dumps(
                    {
                        "action": "continue-workflow",
                        "workflow_id": "wf-draft",
                        "run_id": "r-1",
                        "session_id": "s-1",
                        "user_id": "victim",
                    }
                )
            )
            assert _drain_until_error(ws) == {"event": "error", "error": "Workflow wf-draft not found"}

        assert [c["actor"] for c in gate] == [None]
        assert len(resolutions) == 1

    def test_owner_token_still_previews_its_own_draft_over_the_socket(self, tmp_path, monkeypatch):
        # Control: the deployment still works for the honest owner.
        from fastapi.testclient import TestClient

        db = _draft_component_db(tmp_path, "ws-e2e-owner")
        gate = _gate_spy(monkeypatch)
        resolutions = _record_start_resolution(monkeypatch)

        with TestClient(_custom_admin_scope_app(db)).websocket_connect("/workflows/ws") as ws:
            _authenticate_ws(ws, _issue_ws_token(sub="victim", scopes=["workflows:run"]))
            ws.send_text(
                json.dumps(
                    {
                        "action": "start-workflow",
                        "workflow_id": "wf-draft",
                        "message": "hi",
                        "version": 1,
                    }
                )
            )
            _drain_until_error(ws)

        assert gate == [{"actor": "victim", "privileged": False, "result": True}]
        assert len(resolutions) == 1

    def test_configured_admin_token_is_still_admin_over_the_socket(self, tmp_path, monkeypatch):
        # Control: the deployment's real admin scope keeps admin behaviour,
        # including acting on behalf of the user_id in the frame.
        from fastapi.testclient import TestClient

        db = _draft_component_db(tmp_path, "ws-e2e-admin")
        gate = _gate_spy(monkeypatch)
        resolutions = _record_start_resolution(monkeypatch)

        with TestClient(_custom_admin_scope_app(db)).websocket_connect("/workflows/ws") as ws:
            _authenticate_ws(ws, _issue_ws_token(sub="root", scopes=["workflows:run", CUSTOM_ADMIN_SCOPE]))
            ws.send_text(
                json.dumps(
                    {
                        "action": "start-workflow",
                        "workflow_id": "wf-draft",
                        "message": "hi",
                        "user_id": "victim",
                        "version": 1,
                    }
                )
            )
            _drain_until_error(ws)

        assert gate == [{"actor": "victim", "privileged": True, "result": True}]
        assert len(resolutions) == 1
