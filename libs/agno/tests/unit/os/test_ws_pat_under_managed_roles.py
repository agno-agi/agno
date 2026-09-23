"""A service-account PAT is decided on its own scopes over the WebSocket, as on REST.

Under managed roles the configured provider decides from stored assignments. A PAT has no
subject there (its scopes are its ACL), so routing it through that provider denied every
PAT on the socket while the same token was admitted on ``POST /workflows/{id}/runs``.
The WebSocket gate now evaluates a PAT with the scope provider, like ``auth._provider_for``.
"""

import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz import Authorization  # noqa: E402

SECRET = "ws-pat-managed-roles-secret-32-bytes!!"
OS_ID = "ws-pat-os"
HANDSHAKE_EVENTS = ("connected", "authenticated", "ping")


def _managed_roles_app(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "managed.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], audience=OS_ID, algorithm="HS256")
    authz.define_role("viewer", ["agents:read"])  # any role: managed roles decide from the store
    return AgentOS(id=OS_ID, db=db, authorization=authz, telemetry=False).get_app()


def _patch_pat_identity(monkeypatch, *, principal: str, scopes: List[str]) -> None:
    async def fake_verify(token, app, client_key=None):
        account = SimpleNamespace(principal=principal, scopes=scopes)
        return SimpleNamespace(ok=True, status=None, account=account)

    monkeypatch.setattr("agno.os.router.verify_websocket_service_account", fake_verify)


def _capture_start_workflow(monkeypatch) -> List[Dict[str, Any]]:
    captured: List[Dict[str, Any]] = []

    async def fake_handler(websocket, message, os, **kwargs):
        captured.append({"message": message})
        await websocket.send_text(json.dumps({"event": "captured"}))

    monkeypatch.setattr("agno.os.router.handle_workflow_via_websocket", fake_handler)
    return captured


def _first_non_handshake_event(ws) -> Dict[str, Any]:
    for _ in range(10):
        frame = json.loads(ws.receive_text())
        if frame.get("event") not in HANDSHAKE_EVENTS:
            return frame
    raise AssertionError("no event arrived")


def _start_workflow_as_pat(app, monkeypatch, *, scopes: List[str]) -> Dict[str, Any]:
    _capture_start_workflow(monkeypatch)
    _patch_pat_identity(monkeypatch, principal="sa:runner", scopes=scopes)
    with TestClient(app).websocket_connect("/workflows/ws") as ws:
        ws.send_text(json.dumps({"action": "authenticate", "token": "agno_pat_fake"}))
        for _ in range(10):
            if json.loads(ws.receive_text()).get("event") == "authenticated":
                break
        ws.send_text(json.dumps({"action": "start-workflow", "workflow_id": "wf-1", "message": "hi"}))
        return _first_non_handshake_event(ws)


def test_a_pat_with_the_run_scope_is_admitted_under_managed_roles(tmp_path, monkeypatch):
    event = _start_workflow_as_pat(_managed_roles_app(tmp_path), monkeypatch, scopes=["workflows:run"])
    assert event["event"] == "captured", event


def test_a_pat_without_the_run_scope_is_still_refused(tmp_path, monkeypatch):
    event = _start_workflow_as_pat(_managed_roles_app(tmp_path), monkeypatch, scopes=["agents:read"])
    assert event["event"] != "captured", event
